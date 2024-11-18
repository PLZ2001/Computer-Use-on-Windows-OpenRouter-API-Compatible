"""统一的异常处理模块"""

from typing import Optional

class ToolError(Exception):
    """工具异常基类"""
    def __init__(self, message: str, code: Optional[str] = None):
        self.message = message
        self.code = code
        super().__init__(message)

class ValidationError(ToolError):
    """参数验证错误"""
    pass

class ExecutionError(ToolError):
    """执行错误"""
    pass

class FileOperationError(ToolError):
    """文件操作错误"""
    pass

class APIError(ToolError):
    """API调用错误"""
    pass

class ConfigurationError(ToolError):
    """配置错误"""
    pass
