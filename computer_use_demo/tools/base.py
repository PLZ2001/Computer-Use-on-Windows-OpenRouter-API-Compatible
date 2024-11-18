"""工具基类和工厂模块"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional, Type

from ..config import Config
from .exceptions import ToolError, ValidationError

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class ToolResult:
    """工具执行结果"""
    output: Optional[str] = None
    error: Optional[str] = None
    base64_image: Optional[str] = None
    system: Optional[str] = None

    def is_success(self) -> bool:
        """检查执行是否成功"""
        return self.error is None

    def with_error(self, error: str) -> 'ToolResult':
        """创建一个带有错误信息的新结果"""
        return ToolResult(error=error)

    def with_output(self, output: str) -> 'ToolResult':
        """创建一个带有输出的新结果"""
        return ToolResult(output=output)

class BaseTool(ABC):
    """工具基类"""
    
    def __init__(self):
        self.config = Config.get_instance()
        self.logger = logging.getLogger(self.__class__.__name__)

    @property
    @abstractmethod
    def name(self) -> str:
        """工具名称"""
        pass

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """执行工具操作"""
        pass

    async def __call__(self, **kwargs) -> ToolResult:
        """调用工具"""
        try:
            self.logger.debug(f"执行工具 {self.name} 参数: {kwargs}")
            await self.validate_params(**kwargs)
            result = await self.execute(**kwargs)
            self.logger.debug(f"工具 {self.name} 执行结果: {result}")
            return result
        except ValidationError as e:
            self.logger.error(f"参数验证错误: {e}")
            return ToolResult(error=f"参数验证错误: {str(e)}")
        except ToolError as e:
            self.logger.error(f"工具执行错误: {e}")
            return ToolResult(error=f"工具执行错误: {str(e)}")
        except Exception as e:
            self.logger.exception(f"未预期的错误: {e}")
            return ToolResult(error=f"未预期的错误: {str(e)}")

    async def validate_params(self, **kwargs) -> None:
        """验证参数"""
        pass

class ToolFactory:
    """工具工厂类"""
    
    _tools: Dict[str, Type[BaseTool]] = {}

    @classmethod
    def register(cls, tool_class: Type[BaseTool]) -> Type[BaseTool]:
        """注册工具类"""
        cls._tools[tool_class.name] = tool_class
        return tool_class

    @classmethod
    def create(cls, name: str, **kwargs) -> BaseTool:
        """创建工具实例"""
        if name not in cls._tools:
            raise ValidationError(f"未知的工具: {name}")
        return cls._tools[name](**kwargs)

class ToolCollection:
    """工具集合类"""
    
    def __init__(self, *tools: BaseTool):
        self.tools = {tool.name: tool for tool in tools}

    async def run(self, name: str, tool_input: Dict[str, Any]) -> ToolResult:
        """运行指定的工具"""
        if name not in self.tools:
            return ToolResult(error=f"工具 {name} 未找到")
        return await self.tools[name](**tool_input)
