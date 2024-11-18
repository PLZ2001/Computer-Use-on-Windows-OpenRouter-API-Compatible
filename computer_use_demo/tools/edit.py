"""文件编辑工具"""

from collections import defaultdict
from pathlib import Path
from typing import DefaultDict, List, Literal, Optional, get_args
import logging

from .base import BaseTool, ToolResult, ToolFactory
from .exceptions import FileOperationError, ValidationError

logger = logging.getLogger(__name__)

# 常量
SNIPPET_LINES = 4  # 显示编辑上下文的行数

Command = Literal[
    "view",
    "create",
    "str_replace",
    "insert",
    "undo_edit",
]

class FileHistory:
    """文件历史记录管理器"""
    
    def __init__(self):
        self._history: DefaultDict[Path, List[str]] = defaultdict(list)
        
    def push(self, path: Path, content: str) -> None:
        """添加历史记录"""
        self._history[path].append(content)
        
    def pop(self, path: Path) -> Optional[str]:
        """获取上一个版本"""
        if not self._history[path]:
            return None
        return self._history[path].pop()
        
    def has_history(self, path: Path) -> bool:
        """检查是否有历史记录"""
        return bool(self._history[path])

class FileManager:
    """文件操作管理器"""
    
    @staticmethod
    def read_file(path: Path) -> str:
        """读取文件内容"""
        try:
            return path.read_text(encoding='utf-8')
        except Exception as e:
            raise FileOperationError(f"读取文件 '{path}' 失败: {str(e)}")

    @staticmethod
    def write_file(path: Path, content: str) -> None:
        """写入文件内容"""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding='utf-8')
        except Exception as e:
            raise FileOperationError(f"写入文件 '{path}' 失败: {str(e)}")

    @staticmethod
    def format_output(content: str, file_desc: str, start_line: int = 1) -> str:
        """格式化输出内容"""
        content = content.expandtabs()
        numbered_lines = [
            f"{i + start_line:6}\t{line}"
            for i, line in enumerate(content.split('\n'))
        ]
        return (
            f"文件 {file_desc} 的内容:\n"
            + '\n'.join(numbered_lines)
            + '\n'
        )

