"""Command execution tool."""

import asyncio
import logging
import os
import subprocess
import concurrent.futures
from typing import Literal

from .base import BaseAnthropicTool, CLIResult, ToolResult
from .computer import ComputerTool

logger = logging.getLogger(__name__)

class CommandTool(BaseAnthropicTool):
    """Tool for executing shell commands."""

    name: Literal["bash"] = "bash"

    def __init__(self):
        super().__init__()
        self.computer = ComputerTool()

    async def __call__(
        self,
        *,
        command: str | None = None,
        **kwargs,
    ) -> ToolResult:
        """Execute a shell command."""
        if not command:
            return ToolResult(error="No command provided")

        try:
            logger.info(f"Executing command: {command}")
            
            # 使用线程池执行同步的subprocess调用
            loop = asyncio.get_event_loop()
            with concurrent.futures.ThreadPoolExecutor() as pool:
                if os.name == 'nt':
                    # Windows: 使用cmd.exe执行命令
                    full_command = f'cmd /c {command}'
                else:
                    # Unix: 使用bash执行命令
                    full_command = command

                # 在线程池中执行同步的subprocess.run
                process_result = await loop.run_in_executor(
                    pool,
                    lambda: subprocess.run(
                        full_command,
                        shell=True,
                        capture_output=True,
                        text=True,
                        encoding='utf-8',
                        errors='ignore'
                    )
                )

            stdout_str = process_result.stdout
            stderr_str = process_result.stderr
            
            logger.debug(f"Command output - stdout: {stdout_str}, stderr: {stderr_str}")
            
            result = CLIResult(
                returncode=process_result.returncode,
                stdout=stdout_str,
                stderr=stderr_str
            )

            if result.returncode != 0:
                error_msg = f"Command failed with code {result.returncode}\n{result.stderr}"
                logger.error(error_msg)
                return ToolResult(error=error_msg)

            # 如果没有stdout输出，返回截图
            if not stdout_str.strip():
                return await self.computer.take_screenshot()

            return ToolResult(output=stdout_str)

        except Exception as e:
            error_msg = f"Command execution failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return ToolResult(error=error_msg)
