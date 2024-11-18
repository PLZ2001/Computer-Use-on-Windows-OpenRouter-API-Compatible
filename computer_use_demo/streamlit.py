"""Streamlit Web界面模块"""

import base64
import json
import logging
import os
from enum import Enum
from typing import Any, Dict, List, Optional, Union

import streamlit as st
from dotenv import load_dotenv
import anyio

from .config import Config
from .loop import APIProvider, sampling_loop, APIConfig, CallbackConfig
from .tools import ToolResult

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 加载环境变量
load_dotenv()

class Sender(str, Enum):
    """消息发送者类型"""
    USER = "user"
    BOT = "assistant"
    TOOL = "tool"

class StreamlitUI:
    """Streamlit用户界面管理器"""

    def __init__(self):
        """初始化UI管理器"""
        self.config = Config.get_instance()
        self.setup_page()
        self.initialize_session_state()

    def setup_page(self):
        """设置页面配置"""
        st.set_page_config(
            page_title="计算机控制助手",
            page_icon="🖥️",
            layout="wide",
            initial_sidebar_state="expanded"
        )

    def initialize_session_state(self):
        """初始化会话状态"""
        if "messages" not in st.session_state:
            st.session_state.messages = []
        if "tools" not in st.session_state:
            st.session_state.tools = {}
        if "api_key" not in st.session_state:
            st.session_state.api_key = os.getenv("OPENROUTER_API_KEY", "")
        if "base_url" not in st.session_state:
            st.session_state.base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        if "model" not in st.session_state:
            st.session_state.model = os.getenv("OPENROUTER_MODEL", "anthropic/claude-2")
        if "hide_images" not in st.session_state:
            st.session_state.hide_images = False

    def render_sidebar(self):
        """渲染侧边栏"""
        with st.sidebar:
            st.title("⚙️ 设置")
            
            # API配置
            st.header("API配置")
            st.session_state.api_key = st.text_input(
                "API密钥",
                value=st.session_state.api_key,
                type="password"
            )
            st.session_state.base_url = st.text_input(
                "API基础URL",
                value=st.session_state.base_url
            )
            st.session_state.model = st.text_input(
                "模型名称",
                value=st.session_state.model
            )
            
            # Computer工具配置
            st.header("🖥️ Computer工具配置")
            typing_group_size = st.number_input(
                "打字分组大小",
                min_value=1,
                max_value=200,
                value=self.config.computer.TYPING_GROUP_SIZE,
                step=1,
                help="每组输入的字符数量"
            )
            screenshot_delay = st.number_input(
                "截图延迟(秒)",
                min_value=0.1,
                max_value=5.0,
                value=self.config.computer.SCREENSHOT_DELAY,
                step=0.1,
                help="执行截图前的等待时间"
            )
            max_image_size = st.number_input(
                "最大图片大小(MB)",
                min_value=0.1,
                max_value=10.0,
                value=self.config.computer.MAX_IMAGE_SIZE / (1024 * 1024),
                step=0.1,
                help="截图的最大文件大小"
            )
            only_n_most_recent_images = st.number_input(
                "保留最近图片数量",
                min_value=1,
                max_value=20,
                value=self.config.computer.ONLY_N_MOST_RECENT_IMAGES,
                step=1,
                help="只保留最近的N张图片"
            )
            st.session_state.hide_images = st.checkbox(
                "隐藏图片",
                value=st.session_state.hide_images,
                help="是否在界面上隐藏截图"
            )
            
            # Edit工具配置
            st.header("📝 Edit工具配置")
            snippet_lines = st.number_input(
                "编辑上下文行数",
                min_value=1,
                max_value=20,
                value=self.config.edit.SNIPPET_LINES,
                step=1,
                help="显示编辑操作前后的上下文行数"
            )
            
            # 路径配置
            st.header("📁 路径配置")
            output_dir = st.text_input(
                "输出目录",
                value=str(self.config.path.OUTPUT_DIR),
                help="工具输出文件的保存目录"
            )
            
            # API配置
            st.header("🌐 API配置")
            max_tokens = st.number_input(
                "最大Token数",
                min_value=1,
                max_value=8192,
                value=self.config.api.MAX_TOKENS,
                step=1,
                help="API请求的最大token数量"
            )
            request_timeout = st.number_input(
                "请求超时(秒)",
                min_value=1.0,
                max_value=300.0,
                value=self.config.api.REQUEST_TIMEOUT,
                step=1.0,
                help="API请求的超时时间"
            )
            
            # 更新配置
            self.config.computer.TYPING_GROUP_SIZE = typing_group_size
            self.config.computer.SCREENSHOT_DELAY = screenshot_delay
            self.config.computer.MAX_IMAGE_SIZE = int(max_image_size * 1024 * 1024)
            self.config.computer.ONLY_N_MOST_RECENT_IMAGES = only_n_most_recent_images
            self.config.edit.SNIPPET_LINES = snippet_lines
            self.config.path.OUTPUT_DIR = output_dir
            self.config.api.MAX_TOKENS = max_tokens
            self.config.api.REQUEST_TIMEOUT = request_timeout
            
            # 清除历史
            if st.button("🗑️ 清除聊天历史"):
                st.session_state.messages = []
                st.session_state.tools = {}
                st.rerun()

    def _render_message(
        self,
        sender: Sender,
        message: Union[str, Dict[str, Any], ToolResult]
    ):
        """渲染单条消息"""
        if not message:
            return
            
        with st.chat_message(sender):
            if isinstance(message, ToolResult):
                if message.output:
                    st.code(message.output)
                if message.error:
                    st.error(message.error)
                if message.base64_image and not st.session_state.hide_images:
                    st.image(base64.b64decode(message.base64_image))
            elif isinstance(message, dict):
                if message.get("type") == "text":
                    st.markdown(message.get("text", ""))
                elif message.get("type") == "tool_use":
                    st.code(f'使用工具: {message.get("name", "")}\n输入: {message.get("input", "")}')
                elif message.get("type") == "error":
                    st.error(message.get("text", ""))
            else:
                st.markdown(str(message))

    def render_messages(self):
        """渲染消息历史"""
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
                        self._render_message(
                            Sender.BOT,
                            {
                                "type": "tool_use",
                                "name": message.get("name", ""),
                                "input": next((call for call in messages[i-1]["tool_calls"] if call["id"] == tool_call_id), {}).get("function", {}).get("arguments", ""),
                            }
                        )
                        self._render_message(Sender.TOOL, st.session_state.tools[tool_call_id])
                elif isinstance(content, str):
                    self._render_message(role, content)
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict):
                            if block.get("type") == "tool_result":
                                tool_id = block.get("tool_use_id", "")
                                if tool_id in st.session_state.tools:
                                    self._render_message(
                                        Sender.TOOL, 
                                        st.session_state.tools[tool_id]
                                    )
                            elif block.get("type") == "text":
                                self._render_message(role, block.get("text", ""))

    async def handle_user_input(self):
        """处理用户输入"""
        if prompt := st.chat_input("输入你的指令..."):
            st.chat_message("user").write(prompt)
            st.session_state.messages.append({
                "role": "user",
                "content": prompt
            })
            
            await self.process_messages()

    async def _run_sampling_loop(self):
        """运行采样循环"""
        def output_callback(content: Dict[str, Any]):
            """输出回调"""
            self._render_message(Sender.BOT, content)

        def tool_output_callback(result: ToolResult, tool_id: str):
            """工具输出回调"""
            # 缓存工具结果
            st.session_state.tools[tool_id] = result
            
            if result.error:
                self._render_message(
                    Sender.TOOL,
                    {
                        "type": "error",
                        "text": f"工具执行错误 (ID: {tool_id}): {result.error}"
                    }
                )
            else:
                if result.output or result.base64_image:
                    self._render_message(
                        Sender.TOOL,
                        result
                    )

        def api_response_callback(response: Optional[Any], error: Optional[Exception]):
            """API响应回调"""
            if error:
                self._render_message(
                    Sender.BOT,
                    {
                        "type": "error",
                        "text": f"API错误: {str(error)}"
                    }
                )
                if response:
                    self._render_message(
                        Sender.BOT,
                        response
                    )

        # 创建API配置
        api_config = APIConfig(
            provider=APIProvider.OPENROUTER,
            api_key=st.session_state.api_key,
            base_url=st.session_state.base_url,
            model=st.session_state.model
        )

        # 创建回调配置
        callback_config = CallbackConfig(
            output=output_callback,
            tool_output=tool_output_callback,
            api_response=api_response_callback
        )

        return await sampling_loop(
            api_config=api_config,
            callback_config=callback_config,
            messages=st.session_state.messages,
        )

    async def process_messages(self):
        """处理消息并调用API"""
        if not st.session_state.api_key:
            st.error("请先配置API密钥")
            return

        with st.spinner("思考中..."):
            try:
                # 运行采样循环
                messages = await self._run_sampling_loop()
                
                # 更新消息历史
                if messages:
                    st.session_state.messages = messages
                
            except Exception as e:
                st.error(f"处理消息时出错: {str(e)}")
                logger.exception("消息处理错误")

    async def run(self):
        """运行UI"""
        st.title("🖥️ 计算机控制助手")
        
        # 渲染侧边栏
        self.render_sidebar()
        
        # 显示历史消息
        self.render_messages()
        
        # 处理用户输入
        await self.handle_user_input()

async def main():
    """主函数"""
    try:
        ui = StreamlitUI()
        await ui.run()
    except Exception as e:
        st.error(f"应用程序错误: {str(e)}")
        logger.exception("应用程序错误")

if __name__ == "__main__":
    anyio.run(main)