@ToolFactory.register
class EditTool(BaseTool):
    """一个强大的文件编辑工具，支持查看、创建、编辑和管理文件内容，具有历史记录跟踪功能。提供多种编辑操作，包括文本替换、行插入和编辑撤销。支持查看文件内容时的行号范围控制，并在编辑操作后显示上下文。所有编辑操作都可以通过撤销功能恢复到之前的状态。"""

    name: Literal["edit"] = "edit"
    
    parameters_schema = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "enum": ["view", "create", "str_replace", "insert", "undo_edit"],
                "description": "要执行的编辑命令：view（显示文件内容），create（创建新文件），str_replace（替换文本），insert（在行插入），undo_edit（撤销最后更改）"
            },
            "path": {
                "type": "string",
                "description": "要操作的文件的绝对路径"
            },
            "file_text": {
                "type": "string",
                "description": "'create'命令需要此参数。要写入新文件的内容。"
            },
            "view_range": {
                "type": "array",
                "items": {"type": "integer"},
                "minItems": 2,
                "maxItems": 2,
                "description": "'view'命令的可选参数。指定要查看的起始和结束行号[start, end]。使用-1表示查看到最后一行。"
            },
            "old_str": {
                "type": "string",
                "description": "'str_replace'命令需要此参数。要替换的字符串。"
            },
            "new_str": {
                "type": "string",
                "description": "'str_replace'和'insert'命令需要此参数。要插入或替换的新字符串。"
            },
            "insert_line": {
                "type": "integer",
                "description": "'insert'命令需要此参数。要插入新内容的行号。"
            }
        },
        "required": ["command", "path"]
    }

    def __init__(self):
        super().__init__()
        self._history = FileHistory()
        self._file_manager = FileManager()

    async def validate_params(self, **kwargs) -> None:
        """验证参数"""
        command = kwargs.get("command")
        if not command:
            raise ValidationError("未提供命令")
        if command not in get_args(Command):
            raise ValidationError(f"无效的命令: {command}")
            
        path = kwargs.get("path")
        if not path:
            raise ValidationError("未提供文件路径")
            
        _path = Path(path)
        self._validate_path(command, _path)

    def _validate_path(self, command: str, path: Path) -> None:
        """验证路径和命令的组合是否有效"""
        # 检查是否为绝对路径
        if not path.is_absolute():
            suggested_path = Path.cwd() / path
            raise ValidationError(
                f"路径 '{path}' 不是绝对路径。是否要使用 '{suggested_path}'?"
            )

        # 检查路径是否存在（除了create命令）
        if not path.exists() and command != "create":
            raise ValidationError(f"路径 '{path}' 不存在")

        # 检查是否为目录
        if path.is_dir() and command != "view":
            raise ValidationError(
                f"路径 '{path}' 是一个目录。只有 'view' 命令可以用于目录"
            )

        # 检查create命令的路径是否已存在
        if command == "create" and path.exists():
            raise ValidationError(
                f"路径 '{path}' 已存在。'create' 命令不能覆盖现有文件"
            )

    async def execute(
        self,
        *,
        command: Command,
        path: str,
        file_text: Optional[str] = None,
        view_range: Optional[List[int]] = None,
        old_str: Optional[str] = None,
        new_str: Optional[str] = None,
        insert_line: Optional[int] = None,
        **kwargs,
    ) -> ToolResult:
        """执行文件编辑命令"""
        _path = Path(path)

        try:
            if command == "view":
                return await self._view(_path, view_range)
            elif command == "create":
                if not file_text:
                    raise ValidationError("create命令需要提供file_text参数")
                return await self._create(_path, file_text)
            elif command == "str_replace":
                if not old_str:
                    raise ValidationError("str_replace命令需要提供old_str参数")
                return await self._str_replace(_path, old_str, new_str or "")
            elif command == "insert":
                if insert_line is None:
                    raise ValidationError("insert命令需要提供insert_line参数")
                if new_str is None:
                    raise ValidationError("insert命令需要提供new_str参数")
                return await self._insert(_path, insert_line, new_str)
            elif command == "undo_edit":
                return await self._undo_edit(_path)
            
            raise ValidationError(f"无效的命令: {command}")

        except Exception as e:
            error_msg = f"文件操作失败: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            return ToolResult(error=error_msg)

    async def _view(self, path: Path, view_range: Optional[List[int]] = None) -> ToolResult:
        """查看文件或目录内容"""
        if path.is_dir():
            if view_range:
                raise ValidationError("不能对目录使用view_range参数")
            
            try:
                files = list(path.glob('**/*'))
                file_list = '\n'.join(str(f.relative_to(path)) for f in files)
                return ToolResult(
                    output=f"目录 '{path}' 中的文件:\n{file_list}"
                )
            except Exception as e:
                raise FileOperationError(f"列出目录 '{path}' 失败: {str(e)}")

        content = self._file_manager.read_file(path)
        
        if view_range:
            if len(view_range) != 2 or not all(isinstance(x, int) for x in view_range):
                raise ValidationError("view_range必须是包含两个整数的列表")
            
            lines = content.split('\n')
            start, end = view_range
            
            if start < 1 or start > len(lines):
                raise ValidationError(f"无效的起始行: {start}")
            if end != -1 and (end < start or end > len(lines)):
                raise ValidationError(f"无效的结束行: {end}")
            
            content = '\n'.join(
                lines[start - 1 : end if end != -1 else None]
            )

        return ToolResult(
            output=self._file_manager.format_output(
                content, str(path), 
                start_line=view_range[0] if view_range else 1
            )
        )

    async def _create(self, path: Path, content: str) -> ToolResult:
        """创建新文件"""
        self._file_manager.write_file(path, content)
        return ToolResult(output=f"文件已成功创建于 '{path}'")

    async def _str_replace(self, path: Path, old_str: str, new_str: str) -> ToolResult:
        """替换文件中的字符串"""
        content = self._file_manager.read_file(path)
        old_str = old_str.expandtabs()
        new_str = new_str.expandtabs()

        # 检查old_str是否唯一
        occurrences = content.count(old_str)
        if occurrences == 0:
            raise ValidationError(f"在文件中未找到字符串 '{old_str}'")
        if occurrences > 1:
            lines = [
                i + 1
                for i, line in enumerate(content.split('\n'))
                if old_str in line
            ]
            raise ValidationError(
                f"在第 {lines} 行找到多个 '{old_str}' 的匹配项"
            )

        # 保存历史记录
        self._history.push(path, content)

        # 执行替换
        new_content = content.replace(old_str, new_str)
        self._file_manager.write_file(path, new_content)

        # 创建编辑片段
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if old_str in line:
                start = max(0, i - SNIPPET_LINES)
                end = min(len(lines), i + SNIPPET_LINES + 1)
                snippet = '\n'.join(lines[start:end])
                return ToolResult(
                    output=f"替换成功。上下文如下:\n"
                    + self._file_manager.format_output(
                        snippet, f"{path}中的编辑部分", start + 1
                    )
                )

        return ToolResult(output=f"在 '{path}' 中替换成功")

    async def _insert(self, path: Path, insert_line: int, new_str: str) -> ToolResult:
        """在指定行插入内容"""
        content = self._file_manager.read_file(path)
        lines = content.split('\n')

        if insert_line < 0 or insert_line > len(lines):
            raise ValidationError(
                f"无效的插入行号 {insert_line}。文件共有 {len(lines)} 行"
            )

        # 保存历史记录
        self._history.push(path, content)

        # 执行插入
        new_str = new_str.expandtabs()
        new_lines = (
            lines[:insert_line]
            + new_str.split('\n')
            + lines[insert_line:]
        )
        new_content = '\n'.join(new_lines)
        self._file_manager.write_file(path, new_content)

        # 创建编辑片段
        start = max(0, insert_line - SNIPPET_LINES)
        end = min(len(new_lines), insert_line + SNIPPET_LINES + new_str.count('\n') + 1)
        snippet = '\n'.join(new_lines[start:end])

        return ToolResult(
            output=f"插入成功。上下文如下:\n"
            + self._file_manager.format_output(
                snippet, f"{path}中的编辑部分", start + 1
            )
        )

    async def _undo_edit(self, path: Path) -> ToolResult:
        """撤销最后一次编辑"""
        if not self._history.has_history(path):
            raise ValidationError(f"文件 '{path}' 没有编辑历史")

        content = self._history.pop(path)
        if content is None:
            raise ValidationError(f"无法获取文件 '{path}' 的历史版本")
            
        self._file_manager.write_file(path, content)

        return ToolResult(
            output=f"已撤销最后一次编辑。当前内容:\n"
            + self._file_manager.format_output(content, str(path))
        )
