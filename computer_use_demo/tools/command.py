"""命令执行工具"""

import asyncio
import concurrent.futures
import logging
import os
import subprocess
from dataclasses import dataclass
from typing import Literal, Optional

from .base import BaseTool, ToolResult, ToolFactory
from .computer import ComputerTool
from .exceptions import ExecutionError, ValidationError

logger = logging.getLogger(__name__)

@dataclass
class CLIResult:
    """命令行执行结果"""
    returncode: int
    stdout: str
    stderr: str

    def __str__(self) -> str:
        return f"CLIResult(returncode={self.returncode}, stdout={self.stdout}, stderr={self.stderr})"

    def replace(self, **kwargs) -> 'CLIResult':
        """创建一个新的CLIResult，替换部分字段"""
        return CLIResult(
            returncode=kwargs.get('returncode', self.returncode),
            stdout=kwargs.get('stdout', self.stdout),
            stderr=kwargs.get('stderr', self.stderr)
        )

    def is_success(self) -> bool:
        """检查命令是否执行成功"""
        return self.returncode == 0

@ToolFactory.register
class CommandTool(BaseTool):
    """命令执行工具"""

    name: Literal["bash"] = "bash"

    def __init__(self):
        super().__init__()
        self.computer = ComputerTool()

    async def validate_params(self, **kwargs) -> None:
        """验证参数"""
        if not kwargs.get("command"):
            raise ValidationError("未提供命令")

    async def execute(
        self,
        *,
        command: Optional[str] = None,
        **kwargs,
    ) -> ToolResult:
        """执行命令"""
        try:
            self.logger.info(f"执行命令: {command}")
            
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

            result = CLIResult(
                returncode=process_result.returncode,
                stdout=process_result.stdout,
                stderr=process_result.stderr
            )

            self.logger.debug(f"命令输出 - stdout: {result.stdout}, stderr: {result.stderr}")

            if not result.is_success():
                error_msg = f"命令执行失败，返回码 {result.returncode}\n{result.stderr}"
                self.logger.error(error_msg)
                return ToolResult(error=error_msg)

            # 如果没有stdout输出，返回截图
            if not result.stdout.strip():
                return await self.computer.take_screenshot()

            return ToolResult(output=result.stdout)

        except Exception as e:
            error_msg = f"命令执行失败: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            raise ExecutionError(error_msg)
