"""
Entrypoint for streamlit, see https://docs.streamlit.io/
"""

import asyncio
import base64
import os
import subprocess
import traceback
from datetime import datetime, timedelta
from enum import StrEnum
from functools import partial
from pathlib import Path
from typing import cast

import httpx
import streamlit as st
from anthropic import RateLimitError
from anthropic.types.beta import (
    BetaContentBlockParam,
    BetaTextBlockParam,
)
from streamlit.delta_generator import DeltaGenerator

from computer_use_demo.loop import (
    APIProvider,
    sampling_loop,
)
from computer_use_demo.tools import ToolResult

CONFIG_DIR = Path(os.path.expanduser("~/.anthropic"))
API_KEY_FILE = CONFIG_DIR / "api_key"
STREAMLIT_STYLE = """
<style>
    /* Hide chat input while agent loop is running */
    .stApp[data-teststate=running] .stChatInput textarea,
    .stApp[data-test-script-state=running] .stChatInput textarea {
        display: none;
    }
     /* Hide the streamlit deploy button */
    .stDeployButton {
        visibility: hidden;
    }
</style>
"""

class Sender(StrEnum):
    USER = "user"
    BOT = "assistant"
    TOOL = "tool"


def setup_state():
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "api_key" not in st.session_state:
        st.session_state.api_key = os.getenv("OPENROUTER_API_KEY", "")
    if "base_url" not in st.session_state:
        st.session_state.base_url = os.getenv("OPENROUTER_BASE_URL", "")
    if "model" not in st.session_state:
        st.session_state.model = os.getenv("OPENROUTER_MODEL", "")
    if "provider" not in st.session_state:
        st.session_state.provider = APIProvider.OPENROUTER.value
    if "provider_radio" not in st.session_state:
        st.session_state.provider_radio = st.session_state.provider
    if "auth_validated" not in st.session_state:
        st.session_state.auth_validated = False
    if "responses" not in st.session_state:
        st.session_state.responses = {}
    if "tools" not in st.session_state:
        st.session_state.tools = {}
    if "only_n_most_recent_images" not in st.session_state:
        st.session_state.only_n_most_recent_images = 2
    if "custom_system_prompt" not in st.session_state:
        st.session_state.custom_system_prompt = "Speak in Chinese."
    if "hide_images" not in st.session_state:
        st.session_state.hide_images = False


async def main():
    """Render loop for streamlit"""
    setup_state()

    st.markdown(STREAMLIT_STYLE, unsafe_allow_html=True)

    st.title("让AI控制你的电脑")

    with st.sidebar:
        st.text_area(
            "模型名称",
            key="model",
            help="选择OpenRouter的模型",
        )
        st.text_area(
            "自定义系统提示",
            key="custom_system_prompt",
            help="添加至系统提示的额外指令",
        )
    if not st.session_state.auth_validated:
        st.session_state.auth_validated = True

    chat, http_logs = st.tabs(["对话", "HTTP日志"])
    new_message = st.chat_input(
        "给AI发送消息以控制你的电脑..."
    )

    with chat:
        # render past chats
        messages = st.session_state.messages
        for i, message in enumerate(messages):
            if isinstance(message, dict):
                role = message.get("role", "")
                content = message.get("content", "")
                
                # 如果当前消息是role="user"且前一条是role="tool"，则跳过显示
                if (role == "user" and 
                    i > 0 and 
                    isinstance(messages[i-1], dict) and 
                    messages[i-1].get("role") == "tool"):
                    continue
                
                if role == "tool":
                    # 处理工具执行结果
                    tool_call_id = message.get("tool_call_id", "")
                    if tool_call_id in st.session_state.tools:
                        _render_message(Sender.TOOL, st.session_state.tools[tool_call_id])
                elif isinstance(content, str):
                    _render_message(role, content)
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict):
                            if block.get("type") == "tool_result":
                                tool_id = block.get("tool_use_id", "")
                                if tool_id in st.session_state.tools:
                                    _render_message(
                                        Sender.TOOL, 
                                        st.session_state.tools[tool_id]
                                    )
                            elif block.get("type") == "text":
                                _render_message(role, block.get("text", ""))
                            elif block.get("type") == "tool_use":
                                _render_message(
                                    role,
                                    f'使用工具: {block.get("name", "")}\n输入: {block.get("input", "")}'
                                )

        # render past http exchanges
        for identity, (request, response) in st.session_state.responses.items():
            _render_api_response(request, response, identity, http_logs)

        # handle new message
        if new_message:
            st.session_state.messages.append(
                {
                    "role": Sender.USER,
                    "content": [BetaTextBlockParam(type="text", text=new_message)],
                }
            )
            _render_message(Sender.USER, new_message)

        try:
            most_recent_message = st.session_state["messages"][-1]
        except IndexError:
            return

        if most_recent_message["role"] is not Sender.USER:
            # we don't have a user message to respond to, exit early
            return

        with st.spinner("正在运行..."):
            # run the agent sampling loop with the newest message
            st.session_state.messages = await sampling_loop(
                system_prompt_suffix=st.session_state.custom_system_prompt,
                provider=st.session_state.provider,
                messages=st.session_state.messages,
                output_callback=partial(_render_message, Sender.BOT),
                tool_output_callback=partial(
                    _tool_output_callback, tool_state=st.session_state.tools
                ),
                api_response_callback=partial(
                    _api_response_callback,
                    tab=http_logs,
                    response_state=st.session_state.responses,
                ),
                api_key=st.session_state.api_key,
                base_url=st.session_state.base_url,
                model=st.session_state.model,
                only_n_most_recent_images=st.session_state.only_n_most_recent_images,
            )


