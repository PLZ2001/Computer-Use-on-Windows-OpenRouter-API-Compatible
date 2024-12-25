"""简单的浏览器自动化工具"""

import base64
import json
from pathlib import Path
from typing import Optional, Dict, Any, List, Literal
from dataclasses import dataclass

from selenium import webdriver
from selenium.webdriver.edge.service import Service
from selenium.webdriver.edge.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from bs4 import BeautifulSoup

from .base import BaseTool, ToolResult, ToolFactory
from .exceptions import ToolError, ValidationError

@dataclass
class Link:
    """网页链接"""
    url: str
    text: str

@ToolFactory.register
class BrowserTool(BaseTool):
    """封闭的浏览器自动化工具，支持网页访问、内容获取和基本操作"""
    
    name: Literal["browser"] = "browser"

    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["visit", "get_content", "click", "back", "type"],
                "description": "要执行的操作: visit(打开一个网页), get_content(获取网页中的特定内容), click(点击按钮/链接等), back(返回上一个访问的页面), type(在搜索框/表单等处输入文字)"
            },
            "url": {
                "type": "string",
                "description": "要打开的网页地址，必须包含完整的网址(比如https://www.google.com)或本地文件路径(比如file:///C:/index.html)"
            },
            "selector": {
                "type": "string",
                "description": "用于定位要操作的元素的查找方式"
            },
            "input_text": {
                "type": "string",
                "description": "用于type操作时输入到表单字段的文本内容(搜索词、用户名等)"
            },
            "target_text": {
                "type": "string",
                "description": "用于click操作时通过显示文本定位要点击的元素"
            },
            "filter_text": {
                "type": "string",
                "description": "用于配合content_type、selector_type或text_type, 以筛选包含特定文本的内容(标题、段落、链接等)"
            },
            "content_type": {
                "type": "string",
                "enum": ["text", "title", "url", "clickable", "screenshot", "media"],
                "description": "要获取的内容类型: text(页面中的文字内容), title(网页标题), url(当前网页地址), clickable(可以点击的元素), screenshot(网页截图), media(图片/视频/音频)"
            },
            "selector_type": {
                "type": "string",
                "enum": ["a", "div", "custom"],
                "description": "指定要查找的HTML元素类型: a(链接), div(通用容器元素，常用于组织和布局页面内容，可能包含其他元素或作为可点击区域), custom(自定义元素)"
            },
            "selector_attrs": {
                "type": "object",
                "description": "用于进一步筛选元素的属性条件,支持class、role、aria-*等属性"
            },
            "text_type": {
                "type": "string",
                "enum": ["heading", "paragraph", "span"],
                "description": "要获取的具体文字类型: heading(大标题/小标题), paragraph(正文段落), span(行内文本)"
            }
        },
        "required": ["action"],
    }

    def __init__(self):
        super().__init__()
        self._driver: Optional[webdriver.Edge] = None
        self._wait: Optional[WebDriverWait] = None

    async def _ensure_browser(self) -> None:
        """确保浏览器已启动"""
        import streamlit as st
        
        # 如果session_state中有浏览器实例，使用它
        if hasattr(st, 'session_state') and 'browser_instance' in st.session_state:
            if st.session_state.browser_instance and st.session_state.browser_instance._driver:
                self._driver = st.session_state.browser_instance._driver
                self._wait = st.session_state.browser_instance._wait
                return
                
        # 否则创建新的浏览器实例
        if not self._driver:
            import json

            # 设置Edge WebDriver选项
            edge_options = Options()
            edge_options.use_chromium = True
            edge_options.add_argument('--disable-gpu')
            edge_options.add_argument('--no-sandbox')
            edge_options.add_argument('--remote-allow-origins=*')
            
            # 使用默认的Edge WebDriver
            service = Service()
            
            try:
                print("正在启动Edge浏览器...")
                self._driver = webdriver.Edge(service=service, options=edge_options)
                print("Edge WebDriver实例创建成功")
                self._wait = WebDriverWait(self._driver, 10)
                print("WebDriverWait实例创建成功")
                
                # 保存到session_state
                if hasattr(st, 'session_state'):
                    st.session_state.browser_instance = self
                
            except Exception as e:
                raise ToolError(f"启动Edge浏览器失败: {str(e)}")

    def _get_unique_selector(self, element, selector_type: str, selector_attrs: Optional[Dict] = None) -> Optional[str]:
        """获取指定类型元素的唯一选择器"""
        # 处理自定义元素
        if selector_type == 'custom' and selector_attrs:
            selectors = []
            for attr, value in selector_attrs.items():
                if attr == 'class':
                    # 处理class列表
                    classes = value.split() if isinstance(value, str) else value
                    selectors.extend(f".{cls}" for cls in classes)
                elif attr.startswith('aria-'):
                    # 处理aria属性
                    selectors.append(f"[{attr}='{value}']")
                elif attr == 'role':
                    # 处理role属性
                    selectors.append(f"[role='{value}']")
                else:
                    # 处理其他属性
                    selectors.append(f"[{attr}='{value}']")
            if selectors:
                return ''.join(selectors)
            return None
            
        # 处理常规元素
        if selector_type not in ['custom'] and element.name != selector_type:
            return None
            
        selectors = []
        
        # 优先使用id
        if element.get('id'):
            element_id = element['id'].replace("'", "\\'")
            return f"#{element_id}"
            
        # 处理class
        if element.get('class'):
            classes = ' '.join(element.get('class'))
            if classes:
                selectors.append(f".{classes.replace(' ', '.')}")
                
        # 处理role属性
        if element.get('role'):
            role = element['role'].replace("'", "\\'")
            selectors.append(f"[role='{role}']")
            
        # 根据元素类型使用特定属性
        if selector_type == 'a' and element.get('href'):
            from urllib.parse import urljoin
            href = element['href'].replace("'", "\\'")
            # 如果是相对链接，转换为绝对链接
            if self._driver and self._driver.current_url:
                href = urljoin(self._driver.current_url, href)
            selectors.append(f"[href='{href}']")
            
        # 添加用户指定的属性条件
        if selector_attrs:
            for attr, value in selector_attrs.items():
                if attr not in ['class', 'role'] and not attr.startswith('aria-'):
                    value = str(value).replace("'", "\\'")
                    selectors.append(f"[{attr}='{value}']")
                    
        # 如果有选择器，组合它们
        if selectors:
            return f"{selector_type if selector_type != 'custom' else '*'}{''.join(selectors)}"
            
        # 如果没有唯一属性，使用元素在DOM中的位置
        if element.parent:
            siblings = element.parent.find_all(selector_type, recursive=False)
            if len(siblings) > 1:
                index = len(list(element.find_previous_siblings(selector_type))) + 1
                return f"{selector_type}:nth-of-type({index})"
            
        # 如果只有一个此类型的元素，直接使用标签选择器
        return selector_type if selector_type != 'custom' else None

    def _find_clickable_element(self, selector: str) -> Optional[webdriver.remote.webelement.WebElement]:
        """查找可点击元素"""
        try:
            # 根据选择器类型确定定位器
            locator = (By.CSS_SELECTOR, selector)
            if selector.startswith('//'):
                locator = (By.XPATH, selector)
            
            # 尝试查找元素
            element = self._wait.until(EC.presence_of_element_located(locator))
            if element and not element.is_displayed():
                # 如果元素存在但不可见，尝试滚动到元素位置
                self._driver.execute_script("arguments[0].scrollIntoView(true);", element)
            return element if element and element.is_enabled() else None
                
        except Exception:
            return None

    def _get_page_content(self, content_type: str = None, selector_type: str = "text", selector_attrs: Optional[Dict] = None, text_type: str = "paragraph", text: Optional[str] = None) -> Dict[str, Any]:
        """获取页面内容"""
        if not self._driver:
            raise ToolError("浏览器未初始化")
            
        # 等待页面加载
        try:
            self._wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        except TimeoutException:
            pass  # 继续处理已加载的内容
        
        result = {'url': self._driver.current_url}
        
        try:
            # 获取页面内容
            # 获取包含Shadow DOM内容的完整HTML
            html = self._driver.execute_script("""
                function getShadowDOMContent(element) {
                    let content = element.innerHTML || '';
                    const shadowRoots = element.querySelectorAll('*');
                    for (const elem of shadowRoots) {
                        if (elem.shadowRoot) {
                            content += elem.shadowRoot.innerHTML;
                        }
                    }
                    return content;
                }
                return document.documentElement.outerHTML + getShadowDOMContent(document.documentElement);
            """)
            if not html:
                raise ToolError("无法获取页面内容")
        except Exception as e:
            raise ToolError(f"获取页面内容失败: {str(e)}")
            
        soup = BeautifulSoup(html, 'html.parser')

        if content_type == "text":
            # 移除脚本和样式
            for tag in soup(['script', 'style']):
                tag.decompose()
            
            # 根据text_type筛选内容
            text_parts = []
            if text_type == "heading":
                elements = soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
                if text:  # filter_text
                    elements = [e for e in elements if text.lower() in e.get_text().lower()]
            elif text_type == "paragraph":
                elements = soup.find_all('p')
                if text:  # filter_text
                    elements = [e for e in elements if text.lower() in e.get_text().lower()]
            elif text_type == "span":
                elements = soup.find_all('span')
                if text:  # filter_text
                    elements = [e for e in elements if text.lower() in e.get_text().lower()]
            
            for elem in elements:
                text = elem.get_text(strip=True)
                if text:  # 只添加非空文本
                    if text_type == "heading":
                        text_parts.append(f"{elem.name.upper()}: {text}")
                    else:
                        text_parts.append(text)
            
            result['text'] = '\n'.join(text_parts)
            
        elif content_type == "title":
            result['title'] = self._driver.title
            
        elif content_type == "url":
            result['url'] = self._driver.current_url
            
        elif content_type == "clickable":
            # 查找指定类型的元素
            clickable_elements = []
            
            # 处理自定义元素
            if selector_type == 'custom':
                if not selector_attrs:
                    raise ValidationError("使用custom selector_type时必须提供selector_attrs")
                    
                # 构建查找条件
                find_attrs = {}
                if 'class' in selector_attrs:
                    find_attrs['class_'] = selector_attrs['class'].split() if isinstance(selector_attrs['class'], str) else selector_attrs['class']
                for attr, value in selector_attrs.items():
                    if attr != 'class':
                        find_attrs[attr] = value
                        
                elements = soup.find_all(True, attrs=find_attrs)
            else:
                elements = soup.find_all(selector_type)
                
            # 如果提供了text参数，筛选包含该文本的元素
            if text:  # filter_text
                elements = [e for e in elements if text.lower() in e.get_text(strip=True).lower()]
            
            for element in elements:
                # 获取唯一选择器
                selector = self._get_unique_selector(
                    element, 
                    selector_type,
                    selector_attrs
                )
                
                if selector:  # 只添加有唯一选择器的元素
                    # 收集元素信息
                    element_info = {
                        'tag': element.name,
                        'text': element.get_text(strip=True) or '(无文本)',
                        'selector': selector,
                        'attributes': {
                            'class': element.get('class', []),
                            'role': element.get('role', ''),
                            'id': element.get('id', '')
                        }
                    }
                    
                    # 添加其他重要属性
                    for attr in ['aria-label', 'data-testid', 'title']:
                        if value := element.get(attr):
                            element_info['attributes'][attr] = value
                    
                    clickable_elements.append(element_info)
            result['clickable_elements'] = clickable_elements
            
        elif content_type == "screenshot":
            screenshot = self._driver.get_screenshot_as_png()
            result['screenshot'] = base64.b64encode(screenshot).decode()
            
        elif content_type == "media":
            media = {
                'images': [],
                'videos': [],
                'audio': []
            }
            # 收集图片信息
            images = soup.find_all('img')
            if text:  # filter_text
                images = [img for img in images if text.lower() in (img.get('alt', '').lower() or img.get('title', '').lower())]
            for img in images:
                img_info = {
                    'src': img.get('src', ''),
                    'alt': img.get('alt', ''),
                    'width': img.get('width', ''),
                    'height': img.get('height', '')
                }
                media['images'].append(img_info)
            
            # 收集视频信息    
            videos = soup.find_all(['video', 'iframe'])
            if text:  # filter_text
                videos = [v for v in videos if text.lower() in (v.get('title', '').lower() or v.get('aria-label', '').lower())]
            for video in videos:
                video_info = {
                    'src': video.get('src', ''),
                    'type': video.name,
                    'width': video.get('width', ''),
                    'height': video.get('height', '')
                }
                media['videos'].append(video_info)
                
            # 收集音频信息
            audios = soup.find_all('audio')
            if text:  # filter_text
                audios = [a for a in audios if text.lower() in (a.get('title', '').lower() or a.get('aria-label', '').lower())]
            for audio in audios:
                audio_info = {
                    'src': audio.get('src', ''),
                    'type': audio.get('type', '')
                }
                media['audio'].append(audio_info)
                
            result['media'] = media
            
        return result

    async def execute(self, **kwargs) -> ToolResult:
        """执行浏览器操作"""
        action = kwargs.get("action")
        if not action:
            raise ValidationError("未指定操作类型")

        try:
            await self._ensure_browser()

            if action == "visit":
                url = kwargs.get("url")
                if not url:
                    raise ValidationError("未指定URL")
                
                # 访问页面
                self._driver.get(url)
                title = self._driver.title
                result = ToolResult(output=f"已访问页面: {title}\nURL: {url}")
                return result

            elif action == "get_content":
                if not self._driver.current_url:
                    raise ToolError("浏览器未访问任何页面")
                
                content_type = kwargs.get("content_type")
                if not content_type:
                    raise ValidationError("get_content操作需要指定content_type参数")
                
                content = self._get_page_content(
                    content_type=content_type,
                    selector_type=kwargs.get("selector_type", "text"),
                    selector_attrs=kwargs.get('selector_attrs', {}),                    
                    text_type=kwargs.get("text_type", "paragraph"),
                    text=kwargs.get("filter_text")  # 传入filter_text参数用于内容筛选
                )
                
                if content_type == "text":
                    result = ToolResult(output=content['text'])
                    return result
                    
                elif content_type == "title":
                    result = ToolResult(output=content['title'])
                    return result
                    
                elif content_type == "url":
                    result = ToolResult(output=content['url'])
                    return result
                    
                elif content_type == "clickable":
                    elements = content['clickable_elements']
                    output = []
                    for i, elem in enumerate(elements, 1):
                        output.append(f"{i}. {elem['text']} ({elem['tag']})")
                        output.append(f"   选择器: {elem['selector']}")
                    result = ToolResult(output='\n'.join(output))
                    return result
                    
                elif content_type == "screenshot":
                    result = ToolResult(
                        output="页面截图",
                        base64_image=content['screenshot']
                    )
                    return result
                    
                elif content_type == "media":
                    media = content['media']
                    output = []
                    if media['images']:
                        output.append("图片:")
                        for img in media['images']:
                            output.append(f"  - {img['alt'] or '无描述'}")
                            output.append(f"    源: {img['src']}")
                            if img['width'] and img['height']:
                                output.append(f"    尺寸: {img['width']}x{img['height']}")
                    if media['videos']:
                        output.append("\n视频:")
                        for video in media['videos']:
                            output.append(f"  - 类型: {video['type']}")
                            output.append(f"    源: {video['src']}")
                            if video['width'] and video['height']:
                                output.append(f"    尺寸: {video['width']}x{video['height']}")
                    if media['audio']:
                        output.append("\n音频:")
                        for audio in media['audio']:
                            output.append(f"  - 类型: {audio['type']}")
                            output.append(f"    源: {audio['src']}")
                    result = ToolResult(output='\n'.join(output))
                    return result
                    
            elif action == "click":
                selector = kwargs.get("selector")
                text = kwargs.get("target_text")  # 获取target_text参数用于文本定位
                if not selector:
                    raise ValidationError("未指定要点击的元素选择器")
                
                # 如果是链接选择器，直接通过href属性匹配
                if selector.startswith('a') and '[href=' in selector:
                    try:
                        # 使用正则表达式提取href值
                        import re
                        from urllib.parse import urljoin
                        href_match = re.search(r"\[href='([^']+)'\]", selector)
                        href = href_match.group(1) if href_match else None
                        if href:
                            # 使用当前页面URL作为基础来解析相对链接
                            base_url = self._driver.current_url
                            absolute_url = urljoin(base_url, href)
                            self._driver.get(absolute_url)
                            title = self._driver.title
                            result = ToolResult(output=f"已跳转到: {title}\nURL: {href}")
                            return result
                    except TimeoutException:
                        raise ToolError(f"链接元素无效: {selector}")
                
                # 如果提供了text参数，在指定类型的元素中查找包含该文本的元素
                if text:
                    soup = BeautifulSoup(self._driver.page_source, 'html.parser')
                    selector_type = kwargs.get("selector_type")
                    selector_attrs = kwargs.get("selector_attrs", {})
                    
                    if not selector_type and not selector_attrs:
                        raise ValidationError("使用text参数时必须指定selector_type或selector_attrs")
                        
                    # 处理自定义元素
                    if selector_type == 'custom':
                        if not selector_attrs:
                            raise ValidationError("使用custom selector_type时必须提供selector_attrs")
                            
                        # 构建查找条件
                        find_attrs = {}
                        if 'class' in selector_attrs:
                            find_attrs['class_'] = selector_attrs['class'].split() if isinstance(selector_attrs['class'], str) else selector_attrs['class']
                        for attr, value in selector_attrs.items():
                            if attr != 'class':
                                find_attrs[attr] = value
                                
                        elements = soup.find_all(True, attrs=find_attrs)
                    else:
                        # 查找常规元素
                        elements = soup.find_all(selector_type)
                        
                    # 筛选包含文本的元素
                    elements = [e for e in elements if text.lower() in e.get_text(strip=True).lower()]
                    
                    if elements:
                        element = elements[0]
                        selector = self._get_unique_selector(
                            element, 
                            selector_type,
                            selector_attrs
                        )
                        if selector:
                            element = self._find_clickable_element(selector)
                        else:
                            raise ToolError(f"无法为包含文本'{text}'的元素生成唯一选择器")
                    else:
                        element_type = selector_type if selector_type != 'custom' else '自定义'
                        raise ToolError(f"未找到包含文本'{text}'的{element_type}元素")
                else:
                    # 使用原始选择器查找元素
                    element = self._find_clickable_element(selector)
                if not element:
                    raise ToolError(f"未找到可点击的元素: {selector}")
                
                element.click()
                title = self._driver.title
                result = ToolResult(output=f"点击后跳转到: {title}\nURL: {self._driver.current_url}")
                return result

            elif action == "type":
                selector = kwargs.get("selector")
                text = kwargs.get("input_text")
                if not selector:
                    raise ValidationError("未指定要输入文本的元素选择器")
                if not text:
                    raise ValidationError("未指定要输入的input_text内容")

                try:
                    element = self._wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
                    if not element:
                        raise ToolError(f"未找到文本输入框元素: {selector}")
                    
                    # 清除现有文本并输入新文本
                    element.clear()
                    element.send_keys(text)
                    result = ToolResult(output=f"已在元素 {selector} 中输入文本: {text}")
                    return result
                except TimeoutException:
                    raise ToolError(f"等待文本输入框元素超时: {selector}")
                except Exception as e:
                    raise ToolError(f"文本输入操作失败: {str(e)}")

            elif action == "back":
                if not self._driver.current_url:
                    raise ToolError("浏览器未访问任何页面")
                
                self._driver.back()
                title = self._driver.title
                result = ToolResult(output=f"返回到页面: {title}\nURL: {self._driver.current_url}")
                return result

            else:
                raise ValidationError(f"不支持的操作类型: {action}")

        except Exception as e:
            # 发生异常时不自动关闭浏览器，让用户可以查看状态
            raise ToolError(f"浏览器操作失败: {str(e)}")

    async def close(self, force: bool = False) -> None:
        """关闭浏览器
        
        Args:
            force: 是否强制关闭浏览器。如果为False，不做任何操作
        """
        if self._driver and force:
            self._driver.quit()
            self._driver = None

    async def validate_params(self, **kwargs) -> None:
        """验证参数"""
        action = kwargs.get("action")
        if not action:
            raise ValidationError("未指定操作类型")
        
        valid_actions = ["visit", "get_content", "click", "back", "type"]
        if action not in valid_actions:
            raise ValidationError(f"不支持的操作类型: {action}")

        # 定义每个action允许的参数
        allowed_params = {
            "visit": {"action", "url"},
            "get_content": {
                "action", "content_type", "selector_type", "selector_attrs", 
                "text_type", "filter_text"
            },
            "click": {
                "action", "selector", "target_text", "selector_type", 
                "selector_attrs"
            },
            "back": {"action"},
            "type": {"action", "selector", "input_text"}
        }

        # 检查是否存在不允许的参数
        provided_params = set(kwargs.keys())
        invalid_params = provided_params - allowed_params[action]
        if invalid_params:
            raise ValidationError(f"{action}操作不支持以下参数: {', '.join(invalid_params)}")

        # 验证action相关的必需参数和参数组合
        if action == "visit":
            if not kwargs.get("url"):
                raise ValidationError("visit操作需要指定url参数")
        
        elif action == "get_content":
            content_type = kwargs.get("content_type")
            if not content_type:
                raise ValidationError("get_content操作需要指定content_type参数")
                
            valid_content_types = ["text", "title", "url", "clickable", "screenshot", 
                                 "media"]
            if content_type not in valid_content_types:
                raise ValidationError(f"不支持的内容类型: {content_type}")
                
            # 验证content_type相关的参数组合
            if content_type == "text":
                text_type = kwargs.get("text_type")
                if not text_type:
                    raise ValidationError("content_type为text时必须指定text_type参数")
                    
                valid_text_types = ["heading", "paragraph", "span"]
                if text_type not in valid_text_types:
                    raise ValidationError(f"不支持的文本类型: {text_type}")
                    
                # text类型不应该有selector_type和selector_attrs
                if "selector_type" in kwargs or "selector_attrs" in kwargs:
                    raise ValidationError("content_type为text时不应指定selector_type或selector_attrs参数")
                    
            elif content_type == "clickable":
                selector_type = kwargs.get("selector_type")
                if not selector_type:
                    raise ValidationError("content_type为clickable时必须指定selector_type参数")
                    
                valid_selector_types = ["a", "div", "custom"]
                if selector_type not in valid_selector_types:
                    raise ValidationError(f"不支持的元素类型: {selector_type}")
                    
                # 验证selector_type相关的参数
                if selector_type == "custom":
                    if not kwargs.get("selector_attrs"):
                        raise ValidationError("selector_type为custom时必须提供selector_attrs参数")
                elif "selector_attrs" in kwargs:
                    raise ValidationError(f"selector_type为{selector_type}时不应提供selector_attrs参数")
                    
                # clickable类型不应该有text_type
                if "text_type" in kwargs:
                    raise ValidationError("content_type为clickable时不应指定text_type参数")
                    
            elif content_type in ["title", "url", "screenshot"]:
                # 这些类型不需要额外参数
                invalid_params = {"selector_type", "selector_attrs", "text_type"} & provided_params
                if invalid_params:
                    raise ValidationError(f"content_type为{content_type}时不应指定以下参数: {', '.join(invalid_params)}")
                    
        elif action == "click":
            # 验证click操作的两种互斥参数组合
            has_selector = "selector" in kwargs
            has_text_selector = "target_text" in kwargs and "selector_type" in kwargs
            
            if not has_selector and not has_text_selector:
                raise ValidationError("click操作需要指定selector参数或同时指定target_text和selector_type参数")
            if has_selector and has_text_selector:
                raise ValidationError("click操作不能同时指定selector和(target_text, selector_type)参数组合")
                
            if has_text_selector:
                selector_type = kwargs["selector_type"]
                valid_selector_types = ["a", "div", "custom"]
                if selector_type not in valid_selector_types:
                    raise ValidationError(f"不支持的元素类型: {selector_type}")
                    
                if selector_type == "custom":
                    if not kwargs.get("selector_attrs"):
                        raise ValidationError("selector_type为custom时必须提供selector_attrs参数")
                elif "selector_attrs" in kwargs:
                    raise ValidationError(f"selector_type为{selector_type}时不应提供selector_attrs参数")
                    
        elif action == "type":
            if not kwargs.get("selector"):
                raise ValidationError("type操作需要指定selector参数")
            if not kwargs.get("input_text"):
                raise ValidationError("type操作需要指定input_text参数")
