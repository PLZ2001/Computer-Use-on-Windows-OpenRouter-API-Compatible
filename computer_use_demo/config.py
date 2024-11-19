"""统一的配置管理模块"""

import os
from dataclasses import dataclass
from typing import Dict, Optional
from pathlib import Path

@dataclass
class ComputerConfig:
    """Computer工具配置"""
    # 显示相关
    TYPING_GROUP_SIZE: int = 50
    SCREENSHOT_DELAY: float = 1.5
    MAX_IMAGE_SIZE: int = 5 * 1024 * 1024  # 5MB
    ONLY_N_MOST_RECENT_IMAGES: int = 5  # 只保留最近的N张图片
    
    # 分辨率目标
    SCALING_TARGETS: Dict[str, Dict[str, int]] = None
    
    def __post_init__(self):
        if self.SCALING_TARGETS is None:
            self.SCALING_TARGETS = {
                "16:10": {"width": 1280, "height": 800},   # 16:10标准
                "16:9": {"width": 1366, "height": 768},    # 16:9标准
                "4:3": {"width": 1280, "height": 960},     # 4:3标准
                "3:2": {"width": 1350, "height": 900},     # 3:2标准
                "5:4": {"width": 1280, "height": 1024},    # 5:4标准
            }

@dataclass
class EditConfig:
    """Edit工具配置"""
    SNIPPET_LINES: int = 4  # 显示编辑上下文的行数

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
            # 初始化各工具的配置
            cls._instance.computer = ComputerConfig()
            cls._instance.edit = EditConfig()
            cls._instance.path = PathConfig()
            cls._instance.api = APIConfig()
        return cls._instance

    @classmethod
    def get_instance(cls) -> 'Config':
        """获取配置单例实例"""
        return cls()
