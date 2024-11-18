"""OpenRouter API客户端模块"""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .config import Config
from .tools.exceptions import APIError

logger = logging.getLogger(__name__)

class OpenrouterResponse:
    """OpenRouter API响应包装器"""
    
    def __init__(self, message: Dict[str, Any], http_response: httpx.Response):
        self.message = message
        self.http_response = http_response

    def parse(self) -> Dict[str, Any]:
        """解析响应消息"""
        return self.message

class OpenrouterClient:
    """OpenRouter API客户端"""
        
    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model: Optional[str] = None
    ):
        """
        初始化OpenRouter客户端。
        
        Args:
            base_url: API基础URL
            api_key: API密钥
            model: 模型名称
        """
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.beta = self.Beta(self)
        self._initialized = False
        self.config = Config.get_instance()
        
    async def initialize(self) -> 'OpenrouterClient':
        """
        初始化客户端并测试连接。
        
        Returns:
            初始化后的客户端实例
            
        Raises:
            RuntimeError: 连接失败时抛出
        """
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.base_url}/models")
                response.raise_for_status()
            self._initialized = True
            return self
        except Exception as e:
            raise RuntimeError(f"连接OpenRouter失败: {e}")
            
    class Beta:
        """Beta API接口"""
        
        def __init__(self, client: 'OpenrouterClient'):
            self.client = client
            self.messages = self.Messages(client)
            
        class Messages:
            """消息相关API"""
            
            def __init__(self, client: 'OpenrouterClient'):
                self.client = client
                
            def with_raw_response(self) -> 'OpenrouterClient.Beta.Messages':
                """方法链式调用"""
                return self
                
            async def create(
                self,
                max_tokens: int,
                messages: List[Dict[str, Any]],
                system: List[Dict[str, Any]],
            ) -> Tuple[OpenrouterResponse, Dict[str, Any]]:
                """
                创建聊天完成。
                
                Args:
                    max_tokens: 最大生成令牌数
                    messages: 聊天历史
                    system: 系统消息
                    
                Returns:
                    OpenrouterResponse和解析后的消息
                    
                Raises:
                    ValueError: 输入格式无效时抛出
                    RuntimeError: 连接或模型加载失败时抛出
                """
                # 验证输入参数
                if not messages or not isinstance(messages, list):
                    raise ValueError("messages必须是非空列表")
                
                for msg in messages:
                    if not isinstance(msg, dict) or "role" not in msg or "content" not in msg:
                        raise ValueError("每条消息必须是包含'role'和'content'键的字典")
                    if msg["role"] not in ["user", "assistant", "system", "tool"]:
                        raise ValueError(f"无效的消息角色: {msg['role']}")
                
                if not self.client.model:
                    raise ValueError("需要提供模型名称")
                                
                # 转换为OpenRouter格式
                openrouter_messages = [{
                    "role": "system",
                    "content": system
                }]
                openrouter_messages.extend(messages)
                
                # 准备请求数据
                request_data = {
                    "model": self.client.model,
                    "messages": openrouter_messages,
                    "stream": False,
                    "max_tokens": max_tokens,
                    "tools": self._get_tool_definitions()
                }

                try:
                    # 异步请求OpenRouter API
                    async_client = httpx.AsyncClient(
                        base_url=self.client.base_url,
                        timeout=self.client.config.api.REQUEST_TIMEOUT
                    )
                    try:
                        http_response = await async_client.post(
                            "/chat/completions",
                            headers={"Authorization": f"Bearer {self.client.api_key}"},
                            json=request_data
                        )
                        http_response.raise_for_status()
                    except httpx.TimeoutException as e:
                        raise APIError(f"OpenRouter请求超时: {e}")
                    except httpx.RequestError as e:
                        raise APIError(f"连接OpenRouter失败: {e}")
                    except httpx.HTTPStatusError as e:
                        raise APIError(f"OpenRouter API返回错误 {e.response.status_code}: {e.response.text}")
                
                    try:
                        # 解析OpenRouter响应
                        openrouter_response = http_response.json()
                        logger.debug(f"OpenRouter响应: {openrouter_response}")
                    except ValueError as e:
                        raise ValueError(f"无效的JSON响应: {e}")
                
                    if not isinstance(openrouter_response, dict):
                        raise ValueError(f"期望dict响应，得到 {type(openrouter_response)}")
                    
                    if "message" not in openrouter_response['choices'][0]:
                        raise ValueError(f"响应缺少'message'字段: {openrouter_response}")
                        
                except Exception as e:
                    if isinstance(e, (ValueError, APIError)):
                        raise
                    raise RuntimeError(f"从OpenRouter获取响应时发生意外错误: {e}")
                
                # 构建响应内容
                content = []
                if openrouter_response['choices'][0]["message"]["content"] is not None:
                    content.append({
                        "type": "text",
                        "text": openrouter_response['choices'][0]["message"]["content"]
                    })
                if 'tool_calls' in openrouter_response['choices'][0]['message']:
                    for item in openrouter_response['choices'][0]['message']['tool_calls']:
                        content.append({
                            "type": "tool_use", 
                            "name": item['function']['name'],
                            "input": json.loads(item['function']['arguments']),
                            'id': item['id']
                        })

                # 创建消息响应
                message = {
                    "id": "msg_" + http_response.headers.get("X-Request-ID", "unknown"),
                    "type": "message",
                    "role": "assistant",
                    "content": content,
                    "model": self.client.model,
                    "stop_reason": "tool_use" if openrouter_response['choices'][0]['finish_reason'] == "tool_calls" else "stop_sequence",
                    "stop_sequence": None,
                    "usage": {
                        "input_tokens": openrouter_response['usage']['prompt_tokens'],  
                        "output_tokens": openrouter_response['usage']['completion_tokens']
                    }
                }
                
                return OpenrouterResponse(message, http_response), openrouter_response['choices'][0]['message']

            def _get_tool_definitions(self) -> List[Dict[str, Any]]:
                """获取工具定义"""
                return [{
                    "type": "function",
                    "function": {
                        "name": "computer",
                        "description": "一个全面的工具，支持与计算机输入/输出设备交互，包括屏幕、键盘和鼠标。支持输入、点击、滚动和截图等操作。",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "action": {
                                    "type": "string",
                                    "enum": [
                                        "key",
                                        "type",
                                        "mouse_move",
                                        "left_click",
                                        "left_click_drag",
                                        "right_click",
                                        "middle_click",
                                        "double_click",
                                        "screenshot",
                                        "cursor_position",
                                        "scroll_up",
                                        "scroll_down",
                                    ],
                                    "description": "指定要执行的计算机交互动作类型。每个动作对应特定的输入/输出设备交互。"
                                },
                                "text": {
                                    "type": "string",
                                    "description": "键盘输入动作（'key'或'type'）需要此参数。Windows键使用'win'。"
                                },
                                "coordinate": {
                                    "type": "array",
                                    "prefixItems": [
                                        { "type": "number" },
                                        { "type": "number" },
                                    ],
                                    "items": { "type": "number" },
                                    "description": "鼠标相关动作需要此参数。指定屏幕上的x,y坐标用于鼠标移动、点击或拖动操作。"
                                },
                                "scroll_amount": {
                                    "type": "integer",
                                    "minimum": 1,
                                    "description": "scroll_up和scroll_down动作的可选参数。指定滚动量。必须是正整数。默认为400。滚动方向由动作类型决定。"
                                },
                                "repeat": {
                                    "type": "integer",
                                    "minimum": 1,
                                    "description": "所有动作的可选参数。指定重复执行动作的次数。默认为1。可用于重复按键、点击、滚动等任何动作。"
                                }
                            },
                            "required": ["action"]
                        }
                    }
                },{
                    "type": "function",
                    "function": {
                        "name": "bash",
                        "description": "一个Windows命令执行工具，维护持久的cmd.exe会话。支持自动超时控制的命令执行，对无输出命令具有截图能力。",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "command": {
                                    "type": "string",
                                    "description": "在持久的cmd.exe会话中执行的Windows命令。命令在120秒后超时。"
                                },
                                "restart": {
                                    "type": "boolean",
                                    "description": "可选参数，用于重启cmd.exe会话。当会话无响应或超时时使用。"
                                }
                            }
                        }
                    }
                },{
                    "type": "function",
                    "function": {
                        "name": "str_replace_editor",
                        "description": "一个强大的文件编辑工具，支持查看、创建、编辑和管理文件内容，具有历史记录跟踪功能。",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "command": {
                                    "type": "string",
                                    "enum": ["view", "create", "str_replace", "insert", "undo_edit"],
                                    "description": "要执行的编辑命令：view（显示文件内容），create（创建新文件），str_replace（替换文本），insert（在行插入），undo_edit（撤销最后更改）"
                                },
                                "path": {
                                    "type": "string",
                                    "description": "要操作的文件的绝对路径"
                                },
                                "file_text": {
                                    "type": "string",
                                    "description": "'create'命令需要此参数。要写入新文件的内容。"
                                },
                                "view_range": {
                                    "type": "array",
                                    "items": {"type": "integer"},
                                    "minItems": 2,
                                    "maxItems": 2,
                                    "description": "'view'命令的可选参数。指定要查看的起始和结束行号[start, end]。使用-1表示查看到最后一行。"
                                },
                                "old_str": {
                                    "type": "string",
                                    "description": "'str_replace'命令需要此参数。要替换的字符串。"
                                },
                                "new_str": {
                                    "type": "string",
                                    "description": "'str_replace'和'insert'命令需要此参数。要插入或替换的新字符串。"
                                },
                                "insert_line": {
                                    "type": "integer",
                                    "description": "'insert'命令需要此参数。要插入新内容的行号。"
                                }
                            },
                            "required": ["command", "path"]
                        }
                    }
                }]
