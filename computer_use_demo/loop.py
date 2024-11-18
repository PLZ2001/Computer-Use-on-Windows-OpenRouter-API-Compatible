"""
Agentic sampling loop that calls the OpenRouter API and local implementation of computer use tools.
"""

import json
import platform
from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from typing import Any, TypedDict, List, Dict, Optional

import httpx

from .tools import ComputerTool, CommandTool, EditTool, ToolCollection, ToolResult

class APIProvider(StrEnum):
    OPENROUTER = "openrouter"

SYSTEM_PROMPT = f"""<SYSTEM_CAPABILITIES>
* Environment:
  - OS: Windows {platform.machine()}
  - Internet: Available
  - Date: {datetime.today().strftime('%A, %B %d, %Y')}

* Available Tools:
  - 'computer': GUI interaction (mouse/keyboard control, screenshots)
  - 'bash': Command line operations (preferred for system tasks)

* Tool Usage Best Practices:
  - Use 'bash' over 'computer' when possible
  - Where possible/feasible, try to call multiple functions/tools at a time for efficiency
  - Take screenshots whenever context is unclear
  - Consider functions/tools execution delays
  - Examine screenshots carefully to validate results of functions/tools execution
  - Any functions/tools execution should be additive rather than overwriting existing content
  - Where possible/feasible, try to access full screen content via scrolling up or down

* Display & Coordinates:
  - Native monitor resolution preserved
  - Accurate DPI scaling and coordinate mapping
  - Windows taskbar position handled
  - Screenshots at native resolution (compressed if needed)
  - Zooming available for full page visibility

* Important Notes:
  - All screen interactions maintain 1:1 pixel accuracy
  - System handles Windows-specific UI elements automatically
  - Coordinate system preserves exact screen positions
  - DPI scaling properly managed for precise interactions
</SYSTEM_CAPABILITIES>"""

async def sampling_loop(
    *,
    provider: APIProvider,
    system_prompt_suffix: str,
    messages: List[Dict[str, Any]],
    output_callback: Callable[[Dict[str, Any]], None],
    tool_output_callback: Callable[[ToolResult, str], None],
    api_response_callback: Callable[
        [httpx.Request, httpx.Response | object | None, Exception | None], None
    ],
    api_key: str,
    base_url: str,
    model: str,
    only_n_most_recent_images: int | None = None,
    max_tokens: int = 4096,
):
    """
    Agentic sampling loop for the assistant/tool interaction of computer use.
    """
    tool_collection = ToolCollection(
        ComputerTool(),
        CommandTool(),
        EditTool(),
    )
    system = {
        "type": "text",
        "text": f"{SYSTEM_PROMPT}{' ' + system_prompt_suffix if system_prompt_suffix else ''}",
    }

    while True:
        if provider == APIProvider.OPENROUTER:
            from .openrouter_client import OpenrouterClient
            client = await (OpenrouterClient(base_url=base_url, api_key=api_key, model=model).initialize())  # Initialize asynchronously

        if only_n_most_recent_images:
            messages = _maybe_filter_to_n_most_recent_images(
                messages,
                only_n_most_recent_images,
            )

        # Call the API
        try:
            raw_response, message = await client.beta.messages.create(
                max_tokens=max_tokens,
                messages=messages,
                system=[system],
            )
        except Exception as e:
            api_response_callback(e.request, getattr(e, 'response', None), e)
            return messages

        api_response_callback(
            raw_response.http_response.request, raw_response.http_response, None
        )
        
        response = raw_response.parse()
        response_params = _response_to_params(response)
        messages.append(message)

        tool_result_content: List[Dict[str, Any]] = []
        for content_block in response_params:
            output_callback(content_block)
            if content_block["type"] == "tool_use":
                result = await tool_collection.run(
                    name=content_block["name"],
                    tool_input=content_block["input"],
                )
                tool_result_content.append(
                    _make_api_tool_result(result, content_block["name"], content_block["id"])
                )
                tool_output_callback(result, content_block["id"])

        if not tool_result_content:
            return messages
        
        for item in tool_result_content:
            messages.append({"role": "tool", "name": item["name"], "tool_call_id": item["tool_use_id"], "content": json.dumps([item["tool_result"]])})
        messages.append({"role": "user", "content": tool_result_content[-1]["content"]})


def _maybe_filter_to_n_most_recent_images(
    messages: List[Dict[str, Any]],
    images_to_keep: int,
):
    """
    Filters the messages to keep only the most recent images while preserving other content.
    Only keeps the specified number of most recent image blocks.
    
    Args:
        messages: List of message parameters containing various content blocks
        images_to_keep: Number of most recent images to retain
        
    Returns:
        List of filtered messages with only the N most recent images
    """
    if images_to_keep is None or images_to_keep <= 0:
        return messages
        
    # Track number of images we've seen from newest to oldest  
    images_seen = 0
    
    # Process messages in reverse order to keep most recent images
    new_messages = []
    for message in reversed(messages):
        new_content = []        
        if isinstance(message.get("content"), list):
            for content in message["content"]:
                # If this is an image block
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
    res: List[Dict[str, Any]] = []
    for block in response.get("content", []):
        if block.get("type") == "text":
            res.append({"type": "text", "text": block.get("text", "")})
        else:
            res.append(block)
    return res


def _make_api_tool_result(
    result: ToolResult, tool_name: str, tool_use_id: str
) -> Dict[str, Any]:
    """Convert an agent ToolResult to an API tool result format."""
    tool_result_content: List[Dict[str, Any]] | str = []
    is_error = False
    if result.error:
        is_error = True
        tool_result_content = result
    else:
        if result.output:
            tool_result_content.append(
                {
                    "type": "text",
                    "text": "TOOL RESULT FOLLOWING",
                }
            )
            tool_result_content.append(
                {
                    "type": "text",
                    "text": result.output,
                }
            )
        if result.base64_image:
            tool_result_content.append(
                {
                    "type": "text",
                    "text": "TOOL RESULT FOLLOWING",
                }
            )
            tool_result_content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{result.base64_image}",
                    },
                }
            )
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
