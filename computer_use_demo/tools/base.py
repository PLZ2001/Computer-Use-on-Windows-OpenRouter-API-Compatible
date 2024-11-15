"""Base classes for Anthropic tools."""

from dataclasses import dataclass
from typing import Any, Optional

class ToolError(Exception):
    """Error raised by tools."""
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)

@dataclass
class ToolResult:
    """Result from a tool execution."""
    output: Optional[str] = None
    error: Optional[str] = None
    base64_image: Optional[str] = None
    system: Optional[str] = None

@dataclass
class CLIResult:
    """Result from a CLI command execution."""
    returncode: int
    stdout: str
    stderr: str

    def __str__(self) -> str:
        return f"CLIResult(returncode={self.returncode}, stdout={self.stdout}, stderr={self.stderr})"

    def replace(self, **kwargs) -> 'CLIResult':
        """Create a new CLIResult with some fields replaced."""
        return CLIResult(
            returncode=kwargs.get('returncode', self.returncode),
            stdout=kwargs.get('stdout', self.stdout),
            stderr=kwargs.get('stderr', self.stderr)
        )

class BaseAnthropicTool:
    """Base class for Anthropic tools."""
    
    async def __call__(self, **kwargs) -> ToolResult:
        """Execute the tool with the given parameters."""
        raise NotImplementedError()

    def to_params(self) -> dict[str, Any]:
        """Convert tool to API parameters."""
        raise NotImplementedError()

class ToolCollection:
    """Collection of tools that can be used by the agent."""
    
    def __init__(self, *tools: BaseAnthropicTool):
        self.tools = {tool.name: tool for tool in tools}

    async def run(self, name: str, tool_input: dict[str, Any]) -> ToolResult:
        """Run a tool by name with the given input."""
        if name not in self.tools:
            return ToolResult(error=f"Tool {name} not found")
        return await self.tools[name](**tool_input)

    def to_params(self) -> list[dict[str, Any]]:
        """Convert all tools to API parameters."""
        return [tool.to_params() for tool in self.tools.values()]