def load_from_storage(filename: str) -> str | None:
    """Load data from a file in the storage directory."""
    try:
        file_path = CONFIG_DIR / filename
        if file_path.exists():
            data = file_path.read_text().strip()
            if data:
                return data
    except Exception as e:
        st.write(f"Debug: Error loading {filename}: {e}")
    return None


def save_to_storage(filename: str, data: str) -> None:
    """Save data to a file in the storage directory."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        file_path = CONFIG_DIR / filename
        file_path.write_text(data)
        # Ensure only user can read/write the file
        file_path.chmod(0o600)
    except Exception as e:
        st.write(f"Debug: Error saving {filename}: {e}")


def _api_response_callback(
    request: httpx.Request,
    response: httpx.Response | object | None,
    error: Exception | None,
    tab: DeltaGenerator,
    response_state: dict[str, tuple[httpx.Request, httpx.Response | object | None]],
):
    """
    Handle an API response by storing it to state and rendering it.
    """
    response_id = datetime.now().isoformat()
    response_state[response_id] = (request, response)
    if error:
        _render_error(error)
    _render_api_response(request, response, response_id, tab)


def _tool_output_callback(
    tool_output: ToolResult, tool_id: str, tool_state: dict[str, ToolResult]
):
    """Handle a tool output by storing it to state and rendering it."""
    tool_state[tool_id] = tool_output
    _render_message(Sender.TOOL, tool_output)


def _render_api_response(
    request: httpx.Request,
    response: httpx.Response | object | None,
    response_id: str,
    tab: DeltaGenerator,
):
    """Render an API response to a streamlit tab"""
    with tab:
        with st.expander(f"Request/Response ({response_id})"):
            newline = "\n\n"
            st.markdown(
                f"`{request.method} {request.url}`{newline}{newline.join(f'`{k}: {v}`' for k, v in request.headers.items())}"
            )
            st.json(request.read().decode())
            st.markdown("---")
            if isinstance(response, httpx.Response):
                st.markdown(
                    f"`{response.status_code}`{newline}{newline.join(f'`{k}: {v}`' for k, v in response.headers.items())}"
                )
                st.json(response.text)
            else:
                st.write(response)


def _render_error(error: Exception):
    if isinstance(error, RateLimitError):
        body = "You have been rate limited."
        if retry_after := error.response.headers.get("retry-after"):
            body += f" **Retry after {str(timedelta(seconds=int(retry_after)))} (HH:MM:SS).** See our API [documentation](https://docs.anthropic.com/en/api/rate-limits) for more details."
        body += f"\n\n{error.message}"
    else:
        body = str(error)
        body += "\n\n**Traceback:**"
        lines = "\n".join(traceback.format_exception(error))
        body += f"\n\n```{lines}```"
    save_to_storage(f"error_{datetime.now().timestamp()}.md", body)
    st.error(f"**{error.__class__.__name__}**\n\n{body}", icon=":material/error:")


def _render_message(
    sender: Sender,
    message: str | BetaContentBlockParam | ToolResult | dict,
):
    """Convert input from the user or output from the agent to a streamlit message."""
    if not message:
        return
        
    with st.chat_message(sender):
        if isinstance(message, ToolResult):
            if message.output:
                if message.__class__.__name__ == "CLIResult":
                    st.code(message.output)
                else:
                    st.markdown(message.output)
            if message.error:
                st.error(message.error)
            if message.base64_image and not st.session_state.hide_images:
                st.image(base64.b64decode(message.base64_image))
        elif isinstance(message, dict):
            if message.get("type") == "text":
                st.write(message.get("text", ""))
            elif message.get("type") == "tool_use":
                st.code(f'使用工具: {message.get("name", "")}\n输入: {message.get("input", "")}')
        else:
            st.markdown(str(message))


if __name__ == "__main__":
    asyncio.run(main())
