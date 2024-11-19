"""计算机交互工具"""

import asyncio
import base64
import io
import logging
import ctypes
from enum import StrEnum
from typing import List, Literal, Optional, Tuple, TypedDict

import cv2
import numpy as np
import pyautogui
from PIL import Image
import pyperclip

from .base import BaseTool, ToolResult, ToolFactory
from .exceptions import ValidationError, ExecutionError

class Action(StrEnum):
    """可执行的动作类型"""
    KEY = "key"
    TYPE = "type"
    MOUSE_MOVE = "mouse_move"
    LEFT_CLICK = "left_click"
    LEFT_CLICK_DRAG = "left_click_drag"
    RIGHT_CLICK = "right_click"
    MIDDLE_CLICK = "middle_click"
    DOUBLE_CLICK = "double_click"
    SCREENSHOT = "screenshot"
    CURSOR_POSITION = "cursor_position"
    SCROLL_UP = "scroll_up"
    SCROLL_DOWN = "scroll_down"

class ComputerToolOptions(TypedDict):
    """计算机工具选项"""
    display_height_px: int
    display_width_px: int
    display_number: Optional[int]

class CoordinateTranslator:
    """坐标转换器"""
    
    def __init__(self, dpi_scale: float, taskbar_offset: int, 
                 physical_width: int, physical_height: int,
                 target_width: int, target_height: int):
        self.dpi_scale = dpi_scale
        self.taskbar_offset = taskbar_offset
        self.physical_width = physical_width
        self.physical_height = physical_height
        self.target_width = target_width
        self.target_height = target_height
        
        # 计算缩放因子
        self.x_scale = physical_width / target_width
        self.y_scale = physical_height / target_height
        
        logger = logging.getLogger(self.__class__.__name__)
        logger.debug(f"坐标转换器初始化:")
        logger.debug(f"DPI缩放: {dpi_scale}")
        logger.debug(f"任务栏偏移: {taskbar_offset}")
        logger.debug(f"X缩放: {self.x_scale}")
        logger.debug(f"Y缩放: {self.y_scale}")
    
    def api_to_screen(self, x: int, y: int) -> tuple[int, int]:
        """将API坐标转换为屏幕坐标"""
        screen_x = int(x * self.x_scale / self.dpi_scale)
        screen_y = int(y * self.y_scale / self.dpi_scale) + self.taskbar_offset
        return screen_x, screen_y
    
    def screen_to_api(self, x: int, y: int) -> tuple[int, int]:
        """将屏幕坐标转换为API坐标"""
        api_x = int(x * self.dpi_scale / self.x_scale)
        api_y = int((y - self.taskbar_offset) * self.dpi_scale / self.y_scale)
        return api_x, api_y

class IconDetector:
    """图标检测器"""
    
    def __init__(self, min_size: int = 16, max_size: int = 64):
        self.min_size = min_size
        self.max_size = max_size
        self.logger = logging.getLogger(self.__class__.__name__)
    
    def find_icon_center(self, screenshot: Image.Image, target_x: int, target_y: int) -> Optional[Tuple[int, int]]:
        """查找目标坐标附近的图标中心"""
        # 转换为OpenCV格式
        cv_image = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
        
        # 创建目标点周围的感兴趣区域
        roi_size = self.max_size * 2
        x1 = max(0, target_x - roi_size)
        y1 = max(0, target_y - roi_size)
        x2 = min(screenshot.width, target_x + roi_size)
        y2 = min(screenshot.height, target_y + roi_size)
        
        roi = cv_image[y1:y2, x1:x2]
        
        # 转换为灰度图
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        
        # 查找边缘
        edges = cv2.Canny(gray, 50, 150)
        
        # 查找轮廓
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        # 按大小过滤轮廓并找到最近的
        best_center = None
        min_distance = 5.0  # 仅考虑5px以内的范围
        
        for contour in contours:
            # 获取边界框
            x, y, w, h = cv2.boundingRect(contour)
            
            # 检查大小是否在图标范围内
            if (self.min_size <= w <= self.max_size and 
                self.min_size <= h <= self.max_size):
                
                # 计算中心点
                center_x = x1 + x + w//2
                center_y = y1 + y + h//2
                
                # 计算到目标的距离
                distance = ((center_x - target_x) ** 2 + 
                          (center_y - target_y) ** 2) ** 0.5
                
                if distance < min_distance:
                    min_distance = distance
                    best_center = (center_x, center_y)
        
        if best_center:
            self.logger.debug(f"找到图标中心点: {best_center}, 偏移距离: {min_distance:.1f}px")
        else:
            self.logger.debug("未找到图标，使用原始坐标")
            
        return best_center

