"""OpenRouter API客户端模块"""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .config import Config
from .tools.exceptions import APIError
from .tools.base import ToolFactory

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
                self.logger = logging.getLogger(self.__class__.__name__)
                
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
                        self.logger.debug(f"OpenRouter响应: {openrouter_response}")
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
                
                def _build_content(choice: Dict[str, Any]) -> List[Dict[str, Any]]:
                    """构建响应内容列表"""
                    content = []
                    
                    # 添加文本内容
                    message = choice["message"]
                    if message.get("content"):
                        content.append({
                            "type": "text",
                                "text": message["content"]
                        })
                    
                    # 添加工具调用内容
                    if tool_calls := message.get("tool_calls"):
                        content.extend([{
                            "type": "tool_use", 
                            "name": call["function"]["name"],
                            "input": json.loads(call["function"]["arguments"]),
                            "id": call["id"]
                        } for call in tool_calls])

                    return content

                def _create_message(response: Dict[str, Any], choice: Dict[str, Any], request_id: str) -> Dict[str, Any]:
                    """创建标准化的消息响应"""
                    return {
                        "id": f"msg_{request_id}",
                        "type": "message",
                        "role": "assistant",
                        "content": _build_content(choice),
                        "model": self.client.model,
                        "stop_reason": "tool_use" if choice["finish_reason"] == "tool_calls" else "stop_sequence",
                        "stop_sequence": None,
                        "usage": {
                                "input_tokens": response["usage"]["prompt_tokens"],
                                "output_tokens": response["usage"]["completion_tokens"]
                        }
                    }
                
                # 获取首个选择结果
                choice = openrouter_response["choices"][0]
                request_id = http_response.headers.get("X-Request-ID", "unknown")
                
                # 构建最终响应
                message = _create_message(openrouter_response, choice, request_id)
                return OpenrouterResponse(message, http_response), choice["message"]

            def _get_tool_definitions(self) -> List[Dict[str, Any]]:
                """获取工具定义"""
                tool_definitions = []
                for tool_name in ToolFactory._tools:
                    tool = ToolFactory.create(tool_name)
                    # 从工具类中获取参数定义
                    if hasattr(tool, "parameters_schema"):
                        tool_def = {
                            "type": "function",
                            "function": {
                                "name": tool.name,
                                "description": tool.__class__.__doc__.strip(),
                                "parameters": tool.parameters_schema
                            }
                        }
                        tool_definitions.append(tool_def)
                return tool_definitions
