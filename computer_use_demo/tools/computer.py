"""Windows-compatible computer interaction tool using pyautogui."""

import asyncio
import base64
import io
import os
import logging
import ctypes
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal, TypedDict, Optional, Tuple
from uuid import uuid4

import cv2
import numpy as np
import pyautogui
from PIL import Image, ImageDraw
from anthropic.types.beta import BetaToolComputerUse20241022Param
from dotenv import load_dotenv
import pyperclip

from .base import BaseAnthropicTool, ToolError, ToolResult

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Ensure PyAutoGUI fails safely
pyautogui.FAILSAFE = True

# Configure typing speed
TYPING_DELAY_MS = 12
TYPING_GROUP_SIZE = 50

# Configure screenshot directory
OUTPUT_DIR = os.path.join(os.getenv('TEMP', '.'), 'outputs')

# Maximum image size (5MB)
MAX_IMAGE_SIZE = 5 * 1024 * 1024

# Standard resolutions for scaling (from original repo)
MAX_SCALING_TARGETS: dict[str, dict[str, int]] = {
    "XGA": {"width": 1024, "height": 768},    # 4:3
    "WXGA": {"width": 1280, "height": 800},   # 16:10
    "FWXGA": {"width": 1366, "height": 768},  # ~16:9
}

Action = Literal[
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
]

class Resolution(TypedDict):
    width: int
    height: int

class ScalingSource(StrEnum):
    COMPUTER = "computer"
    API = "api"

class ComputerToolOptions(TypedDict):
    display_height_px: int
    display_width_px: int
    display_number: int | None

class CoordinateTranslator:
    """Handles coordinate translation between physical screen and API target space."""
    
    def __init__(self, dpi_scale: float, taskbar_offset: int, 
                 physical_width: int, physical_height: int,
                 target_width: int, target_height: int):
        self.dpi_scale = dpi_scale
        self.taskbar_offset = taskbar_offset
        self.physical_width = physical_width
        self.physical_height = physical_height
        self.target_width = target_width
        self.target_height = target_height
        
        # Calculate scaling factors
        self.x_scale = physical_width / target_width
        self.y_scale = physical_height / target_height
        
        logger.debug(f"Coordinate translator initialized:")
        logger.debug(f"DPI scale: {dpi_scale}")
        logger.debug(f"Taskbar offset: {taskbar_offset}")
        logger.debug(f"X scale: {self.x_scale}")
        logger.debug(f"Y scale: {self.y_scale}")
    
    def api_to_screen(self, x: int, y: int) -> tuple[int, int]:
        """Convert coordinates from API space to physical screen space."""
        screen_x = int(x * self.x_scale / self.dpi_scale)
        screen_y = int(y * self.y_scale / self.dpi_scale) + self.taskbar_offset
        return screen_x, screen_y
    
    def screen_to_api(self, x: int, y: int) -> tuple[int, int]:
        """Convert coordinates from physical screen space to API space."""
        api_x = int(x * self.dpi_scale / self.x_scale)
        api_y = int((y - self.taskbar_offset) * self.dpi_scale / self.y_scale)
        return api_x, api_y

def chunks(s: str, chunk_size: int) -> list[str]:
    return [s[i : i + chunk_size] for i in range(0, len(s), chunk_size)]

