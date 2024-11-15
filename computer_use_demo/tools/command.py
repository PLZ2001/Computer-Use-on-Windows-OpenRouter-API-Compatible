"""Command execution tool."""

import asyncio
import logging
import os
import shlex
from typing import Any, Literal

from .base import BaseAnthropicTool, CLIResult, ToolError, ToolResult

logger = logging.getLogger(__name__)

class CommandTool(BaseAnthropicTool):
    """Tool for executing shell commands."""

    name: Literal["bash"] = "bash"
    api_type: Literal["bash_20241022"] = "bash_20241022"

    def to_params(self) -> dict[str, Any]:
        return {"name": self.name, "type": self.api_type}

    async def __call__(
        self,
        *,
        command: str | None = None,
        restart: bool | None = None,
        **kwargs,
    ) -> ToolResult:
        """Execute a shell command."""
        if restart:
            return ToolResult(output="Tool restarted")

        if not command:
            return ToolResult(error="No command provided")

        try:
            # Use cmd.exe on Windows
            if os.name == 'nt':
                process = await asyncio.create_subprocess_shell(
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    shell=True
                )
            else:
                # Use bash on Unix
                process = await asyncio.create_subprocess_exec(
                    'bash',
                    '-c',
                    command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )

            stdout, stderr = await process.communicate()
            
            # Decode output using UTF-8, ignoring errors
            stdout_str = stdout.decode('utf-8', errors='ignore') if stdout else ''
            stderr_str = stderr.decode('utf-8', errors='ignore') if stderr else ''
            
            result = CLIResult(
                returncode=process.returncode,
                stdout=stdout_str,
                stderr=stderr_str
            )

            if result.returncode != 0:
                return ToolResult(
                    error=f"Command failed with code {result.returncode}\n{result.stderr}"
                )

            return ToolResult(output=result.stdout, error=result.stderr)

        except Exception as e:
            logger.error(f"Command execution failed: {e}")
            return ToolResult(error=f"Command execution failed: {e}")

    def _escape_command(self, command: str) -> str:
        """Escape a command for shell execution."""
        if os.name == 'nt':
            # Windows: wrap in quotes if contains spaces
            if ' ' in command:
                return f'"{command}"'
            return command
        else:
            # Unix: use shlex
            return shlex.quote(command)