@ToolFactory.register
class ComputerTool(BaseTool):
    """一个全面的工具，支持与计算机输入/输出设备交互，包括屏幕、键盘和鼠标。支持输入、点击、滚动和截图等操作。可以模拟各种用户操作，如键盘输入、鼠标移动、点击和拖拽，并能够获取屏幕截图和光标位置。"""

    name: Literal["computer"] = "computer"
    
    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "key",
                    "type",
                    "mouse_move",
                    "left_click",
                    "left_click_drag",
                    "right_click",
                    "middle_click",
                    "double_click",
                    "screenshot",
                    "cursor_position",
                    "scroll_up",
                    "scroll_down",
                ],
                "description": "指定要执行的计算机交互动作类型。每个动作对应特定的输入/输出设备交互。"
            },
            "text": {
                "type": "string",
                "description": "键盘输入动作（'key'或'type'）需要此参数。Windows键使用'win'。"
            },
            "coordinate": {
                "type": "array",
                "prefixItems": [
                    { "type": "number" },
                    { "type": "number" },
                ],
                "items": { "type": "number" },
                "description": "鼠标相关动作需要此参数。指定屏幕上的x,y坐标用于鼠标移动、点击或拖动操作。"
            },
            "scroll_amount": {
                "type": "integer",
                "minimum": 1,
                "description": "scroll_up和scroll_down动作的可选参数。指定滚动量。必须是正整数。默认为400。滚动方向由动作类型决定。"
            },
            "repeat": {
                "type": "integer",
                "minimum": 1,
                "description": "所有动作的可选参数。指定重复执行动作的次数。默认为1。可用于重复按键、点击、滚动等任何动作。"
            }
        },
        "required": ["action"]
    }

    def __init__(self):
        super().__init__()
        
        # 获取坐标系统信息
        dpi_scale, taskbar_offset, physical_width, physical_height = self._get_windows_coordinate_system()
        
        # 查找最佳匹配的目标分辨率
        aspect_ratio = physical_width / physical_height
        best_target = None
        best_ratio_diff = float('inf')
        
        for target in self.config.computer.SCALING_TARGETS.values():
            target_ratio = target["width"] / target["height"]
            ratio_diff = abs(target_ratio - aspect_ratio)
            
            if ratio_diff < best_ratio_diff:
                best_ratio_diff = ratio_diff
                best_target = target
        
        self.target_width = best_target["width"]
        self.target_height = best_target["height"]
        
        # 初始化坐标转换器
        self.translator = CoordinateTranslator(
            dpi_scale=dpi_scale,
            taskbar_offset=taskbar_offset,
            physical_width=physical_width,
            physical_height=physical_height,
            target_width=self.target_width,
            target_height=self.target_height
        )
        
        # 初始化图标检测器
        self.icon_detector = IconDetector()
        
        # 存储尺寸
        self.width = physical_width
        self.height = physical_height
        self.display_num = None
        
        self.logger.info(f"计算机工具初始化:")
        self.logger.info(f"物理分辨率: {self.width}x{self.height}")
        self.logger.info(f"目标分辨率: {self.target_width}x{self.target_height}")
        self.logger.info(f"DPI缩放: {dpi_scale}")

    @property
    def options(self) -> ComputerToolOptions:
        """获取工具选项"""
        return {
            "display_width_px": self.target_width,
            "display_height_px": self.target_height,
            "display_number": self.display_num,
        }

    async def validate_params(self, **kwargs) -> None:
        """验证参数"""
        action = kwargs.get("action")
        if not action:
            raise ValidationError("未提供action参数")
        if action not in Action.__members__.values():
            raise ValidationError(f"无效的action: {action}")

        # 验证特定动作的参数
        if action in (Action.KEY, Action.TYPE):
            if not kwargs.get("text"):
                raise ValidationError(f"{action}动作需要提供text参数")
            if kwargs.get("coordinate"):
                raise ValidationError(f"{action}动作不接受coordinate参数")

        if action in (Action.MOUSE_MOVE, Action.LEFT_CLICK_DRAG):
            if not kwargs.get("coordinate"):
                raise ValidationError(f"{action}动作需要提供coordinate参数")
            if kwargs.get("text"):
                raise ValidationError(f"{action}动作不接受text参数")

    async def execute(
        self,
        *,
        action: Action,
        text: Optional[str] = None,
        coordinate: Optional[tuple[int, int]] = None,
        scroll_amount: Optional[int] = None,
        repeat: Optional[int] = None,
        **kwargs,
    ) -> ToolResult:
        """执行计算机交互操作"""
        # 设置默认repeat值为1
        repeat_times = max(1, repeat or 1)
        
        try:
            if action in (Action.MOUSE_MOVE, Action.LEFT_CLICK_DRAG):
                if not isinstance(coordinate, (list, tuple)) or len(coordinate) != 2:
                    raise ValidationError(f"{coordinate}必须是长度为2的元组")
                if not all(isinstance(i, (int, float)) and i >= 0 for i in coordinate):
                    raise ValidationError(f"{coordinate}必须是非负数值")

                # 将API坐标转换为屏幕坐标
                x, y = self.translator.api_to_screen(coordinate[0], coordinate[1])
                self.logger.debug(f"移动到坐标: ({x}, {y})")

                for _ in range(repeat_times):
                    if action == Action.MOUSE_MOVE:
                        pyautogui.moveTo(x, y)
                    elif action == Action.LEFT_CLICK_DRAG:
                        pyautogui.dragTo(x, y, button='left')
                
                return await self.take_screenshot()

            if action in (Action.KEY, Action.TYPE):
                if not isinstance(text, str):
                    raise ValidationError(f"{text}必须是字符串")

                if action == Action.KEY:
                    key_parts = text.split('+')
                    self.logger.debug(f"重复按键 {repeat_times} 次")
                    
                    for _ in range(repeat_times):
                        if len(key_parts) > 1:
                            self.logger.debug(f"按下组合键: {key_parts}")
                            pyautogui.hotkey(*key_parts)
                        else:
                            self.logger.debug(f"按下按键: {text}")
                            pyautogui.press(text)
                    return await self.take_screenshot()
                elif action == Action.TYPE:
                    results = []
                    for _ in range(repeat_times):
                        for chunk in self._chunks(text, self.config.computer.TYPING_GROUP_SIZE):
                            self.logger.debug(f"输入文本块: {chunk}")
                            # 保存原始剪贴板内容
                            original_clipboard = pyperclip.paste()
                            # 使用剪贴板输入中文字符
                            pyperclip.copy(chunk)
                            pyautogui.hotkey('ctrl', 'v')
                            # 恢复原始剪贴板内容
                            pyperclip.copy(original_clipboard)
                            results.append(ToolResult(output=chunk))
                    screenshot = await self.take_screenshot()
                    return ToolResult(
                        output="".join(result.output or "" for result in results),
                        error="".join(result.error or "" for result in results),
                        base64_image=screenshot.base64_image,
                    )

            if action in (Action.SCROLL_UP, Action.SCROLL_DOWN):
                # 使用提供的滚动量或默认值
                default_amount = 400
                actual_amount = abs(scroll_amount if scroll_amount is not None else default_amount)
                
                # 根据动作方向决定滚动方向
                if action == Action.SCROLL_DOWN:
                    actual_amount = -actual_amount
                
                for _ in range(repeat_times):
                    self.logger.debug(f"滚动量: {actual_amount}")
                    pyautogui.scroll(actual_amount)
                
                return await self.take_screenshot()

            if action in (
                Action.LEFT_CLICK,
                Action.RIGHT_CLICK,
                Action.DOUBLE_CLICK,
                Action.MIDDLE_CLICK,
                Action.SCREENSHOT,
                Action.CURSOR_POSITION,
            ):
                if action == Action.SCREENSHOT:
                    return await self.take_screenshot()
                elif action == Action.CURSOR_POSITION:
                    pos = pyautogui.position()
                    api_x, api_y = self.translator.screen_to_api(pos.x, pos.y)
                    return ToolResult(output=f"X={api_x},Y={api_y}")
                else:
                    if coordinate is not None:
                        # 缩放坐标并使用智能点击
                        x, y = self.translator.api_to_screen(coordinate[0], coordinate[1])
                        await self._smart_click(x, y, action, repeat_times)
                    else:
                        # 在当前位置点击
                        click_map = {
                            Action.LEFT_CLICK: lambda: pyautogui.click(button='left'),
                            Action.RIGHT_CLICK: lambda: pyautogui.click(button='right'),
                            Action.MIDDLE_CLICK: lambda: pyautogui.click(button='middle'),
                            Action.DOUBLE_CLICK: lambda: pyautogui.doubleClick(),
                        }
                        for _ in range(repeat_times):
                            click_map[action]()
                    
                    return await self.take_screenshot()

            raise ValidationError(f"无效的动作: {action}")

        except Exception as e:
            error_msg = f"计算机交互失败: {str(e)}"
            self.logger.error(error_msg, exc_info=True)
            raise ExecutionError(error_msg)

    async def _smart_click(self, x: int, y: int, action: Action, repeat: int = 1) -> None:
        """执行智能点击"""
        # 获取截图用于图标检测
        screenshot = pyautogui.screenshot()
        
        # 尝试找到图标中心
        center = self.icon_detector.find_icon_center(screenshot, x, y)
        
        if center:
            # 使用检测到的中心点
            click_x, click_y = center
            self.logger.debug(f"使用检测到的图标中心点: ({click_x}, {click_y})")
        else:
            # 使用原始坐标
            click_x, click_y = x, y
            self.logger.debug(f"使用原始坐标: ({click_x}, {click_y})")
        
        # 移动到位置
        pyautogui.moveTo(click_x, click_y)
        
        # 执行点击动作
        click_map = {
            Action.LEFT_CLICK: lambda: pyautogui.click(button='left'),
            Action.RIGHT_CLICK: lambda: pyautogui.click(button='right'),
            Action.MIDDLE_CLICK: lambda: pyautogui.click(button='middle'),
            Action.DOUBLE_CLICK: lambda: pyautogui.doubleClick(),
        }
        
        for _ in range(repeat):
            click_map[action]()

    async def take_screenshot(self) -> ToolResult:
        """获取屏幕截图"""
        await asyncio.sleep(self.config.computer.SCREENSHOT_DELAY)
        
        # 使用PyAutoGUI获取截图
        screenshot = pyautogui.screenshot()
        self.logger.debug(f"原始尺寸: {screenshot.width}x{screenshot.height}")
        
        # 缩放到目标分辨率
        scaled_width, scaled_height = self.target_width, self.target_height
        self.logger.debug(f"缩放到: {scaled_width}x{scaled_height}")
        
        scaled = screenshot.resize((scaled_width, scaled_height), Image.Resampling.LANCZOS)
        
        # 尝试不同的压缩级别
        compression_levels = [
            # 1. 原始PNG
            lambda: self._save_png(scaled),
            # 2. 降低分辨率 + PNG
            lambda: self._save_png(scaled.resize(
                (scaled_width//2, scaled_height//2), 
                Image.Resampling.LANCZOS
            )),
            # 3. 转换为灰度 + PNG
            lambda: self._save_png(scaled.convert('L')),
            # 4. 降低分辨率 + 灰度 + PNG
            lambda: self._save_png(scaled.resize(
                (scaled_width//2, scaled_height//2), 
                Image.Resampling.LANCZOS
            ).convert('L')),
        ]
        
        # 尝试每个压缩级别直到文件大小小于限制
        for compress_method in compression_levels:
            img_buffer = compress_method()
            size = len(img_buffer.getvalue())
            self.logger.debug(f"压缩结果大小: {size/1024/1024:.1f}MB")
            
            if size <= self.config.computer.MAX_IMAGE_SIZE:
                return ToolResult(base64_image=base64.b64encode(img_buffer.getvalue()).decode())
        
        # 如果所有压缩方法都无法达到目标大小，使用最后一个结果
        img_buffer = compression_levels[-1]()
        return ToolResult(base64_image=base64.b64encode(img_buffer.getvalue()).decode())

    @staticmethod
    def _chunks(s: str, chunk_size: int) -> List[str]:
        """将字符串分割成固定大小的块"""
        return [s[i:i + chunk_size] for i in range(0, len(s), chunk_size)]

    @staticmethod
    def _save_png(image: Image.Image) -> io.BytesIO:
        """将图像保存为PNG格式"""
        img_buffer = io.BytesIO()
        image.save(img_buffer, format='PNG', optimize=True)
        img_buffer.seek(0)
        return img_buffer

    @staticmethod
    def _get_windows_coordinate_system() -> Tuple[float, float, float, float]:
        """获取Windows坐标系统信息"""
        try:
            user32 = ctypes.windll.user32
            user32.SetProcessDPIAware()
            
            # 获取物理屏幕指标
            physical_width = user32.GetSystemMetrics(0)  # SM_CXSCREEN
            physical_height = user32.GetSystemMetrics(1)  # SM_CYSCREEN
            
            # 获取工作区（屏幕减去任务栏）
            work_rect = ctypes.wintypes.RECT()
            user32.SystemParametersInfoW(48, 0, ctypes.byref(work_rect), 0)  # SPI_GETWORKAREA
            
            # 计算缩放因子
            dpi = user32.GetDpiForSystem()
            dpi_scale = dpi / 96.0
            
            # 获取主显示器信息
            monitor_info = ctypes.wintypes.MONITORINFO()
            monitor_info.cbSize = ctypes.sizeof(monitor_info)
            monitor_handle = user32.MonitorFromWindow(0, 2)  # MONITOR_DEFAULTTOPRIMARY
            user32.GetMonitorInfoW(monitor_handle, ctypes.byref(monitor_info))
            
            return (
                dpi_scale,
                work_rect.top,  # 任务栏偏移
                monitor_info.rcMonitor.right - monitor_info.rcMonitor.left,  # 显示器宽度
                monitor_info.rcMonitor.bottom - monitor_info.rcMonitor.top   # 显示器高度
            )
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.error(f"获取坐标系统失败: {e}")
            return 1.0, 0, pyautogui.size()[0], pyautogui.size()[1]