def get_windows_coordinate_system() -> tuple[float, float, float, float]:
    """Get Windows coordinate system information."""
    try:
        user32 = ctypes.windll.user32
        user32.SetProcessDPIAware()
        
        # Get physical screen metrics
        physical_width = user32.GetSystemMetrics(0)  # SM_CXSCREEN
        physical_height = user32.GetSystemMetrics(1)  # SM_CYSCREEN
        
        # Get virtual screen metrics
        virtual_width = user32.GetSystemMetrics(78)   # SM_CXVIRTUALSCREEN
        virtual_height = user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN
        virtual_x = user32.GetSystemMetrics(76)       # SM_XVIRTUALSCREEN
        virtual_y = user32.GetSystemMetrics(77)       # SM_YVIRTUALSCREEN
        
        # Get work area (screen minus taskbar)
        work_rect = ctypes.wintypes.RECT()
        user32.SystemParametersInfoW(48, 0, ctypes.byref(work_rect), 0)  # SPI_GETWORKAREA
        
        # Calculate scaling factors
        dpi = user32.GetDpiForSystem()
        dpi_scale = dpi / 96.0
        
        # Get primary monitor info
        monitor_info = ctypes.wintypes.MONITORINFO()
        monitor_info.cbSize = ctypes.sizeof(monitor_info)
        monitor_handle = user32.MonitorFromWindow(0, 2)  # MONITOR_DEFAULTTOPRIMARY
        user32.GetMonitorInfoW(monitor_handle, ctypes.byref(monitor_info))
        
        logger.debug(f"Physical screen: {physical_width}x{physical_height}")
        logger.debug(f"Virtual screen: {virtual_width}x{virtual_height} at ({virtual_x},{virtual_y})")
        logger.debug(f"Work area: {work_rect.right-work_rect.left}x{work_rect.bottom-work_rect.top}")
        logger.debug(f"DPI scale: {dpi_scale}")
        
        return (
            dpi_scale,
            work_rect.top,  # Taskbar offset
            monitor_info.rcMonitor.right - monitor_info.rcMonitor.left,  # Monitor width
            monitor_info.rcMonitor.bottom - monitor_info.rcMonitor.top   # Monitor height
        )
    except Exception as e:
        logger.error(f"Failed to get coordinate system: {e}")
        return 1.0, 0, pyautogui.size()[0], pyautogui.size()[1]

class IconDetector:
    """Handles icon detection and center-point calculation."""
    
    def __init__(self, min_size: int = 16, max_size: int = 64):
        self.min_size = min_size
        self.max_size = max_size
    
    def find_icon_center(self, screenshot: Image.Image, target_x: int, target_y: int) -> Optional[Tuple[int, int]]:
        """Find the actual center of an icon near the target coordinates."""
        # Convert PIL image to OpenCV format
        cv_image = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
        
        # Create region of interest around target point
        roi_size = self.max_size * 2
        x1 = max(0, target_x - roi_size)
        y1 = max(0, target_y - roi_size)
        x2 = min(screenshot.width, target_x + roi_size)
        y2 = min(screenshot.height, target_y + roi_size)
        
        roi = cv_image[y1:y2, x1:x2]
        
        # Convert to grayscale
        gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        
        # Find edges
        edges = cv2.Canny(gray, 50, 150)
        
        # Find contours
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        # Filter contours by size and find the closest to target
        best_center = None
        min_distance = 5.0 # 仅考虑5px以内的范围
        
        for contour in contours:
            # Get bounding box
            x, y, w, h = cv2.boundingRect(contour)
            
            # Check if size is in icon range
            if (self.min_size <= w <= self.max_size and 
                self.min_size <= h <= self.max_size):
                
                # Calculate center
                center_x = x1 + x + w//2
                center_y = y1 + y + h//2
                
                # Calculate distance to target
                distance = ((center_x - target_x) ** 2 + 
                          (center_y - target_y) ** 2) ** 0.5
                
                if distance < min_distance:
                    min_distance = distance
                    best_center = (center_x, center_y)
        
        if best_center:
            logger.debug(f"Found icon center at {best_center}, offset from target: {min_distance:.1f}px")
        else:
            logger.debug("No icon found, using original coordinates")
            
        return best_center

