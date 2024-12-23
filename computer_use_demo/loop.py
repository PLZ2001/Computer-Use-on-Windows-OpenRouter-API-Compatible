"""代理采样循环模块"""

import json
import platform
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Dict, List

import httpx

from .config import Config
from .tools import ComputerTool, CommandTool, EditTool, BrowserTool, ToolCollection, ToolResult

class APIProvider(StrEnum):
    """API提供者类型"""
    OPENROUTER = "openrouter"

@dataclass
class APIConfig:
    """API配置"""
    provider: APIProvider
    api_key: str
    base_url: str
    model: str

@dataclass
class CallbackConfig:
    """回调函数配置"""
    output: Callable[[Dict[str, Any]], None]
    tool_output: Callable[[ToolResult, str], None]
    api_response: Callable[[httpx.Response | object | None, Exception | None], None]

# 系统提示信息
SYSTEM_PROMPT = f"""<SYSTEM_CAPABILITIES>
* 环境:
  - 操作系统: Windows {platform.machine()}
  - 网络: 可用
  - 日期: {datetime.today().strftime('%A, %B %d, %Y')}

* 工具使用最佳实践:
  - 尽可能一次调用多个函数/工具以提高效率
  - 考虑函数/工具执行延迟
  - 函数/工具执行应该是增量的而不是覆盖现有内容
  - 有必要时通过上下滚动访问完整屏幕内容
  - 有必要时截图以仔细评估您是否取得了正确的结果
  - 明确显示您的想法（我已经评估了步骤X...）
  - 如果不正确请重试
  - 当您确认正确执行步骤时才能继续执行下一个步骤
</SYSTEM_CAPABILITIES>"""

async def sampling_loop(
    *,
    api_config: APIConfig,
    callback_config: CallbackConfig,
    messages: List[Dict[str, Any]],
    system_prompt_suffix: str = "",
) -> List[Dict[str, Any]]:
    """
    代理采样循环，用于助手/工具交互。
    
    Args:
        api_config: API配置
        callback_config: 回调函数配置
        messages: 消息历史
        system_prompt_suffix: 系统提示后缀
        
    Returns:
        更新后的消息历史
    """
    config = Config.get_instance()
    
    # 初始化工具集合
    tool_collection = ToolCollection(
        ComputerTool(),
        CommandTool(),
        EditTool(),
        BrowserTool(),
    )

    # 构建系统消息
    system = {
        "type": "text",
        "text": f"{SYSTEM_PROMPT}{' ' + system_prompt_suffix if system_prompt_suffix else ''}",
    }

    while True:
        # 根据提供者选择客户端
        if api_config.provider == APIProvider.OPENROUTER:
            from .openrouter_client import OpenrouterClient
            client = await OpenrouterClient(
                base_url=api_config.base_url,
                api_key=api_config.api_key,
                model=api_config.model
            ).initialize()

        # 从配置获取并过滤最近图片
        if config.computer.ONLY_N_MOST_RECENT_IMAGES:
            messages = _filter_recent_images(
                messages,
                config.computer.ONLY_N_MOST_RECENT_IMAGES,
            )

        try:
            # 调用API
            raw_response, message = await client.beta.messages.create(
                max_tokens=config.api.MAX_TOKENS,
                messages=messages,
                system=[system],
            )
        except Exception as e:
            callback_config.api_response(getattr(e, 'response', None), e)
            return messages

        # 处理API响应
        callback_config.api_response(
            raw_response.http_response,
            None
        )
        
        response = raw_response.parse()
        response_params = _response_to_params(response)
        messages.append(message)

        # 处理工具调用
        tool_results = []
        for content_block in response_params:
            callback_config.output(content_block)
            if content_block["type"] == "tool_use":
                result = await tool_collection.run(
                    name=content_block["name"],
                    tool_input=content_block["input"],
                )
                tool_result = _make_tool_result(
                    result,
                    content_block["name"],
                    content_block["id"],
                    content_block["input"],
                )
                tool_results.append(tool_result)
                callback_config.tool_output(result, content_block["id"])

        if not tool_results:
            return messages
        
        # 更新消息历史
        for item in tool_results:
            messages.append({
                "role": "tool",
                "name": item["name"],
                "tool_call_id": item["tool_use_id"],
                "content": json.dumps([item["tool_result"]])
            })
        messages.append({
            "role": "user",
            "content": tool_results[-1]["content"]
        })


def _filter_recent_images(
    messages: List[Dict[str, Any]],
    images_to_keep: int,
) -> List[Dict[str, Any]]:
    """
    过滤消息以仅保留最近的图片。
    
    Args:
        messages: 消息列表
        images_to_keep: 要保留的图片数量
        
    Returns:
        过滤后的消息列表
    """
    if images_to_keep <= 0:
        return messages
        
    # 从最新到最旧追踪图片数量
    images_seen = 0
    
    # 反向处理消息以保留最近的图片
    new_messages = []
    for message in reversed(messages):
        new_content = []
        if isinstance(message.get("content"), list):
            for content in message["content"]:
                if isinstance(content, dict) and content.get("type") == "image_url":
                    if images_seen < images_to_keep:
                        images_seen += 1
                        new_content.append(content)
                else:
                    new_content.append(content)
            if new_content:
                message["content"] = new_content
                new_messages.append(message)
        else:
            new_messages.append(message)
    
    return list(reversed(new_messages))


def _response_to_params(
    response: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    将API响应转换为参数格式。
    
    Args:
        response: API响应
        
    Returns:
        参数列表
    """
    result = []
    for block in response.get("content", []):
        if block.get("type") == "text":
            result.append({
                "type": "text",
                "text": block.get("text", "")
            })
        else:
            result.append(block)
    return result


def _make_tool_result(
    result: ToolResult,
    tool_name: str,
    tool_use_id: str,
    input: Dict[str, Any]
) -> Dict[str, Any]:
    """
    将工具结果转换为API格式。
    
    Args:
        result: 工具执行结果
        tool_name: 工具名称
        tool_use_id: 工具使用ID
        
    Returns:
        API格式的工具结果
    """
    tool_result_content: List[Dict[str, Any]] = []
    is_error = False

    if result.error:
        is_error = True
        tool_result_content.extend([
            {
                "type": "text",
                "text": f"f'使用工具: {tool_name}\n输入: {input}'",
            },
            {
                "type": "text",
                "text": f"{tool_name}工具执行出错",
            },
            {
                "type": "text",
                "text": str(result.error),
            }
        ])
    else:
        if result.output:
            tool_result_content.extend([
                {
                    "type": "text",
                    "text": f"f'使用工具: {tool_name}\n输入: {input}'",
                },
                {
                    "type": "text",
                    "text": f"{tool_name}工具执行结果如下",
                },
                {
                    "type": "text",
                    "text": result.output,
                }
            ])
        if result.base64_image:
            tool_result_content.extend([
                {
                    "type": "text",
                    "text": f"f'使用工具: {tool_name}\n输入: {input}'",
                },
                {
                    "type": "text",
                    "text": f"{tool_name}工具执行结果如下",
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{result.base64_image}",
                    },
                }
            ])

    return {
        "tool_result": {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "is_error": is_error,
        },
        "content": tool_result_content,
        "name": tool_name,
        "tool_use_id": tool_use_id,
    }
