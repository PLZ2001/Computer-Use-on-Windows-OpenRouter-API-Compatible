"""
Agentic sampling loop that calls the Anthropic API and local implementation of anthropic-defined computer use tools.
"""

import json
import platform
from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from typing import Any, cast

import httpx
from anthropic import (
    Anthropic,
    AnthropicBedrock,
    AnthropicVertex,
    APIError,
    APIResponseValidationError,
    APIStatusError,
)
from anthropic.types.beta import (
    BetaCacheControlEphemeralParam,
    BetaContentBlockParam,
    BetaImageBlockParam,
    BetaMessage,
    BetaMessageParam,
    BetaTextBlock,
    BetaTextBlockParam,
    BetaToolResultBlockParam,
    BetaToolUseBlockParam,
)

from .tools import ComputerTool, CommandTool, ToolCollection, ToolResult

COMPUTER_USE_BETA_FLAG = "computer-use-2024-10-22"
PROMPT_CACHING_BETA_FLAG = "prompt-caching-2024-07-31"


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
  - Batch operations for efficiency
  - Take screenshots when visual context needed
  - Consider command execution delays

* Display & Coordinates:
  - Native monitor resolution preserved
  - Accurate DPI scaling and coordinate mapping
  - Windows taskbar position handled
  - Full screen content accessibility via scrolling
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
    messages: list[BetaMessageParam],
    output_callback: Callable[[BetaContentBlockParam], None],
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
    )
    system = BetaTextBlockParam(
        type="text",
        text=f"{SYSTEM_PROMPT}{' ' + system_prompt_suffix if system_prompt_suffix else ''}",
    )

    while True:
        enable_prompt_caching = False
        betas = [COMPUTER_USE_BETA_FLAG]
        if provider == APIProvider.OPENROUTER:
            from .openrouter_client import OpenrouterClient
            client = await (OpenrouterClient(base_url=base_url, api_key=api_key, model=model).initialize())  # Initialize asynchronously
            enable_prompt_caching = False

        if enable_prompt_caching:
            betas.append(PROMPT_CACHING_BETA_FLAG)
            _inject_prompt_caching(messages)
            # Is it ever worth it to bust the cache with prompt caching?
            system["cache_control"] = {"type": "ephemeral"}

        if only_n_most_recent_images:
            messages = _maybe_filter_to_n_most_recent_images(
                messages,
                only_n_most_recent_images,
            )

        # Call the API
        # we use raw_response to provide debug information to streamlit. Your
        # implementation may be able call the SDK directly with:
        # `response = client.messages.create(...)` instead.
        try:
            raw_response, message = await client.beta.messages.create(
                max_tokens=max_tokens,
                messages=messages,
                system=[system],
            )
        except (APIStatusError, APIResponseValidationError) as e:
            api_response_callback(e.request, e.response, e)
            return messages
        except APIError as e:
            api_response_callback(e.request, e.body, e)
            return messages

        api_response_callback(
            raw_response.http_response.request, raw_response.http_response, None
        )
        
        response = raw_response.parse()
        response_params = _response_to_params(response)
        messages.append(message)

        tool_result_content: list[BetaToolResultBlockParam] = []
        for content_block in response_params:
            output_callback(content_block)
            if content_block["type"] == "tool_use":
                result = await tool_collection.run(
                    name=content_block["name"],
                    tool_input=cast(dict[str, Any], content_block["input"]),
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
    messages: list[BetaMessageParam],
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
    response: BetaMessage,
) -> list[BetaTextBlockParam | BetaToolUseBlockParam]:
    res: list[BetaTextBlockParam | BetaToolUseBlockParam] = []
    for block in response.content:
        if isinstance(block, BetaTextBlock):
            res.append({"type": "text", "text": block.text})
        else:
            res.append(cast(BetaToolUseBlockParam, block.model_dump()))
    return res


def _inject_prompt_caching(
    messages: list[BetaMessageParam],
):
    """
    Set cache breakpoints for the 3 most recent turns
    one cache breakpoint is left for tools/system prompt, to be shared across sessions
    """

    breakpoints_remaining = 3
    for message in reversed(messages):
        if message["role"] == "user" and isinstance(
            content := message["content"], list
        ):
            if breakpoints_remaining:
                breakpoints_remaining -= 1
                content[-1]["cache_control"] = BetaCacheControlEphemeralParam(
                    {"type": "ephemeral"}
                )
            else:
                content[-1].pop("cache_control", None)
                # we'll only every have one extra turn per loop
                break

def _make_api_tool_result(
    result: ToolResult, tool_name: str, tool_use_id: str
) -> BetaToolResultBlockParam:
    """Convert an agent ToolResult to an API ToolResultBlockParam."""
    tool_result_content: list[BetaTextBlockParam | BetaImageBlockParam] | str = []
    is_error = False
    if result.error:
        is_error = True
        tool_result_content = _maybe_prepend_system_tool_result(result, result.error)
    else:
        if result.output:
            tool_result_content.append(
                {
                    "type": "text",
                    "text": _maybe_prepend_system_tool_result(result, result.output),
                }
            )
        if result.base64_image:
            tool_result_content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{result.base64_image}",
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


def _maybe_prepend_system_tool_result(result: ToolResult, result_text: str):
    if result.system:
        result_text = f"<system>{result.system}</system>\n{result_text}"
    return result_text