class ComputerTool(BaseAnthropicTool):
    """
    A tool that allows the agent to interact with the screen, keyboard, and mouse using PyAutoGUI.
    Uses smart icon detection for better clicking accuracy.
    """

    name: Literal["computer"] = "computer"
    api_type: Literal["computer_20241022"] = "computer_20241022"
    width: int
    height: int
    display_num: int | None
    target_width: int
    target_height: int

    _screenshot_delay = 2.0
    _scaling_enabled = True

    @property
    def options(self) -> ComputerToolOptions:
        # Always use target dimensions for API
        return {
            "display_width_px": self.target_width,
            "display_height_px": self.target_height,
            "display_number": self.display_num,
        }

    def to_params(self) -> BetaToolComputerUse20241022Param:
        return {"name": self.name, "type": self.api_type, **self.options}

    def __init__(self):
        super().__init__()
        
        # Get coordinate system information
        dpi_scale, taskbar_offset, physical_width, physical_height = get_windows_coordinate_system()
        
        # Find best matching target resolution
        aspect_ratio = physical_width / physical_height
        best_target = None
        best_ratio_diff = float('inf')
        
        for name, target in MAX_SCALING_TARGETS.items():
            target_ratio = target["width"] / target["height"]
            ratio_diff = abs(target_ratio - aspect_ratio)
            
            if ratio_diff < best_ratio_diff:
                best_ratio_diff = ratio_diff
                best_target = target
        
        self.target_width = best_target["width"]
        self.target_height = best_target["height"]
        
        # Initialize coordinate translator
        self.translator = CoordinateTranslator(
            dpi_scale=dpi_scale,
            taskbar_offset=taskbar_offset,
            physical_width=physical_width,
            physical_height=physical_height,
            target_width=self.target_width,
            target_height=self.target_height
        )
        
        # Initialize icon detector
        self.icon_detector = IconDetector()
        
        # Store dimensions
        self.width = physical_width
        self.height = physical_height
        self.display_num = None
        
        logger.info(f"Computer tool initialized:")
        logger.info(f"Physical: {self.width}x{self.height}")
        logger.info(f"Target: {self.target_width}x{self.target_height}")
        logger.info(f"DPI scale: {dpi_scale}")
        
        # Create output directory
        os.makedirs(OUTPUT_DIR, exist_ok=True)

    def scale_coordinates(self, source: ScalingSource, x: int, y: int) -> tuple[int, int]:
        """Convert coordinates between screen and API space."""
        if not self._scaling_enabled:
            return x, y
            
        if source == ScalingSource.API:
            return self.translator.api_to_screen(x, y)
        else:
            return self.translator.screen_to_api(x, y)

    async def smart_click(self, x: int, y: int, action: str) -> None:
        """Perform a smart click by finding icon center."""
        # Take quick screenshot for icon detection
        screenshot = pyautogui.screenshot()
        
        # Try to find icon center
        center = self.icon_detector.find_icon_center(screenshot, x, y)
        
        if center:
            # Use detected center
            click_x, click_y = center
            logger.debug(f"Using detected icon center: ({click_x}, {click_y})")
        else:
            # Fallback to original coordinates
            click_x, click_y = x, y
            logger.debug(f"Using original coordinates: ({click_x}, {click_y})")
        
        # Move to position
        pyautogui.moveTo(click_x, click_y)
        
        # Perform click action
        click_map = {
            "left_click": lambda: pyautogui.click(button='left'),
            "right_click": lambda: pyautogui.click(button='right'),
            "middle_click": lambda: pyautogui.click(button='middle'),
            "double_click": lambda: pyautogui.doubleClick(),
        }
        click_map[action]()

    async def __call__(
        self,
        *,
        action: Action,
        text: str | None = None,
        coordinate: tuple[int, int] | None = None,
        **kwargs,
    ) -> ToolResult:
        if action in ("mouse_move", "left_click_drag"):
            if coordinate is None:
                raise ToolError(f"coordinate is required for {action}")
            if text is not None:
                raise ToolError(f"text is not accepted for {action}")
            if not isinstance(coordinate, list) or len(coordinate) != 2:
                raise ToolError(f"{coordinate} must be a tuple of length 2")
            if not all(isinstance(i, int) and i >= 0 for i in coordinate):
                raise ToolError(f"{coordinate} must be a tuple of non-negative ints")

            # Scale coordinates from API to screen
            x, y = self.scale_coordinates(ScalingSource.API, coordinate[0], coordinate[1])
            logger.debug(f"Moving to coordinates: ({x}, {y})")

            if action == "mouse_move":
                pyautogui.moveTo(x, y)
                return await self.take_screenshot()
            elif action == "left_click_drag":
                pyautogui.dragTo(x, y, button='left')
                return await self.take_screenshot()

        if action in ("key", "type"):
            if text is None:
                raise ToolError(f"text is required for {action}")
            if coordinate is not None:
                raise ToolError(f"coordinate is not accepted for {action}")
            if not isinstance(text, str):
                raise ToolError(f"{text} must be a string")

            if action == "key":
                key_parts = text.split('+')
                if len(key_parts) > 1:
                    logger.debug(f"Pressing key combination: {key_parts}")
                    pyautogui.hotkey(*key_parts)
                else:
                    logger.debug(f"Pressing key: {text}")
                    pyautogui.press(text)
                return await self.take_screenshot()
            elif action == "type":
                results = []
                for chunk in chunks(text, TYPING_GROUP_SIZE):
                    logger.debug(f"Typing chunk: {chunk}")
                    if any('\u4e00' <= c <= '\u9fff' for c in chunk):
                        # Save original clipboard content
                        original_clipboard = pyperclip.paste()
                        # Use clipboard for typing Chinese characters
                        pyperclip.copy(chunk)
                        pyautogui.hotkey('ctrl', 'v')
                        # Restore original clipboard content
                        pyperclip.copy(original_clipboard)
                    else:
                        pyautogui.write(chunk, interval=TYPING_DELAY_MS/1000.0)
                    results.append(ToolResult(output=chunk))
                screenshot = await self.take_screenshot()
                return ToolResult(
                    output="".join(result.output or "" for result in results),
                    error="".join(result.error or "" for result in results),
                    base64_image=screenshot.base64_image,
                )

        if action in ("scroll_up", "scroll_down"):
            if text is not None:
                raise ToolError(f"text is not accepted for {action}")
            if coordinate is not None:
                raise ToolError(f"coordinate is not accepted for {action}")
            
            # 滚动方向和数量
            scroll_amount = 400 if action == "scroll_up" else -400
            logger.debug(f"Scrolling with amount: {scroll_amount}")
            pyautogui.scroll(scroll_amount)
            return await self.take_screenshot()

        if action in (
            "left_click",
            "right_click",
            "double_click",
            "middle_click",
            "screenshot",
            "cursor_position",
        ):
            if text is not None:
                raise ToolError(f"text is not accepted for {action}")

            if action == "screenshot":
                return await self.take_screenshot()
            elif action == "cursor_position":
                pos = pyautogui.position()
                api_x, api_y = self.scale_coordinates(ScalingSource.COMPUTER, pos.x, pos.y)
                return ToolResult(output=f"X={api_x},Y={api_y}")
            else:
                if coordinate is not None:
                    # Scale coordinates and use smart click
                    x, y = self.scale_coordinates(ScalingSource.API, coordinate[0], coordinate[1])
                    await self.smart_click(x, y, action)
                else:
                    # Click at current position
                    click_map = {
                        "left_click": lambda: pyautogui.click(button='left'),
                        "right_click": lambda: pyautogui.click(button='right'),
                        "middle_click": lambda: pyautogui.click(button='middle'),
                        "double_click": lambda: pyautogui.doubleClick(),
                    }
                    click_map[action]()
                
                return await self.take_screenshot()

        raise ToolError(f"Invalid action: {action}")

    async def take_screenshot(self) -> ToolResult:
        """Take a screenshot and return it as a base64 encoded string."""
        await asyncio.sleep(self._screenshot_delay)
        
        # Take screenshot using PyAutoGUI
        screenshot = pyautogui.screenshot()
        logger.debug(f"Original dimensions: {screenshot.width}x{screenshot.height}")
        
        # Scale to target resolution
        scaled_width, scaled_height = self.target_width, self.target_height
        logger.debug(f"Scaling to: {scaled_width}x{scaled_height}")
        
        scaled = screenshot.resize((scaled_width, scaled_height), Image.Resampling.LANCZOS)
        
        # Try PNG compression
        img_buffer = io.BytesIO()
        scaled.save(
            img_buffer,
            format='PNG',
            optimize=True,
            compress_level=9
        )
        
        img_buffer.seek(0)
        size = len(img_buffer.getvalue())
        logger.debug(f"Size after scaling: {size/1024/1024:.1f}MB")
        
        if size <= MAX_IMAGE_SIZE:
            return ToolResult(base64_image=base64.b64encode(img_buffer.getvalue()).decode())
        
        # If still too large, convert to grayscale
        logger.debug("Converting to grayscale")
        grayscale = scaled.convert('L')
        
        img_buffer = io.BytesIO()
        grayscale.save(
            img_buffer,
            format='PNG',
            optimize=True,
            compress_level=9
        )
        
        img_buffer.seek(0)
        size = len(img_buffer.getvalue())
        logger.debug(f"Size after grayscale: {size/1024/1024:.1f}MB")
        
        return ToolResult(base64_image=base64.b64encode(img_buffer.getvalue()).decode())
