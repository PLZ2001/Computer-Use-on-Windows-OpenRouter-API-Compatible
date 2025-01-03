"""命令执行工具"""

import asyncio
import concurrent.futures
import subprocess
from dataclasses import dataclass
from typing import Literal, Optional

from .base import BaseTool, ToolResult, ToolFactory
from .exceptions import ExecutionError, ValidationError

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
    """Windows命令执行工具。通过cmd.exe执行单次命令，捕获命令的标准输出和错误输出。
    每次执行都是独立的进程。"""

    name: Literal["command"] = "command"
    
    parameters_schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "要执行的Windows命令"
            }
        },
        "required": ["command"]
    }

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
                # Windows: 使用cmd.exe执行命令
                full_command = f'cmd /c {command}'

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

            output = result.stdout.strip()
            if not output:
                return ToolResult(output="命令执行成功,但没有标准输出。如有必要,请通过其他方式验证执行结果。")
            
            return ToolResult(output=output)

        except Exception as e:
            error_msg = f"命令执行失败: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            raise ExecutionError(error_msg)
