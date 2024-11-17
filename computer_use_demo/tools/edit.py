"""File editing tool with history support."""

from collections import defaultdict
from pathlib import Path
from typing import Literal, Optional, Any, get_args
import logging

from .base import BaseAnthropicTool, CLIResult, ToolError, ToolResult

logger = logging.getLogger(__name__)

# Constants
SNIPPET_LINES = 4  # 显示编辑上下文的行数

Command = Literal[
    "view",
    "create",
    "str_replace",
    "insert",
    "undo_edit",
]

class EditTool(BaseAnthropicTool):
    """Enhanced file editing tool with history support."""

    name: Literal["str_replace_editor"] = "str_replace_editor"
    api_type: Literal["text_editor_20241022"] = "text_editor_20241022"

    def __init__(self):
        self._file_history = defaultdict(list)
        super().__init__()

    def to_params(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.api_type,
        }

    async def __call__(
        self,
        *,
        command: Command,
        path: str,
        file_text: Optional[str] = None,
        view_range: Optional[list[int]] = None,
        old_str: Optional[str] = None,
        new_str: Optional[str] = None,
        insert_line: Optional[int] = None,
        **kwargs,
    ) -> ToolResult:
        """Execute file editing commands."""
        try:
            _path = Path(path)
            self._validate_path(command, _path)

            if command == "view":
                return await self._view(_path, view_range)
            elif command == "create":
                if not file_text:
                    raise ToolError("Parameter 'file_text' is required for create command")
                return self._create(_path, file_text)
            elif command == "str_replace":
                if not old_str:
                    raise ToolError("Parameter 'old_str' is required for str_replace command")
                return self._str_replace(_path, old_str, new_str or "")
            elif command == "insert":
                if insert_line is None:
                    raise ToolError("Parameter 'insert_line' is required for insert command")
                if new_str is None:
                    raise ToolError("Parameter 'new_str' is required for insert command")
                return self._insert(_path, insert_line, new_str)
            elif command == "undo_edit":
                return self._undo_edit(_path)
            
            raise ToolError(
                f"Unrecognized command: {command}. Allowed commands: {', '.join(get_args(Command))}"
            )

        except Exception as e:
            error_msg = f"File operation failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return ToolResult(error=error_msg)

    def _validate_path(self, command: str, path: Path) -> None:
        """验证路径和命令的组合是否有效。"""
        # 检查是否为绝对路径
        if not path.is_absolute():
            suggested_path = Path.cwd() / path
            raise ToolError(
                f"Path '{path}' is not absolute. Did you mean '{suggested_path}'?"
            )

        # 检查路径是否存在（除了create命令）
        if not path.exists() and command != "create":
            raise ToolError(f"Path '{path}' does not exist")

        # 检查是否为目录
        if path.is_dir() and command != "view":
            raise ToolError(
                f"Path '{path}' is a directory. Only 'view' command can be used on directories"
            )

        # 检查create命令的路径是否已存在
        if command == "create" and path.exists():
            raise ToolError(
                f"Path '{path}' already exists. Cannot overwrite existing files with 'create'"
            )

    def _read_file(self, path: Path) -> str:
        """读取文件内容。"""
        try:
            return path.read_text(encoding='utf-8')
        except Exception as e:
            raise ToolError(f"Failed to read file '{path}': {str(e)}")

    def _write_file(self, path: Path, content: str) -> None:
        """写入文件内容。"""
        try:
            # 确保父目录存在
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
        except Exception as e:
            raise ToolError(f"Failed to write to file '{path}': {str(e)}")

    def _make_output(self, content: str, file_desc: str, start_line: int = 1) -> str:
        """格式化输出内容。"""
        content = content.expandtabs()
        numbered_lines = [
            f"{i + start_line:6}\t{line}"
            for i, line in enumerate(content.split('\n'))
        ]
        return (
            f"Content of {file_desc}:\n"
            + '\n'.join(numbered_lines)
            + '\n'
        )

    async def _view(self, path: Path, view_range: Optional[list[int]] = None) -> ToolResult:
        """查看文件或目录内容。"""
        if path.is_dir():
            if view_range:
                raise ToolError("Cannot use view_range with directories")
            
            try:
                files = list(path.glob('**/*'))
                file_list = '\n'.join(str(f.relative_to(path)) for f in files)
                return ToolResult(
                    output=f"Files in directory '{path}':\n{file_list}"
                )
            except Exception as e:
                raise ToolError(f"Failed to list directory '{path}': {str(e)}")

        content = self._read_file(path)
        
        if view_range:
            if len(view_range) != 2 or not all(isinstance(x, int) for x in view_range):
                raise ToolError("view_range must be a list of two integers")
            
            lines = content.split('\n')
            start, end = view_range
            
            if start < 1 or start > len(lines):
                raise ToolError(f"Invalid start line: {start}")
            if end != -1 and (end < start or end > len(lines)):
                raise ToolError(f"Invalid end line: {end}")
            
            content = '\n'.join(
                lines[start - 1 : end if end != -1 else None]
            )

        return ToolResult(
            output=self._make_output(content, str(path), start_line=view_range[0] if view_range else 1)
        )

    def _create(self, path: Path, content: str) -> ToolResult:
        """创建新文件。"""
        self._write_file(path, content)
        return ToolResult(output=f"File created successfully at '{path}'")

    def _str_replace(self, path: Path, old_str: str, new_str: str) -> ToolResult:
        """替换文件中的字符串。"""
        content = self._read_file(path)
        old_str = old_str.expandtabs()
        new_str = new_str.expandtabs()

        # 检查old_str是否唯一
        occurrences = content.count(old_str)
        if occurrences == 0:
            raise ToolError(f"String '{old_str}' not found in file")
        if occurrences > 1:
            lines = [
                i + 1
                for i, line in enumerate(content.split('\n'))
                if old_str in line
            ]
            raise ToolError(
                f"Multiple occurrences of '{old_str}' found in lines {lines}"
            )

        # 保存历史记录
        self._file_history[path].append(content)

        # 执行替换
        new_content = content.replace(old_str, new_str)
        self._write_file(path, new_content)

        # 创建编辑片段
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if old_str in line:
                start = max(0, i - SNIPPET_LINES)
                end = min(len(lines), i + SNIPPET_LINES + 1)
                snippet = '\n'.join(lines[start:end])
                return ToolResult(
                    output=f"Replacement successful. Here's the context:\n"
                    + self._make_output(snippet, f"edited section in {path}", start + 1)
                )

        return ToolResult(output=f"Replacement successful in '{path}'")

    def _insert(self, path: Path, insert_line: int, new_str: str) -> ToolResult:
        """在指定行插入内容。"""
        content = self._read_file(path)
        lines = content.split('\n')

        if insert_line < 0 or insert_line > len(lines):
            raise ToolError(
                f"Invalid insert line {insert_line}. File has {len(lines)} lines"
            )

        # 保存历史记录
        self._file_history[path].append(content)

        # 执行插入
        new_str = new_str.expandtabs()
        new_lines = (
            lines[:insert_line]
            + new_str.split('\n')
            + lines[insert_line:]
        )
        new_content = '\n'.join(new_lines)
        self._write_file(path, new_content)

        # 创建编辑片段
        start = max(0, insert_line - SNIPPET_LINES)
        end = min(len(new_lines), insert_line + SNIPPET_LINES + new_str.count('\n') + 1)
        snippet = '\n'.join(new_lines[start:end])

        return ToolResult(
            output=f"Insertion successful. Here's the context:\n"
            + self._make_output(snippet, f"edited section in {path}", start + 1)
        )

    def _undo_edit(self, path: Path) -> ToolResult:
        """撤销最后一次编辑。"""
        if not self._file_history[path]:
            raise ToolError(f"No edit history for file '{path}'")

        content = self._file_history[path].pop()
        self._write_file(path, content)

        return ToolResult(
            output=f"Last edit undone. Current content:\n"
            + self._make_output(content, str(path))
        )
