"""统一的配置管理模块"""

import os
from dataclasses import dataclass
from typing import Optional
from pathlib import Path

@dataclass
class DisplayConfig:
    """显示相关配置"""
    SCREENSHOT_DELAY: float = 1.5
    MAX_IMAGE_SIZE: int = 1 * 1024 * 1024  # 1MB

@dataclass
class PathConfig:
    """路径相关配置"""
    OUTPUT_DIR: Path = Path(os.getenv('TEMP', '.')) / 'outputs'
    
    def __post_init__(self):
        self.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

@dataclass
class APIConfig:
    """API相关配置"""
    MAX_TOKENS: int = 4096
    REQUEST_TIMEOUT: float = 60.0

class Config:
    """全局配置单例类"""
    _instance: Optional['Config'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.display = DisplayConfig()
            cls._instance.path = PathConfig()
            cls._instance.api = APIConfig()
        return cls._instance

    @classmethod
    def get_instance(cls) -> 'Config':
        """获取配置单例实例"""
        return cls()
