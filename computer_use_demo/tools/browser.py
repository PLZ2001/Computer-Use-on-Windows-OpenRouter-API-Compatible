"""简单的浏览器自动化工具"""

import base64
from typing import Optional, Dict, Any, List, Literal
from dataclasses import dataclass

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
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
    """简单的浏览器自动化工具，支持网页访问、内容获取和基本操作"""
    
    name: Literal["browser"] = "browser"

    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["visit", "get_content", "click", "back"],
                "description": "浏览器操作类型: visit(访问URL), get_content(获取页面内容), click(点击元素), back(返回上一页)"
            },
            "url": {
                "type": "string",
                "description": "要访问的URL"
            },
            "selector": {
                "type": "string",
                "description": "要点击的元素的CSS选择器"
            },
            "content_type": {
                "type": "string",
                "enum": ["text", "title", "clickable", "screenshot"],
                "description": "获取内容的类型: text(文本), title(标题), clickable(可点击元素及其选择器), screenshot(截图)"
            },
            "selector_type": {
                "type": "string",
                "enum": ["text", "id", "class", "tag", "position"],
                "description": "当content_type为clickable时使用，指定要获取的选择器类型: text(文本内容), id(ID属性), class(class属性), tag(标签属性), position(位置)"
            },
            "text_type": {
                "type": "string",
                "enum": ["all", "heading", "paragraph", "list", "link"],
                "description": "当content_type为text时使用，指定要获取的文本类型: all(所有文本), heading(标题), paragraph(段落), list(列表), link(链接)"
            }
        },
        "required": ["action"]
    }

    def __init__(self):
        super().__init__()
        self._driver: Optional[webdriver.Chrome] = None
        self._wait: Optional[WebDriverWait] = None

    async def _ensure_browser(self) -> None:
        """确保浏览器已启动"""
        if not self._driver:
            chrome_options = Options()
            chrome_options.add_argument('--no-sandbox')
            chrome_options.add_argument('--disable-dev-shm-usage')
            chrome_options.add_argument('--disable-gpu')
            chrome_options.add_argument('--disable-setuid-sandbox')
            chrome_options.add_argument('--headless=new')
            chrome_options.add_argument('--window-size=1280,800')
            
            self._driver = webdriver.Chrome(options=chrome_options)
            self._wait = WebDriverWait(self._driver, 10)

    def _get_element_selector(self, element, selector_type: str) -> Optional[str]:
        """根据指定类型获取元素选择器"""
        tag_name = element.name
        
        if selector_type == "text":
            text = element.get_text(strip=True)
            if text:
                # 对于链接和按钮，使用特定标签的文本选择器
                if tag_name in ['a', 'button']:
                    return f"//{tag_name}[contains(text(), '{text}')]"
                # 对于其他元素，使用通用文本选择器
                return f"//*[contains(text(), '{text}')]"
                
        elif selector_type == "id":
            if element.get('id'):
                return f"#{element['id']}"
                
        elif selector_type == "class":
            if element.get('class'):
                return f".{' .'.join(element['class'])}"
                
        elif selector_type == "tag":
            # 根据标签类型返回不同的属性选择器
            if tag_name == 'a' and element.get('href'):
                return f"a[href='{element['href']}']"
            elif tag_name == 'button' and element.get('type'):
                return f"button[type='{element['type']}']"
            elif tag_name == 'input':
                selectors = []
                if element.get('name'):
                    selectors.append(f"name='{element['name']}'")
                if element.get('type'):
                    selectors.append(f"type='{element['type']}'")
                if selectors:
                    return f"input[{' and '.join(selectors)}]"
                
        elif selector_type == "position":
            if element.parent:
                siblings = element.parent.find_all(tag_name, recursive=False)
                if len(siblings) == 1:
                    return f"{element.parent.name} > {tag_name}"
                else:
                    index = len(list(element.find_previous_siblings(tag_name))) + 1
                    return f"{element.parent.name} > {tag_name}:nth-of-type({index})"
                    
        return None

    def _find_clickable_element(self, selector: str) -> Optional[webdriver.remote.webelement.WebElement]:
        """尝试多种方式查找可点击元素"""
        try:
            # 1. 直接CSS选择器
            element = self._wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
            if element:
                return element
        except:
            pass

        try:
            # 2. XPath选择器
            if selector.startswith('/'):
                element = self._wait.until(EC.element_to_be_clickable((By.XPATH, selector)))
                if element:
                    return element
        except:
            pass

        try:
            # 3. 链接文本
            element = self._wait.until(EC.element_to_be_clickable((By.LINK_TEXT, selector)))
            if element:
                return element
        except:
            pass

        try:
            # 4. 部分链接文本
            element = self._wait.until(EC.element_to_be_clickable((By.PARTIAL_LINK_TEXT, selector)))
            if element:
                return element
        except:
            pass

        return None

    def _get_page_content(self, content_type: str = None, selector_type: str = "text", text_type: str = "all") -> Dict[str, Any]:
        """获取页面内容"""
        # 等待页面加载
        try:
            self._wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        except TimeoutException:
            pass  # 继续处理已加载的内容
        
        result = {'url': self._driver.current_url}
        
        # 获取页面内容
        html = self._driver.page_source
        soup = BeautifulSoup(html, 'html.parser')

        if content_type == "text":
            # 移除脚本和样式
            for tag in soup(['script', 'style']):
                tag.decompose()
            
            # 根据text_type筛选内容
            if text_type == "all":
                result['text'] = soup.get_text(separator='\n', strip=True)
            else:
                text_parts = []
                if text_type == "heading":
                    elements = soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
                elif text_type == "paragraph":
                    elements = soup.find_all('p')
                elif text_type == "list":
                    elements = []
                    for list_tag in soup.find_all(['ul', 'ol']):
                        elements.extend(list_tag.find_all('li'))
                elif text_type == "link":
                    elements = soup.find_all('a')
                
                for elem in elements:
                    text = elem.get_text(strip=True)
                    if text:  # 只添加非空文本
                        if text_type == "heading":
                            text_parts.append(f"{elem.name.upper()}: {text}")
                        elif text_type == "link":
                            href = elem.get('href', '')
                            if href:
                                text_parts.append(f"{text} -> {href}")
                            else:
                                text_parts.append(text)
                        else:
                            text_parts.append(text)
                
                result['text'] = '\n'.join(text_parts)
            
        elif content_type == "title":
            result['title'] = self._driver.title
            
        elif content_type == "clickable":
            # 提取可点击元素
            clickable_elements = []
            for element in soup.find_all(['a', 'button', 'input', 'select']):
                # 获取选择器
                selector = self._get_element_selector(element, selector_type)
                
                if selector:  # 只添加有选择器的元素
                    # 收集元素信息
                    element_info = {
                        'tag': element.name,
                        'text': element.get_text(strip=True) or '(无文本)',
                        'selector': selector
                    }
                
                # 针对不同类型元素收集特定属性
                if element.name == 'a' and element.get('href'):
                    url = element['href']
                    if url.startswith('/'):
                        url = f"{self._driver.current_url.rstrip('/')}{url}"
                    elif url.startswith(('http://', 'https://')):
                        element_info['url'] = url
                elif element.name == 'button':
                    element_info['type'] = element.get('type', 'button')
                elif element.name == 'input':
                    element_info['type'] = element.get('type', 'text')
                
                clickable_elements.append(element_info)
            result['clickable_elements'] = clickable_elements
            
        elif content_type == "screenshot":
            screenshot = self._driver.get_screenshot_as_png()
            result['screenshot'] = base64.b64encode(screenshot).decode()
            
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
                
                self._driver.get(url)
                title = self._driver.title
                return ToolResult(output=f"已访问页面: {title}\nURL: {url}")

            elif action == "get_content":
                if not self._driver.current_url:
                    raise ToolError("浏览器未访问任何页面")
                
                content_type = kwargs.get("content_type")
                if not content_type:
                    raise ValidationError("get_content操作需要指定content_type参数")
                
                content = self._get_page_content(
                    content_type=content_type,
                    selector_type=kwargs.get("selector_type", "text"),
                    text_type=kwargs.get("text_type", "all")
                )
                
                if content_type == "text":
                    return ToolResult(output=content['text'])
                    
                elif content_type == "title":
                    return ToolResult(output=content['title'])
                    
                elif content_type == "clickable":
                    elements = content['clickable_elements']
                    output = []
                    for i, elem in enumerate(elements, 1):
                        output.append(f"{i}. {elem['text']} ({elem['tag']})")
                        output.append(f"   选择器: {elem['selector']}")
                        if 'url' in elem:
                            output.append(f"   链接: {elem['url']}")
                    return ToolResult(output='\n'.join(output))
                    
                elif content_type == "screenshot":
                    return ToolResult(
                        output="页面截图",
                        base64_image=content['screenshot']
                    )

            elif action == "click":
                selector = kwargs.get("selector")
                if not selector:
                    raise ValidationError("未指定要点击的元素选择器")
                
                element = self._find_clickable_element(selector)
                if not element:
                    raise ToolError(f"未找到可点击的元素: {selector}")
                
                element.click()
                title = self._driver.title
                return ToolResult(output=f"点击后跳转到: {title}\nURL: {self._driver.current_url}")

            elif action == "back":
                if not self._driver.current_url:
                    raise ToolError("浏览器未访问任何页面")
                
                self._driver.back()
                title = self._driver.title
                return ToolResult(output=f"返回到页面: {title}\nURL: {self._driver.current_url}")

            else:
                raise ValidationError(f"不支持的操作类型: {action}")

        except Exception as e:
            if self._driver:
                self._driver.quit()
                self._driver = None
            raise ToolError(f"浏览器操作失败: {str(e)}")

    async def close(self) -> None:
        """关闭浏览器"""
        if self._driver:
            self._driver.quit()
            self._driver = None

    async def validate_params(self, **kwargs) -> None:
        """验证参数"""
        action = kwargs.get("action")
        if not action:
            raise ValidationError("未指定操作类型")
        
        valid_actions = ["visit", "get_content", "click", "back"]
        if action not in valid_actions:
            raise ValidationError(f"不支持的操作类型: {action}")

        if action == "visit":
            if not kwargs.get("url"):
                raise ValidationError("visit操作需要指定url参数")
        
        elif action == "get_content":
            if not kwargs.get("content_type"):
                raise ValidationError("get_content操作需要指定content_type参数")
            content_type = kwargs.get("content_type")
            if content_type not in ["text", "title", "clickable", "screenshot"]:
                raise ValidationError("不支持的内容类型")
            if content_type == "clickable":
                selector_type = kwargs.get("selector_type")
                if selector_type and selector_type not in ["text", "id", "class", "tag", "position"]:
                    raise ValidationError("不支持的选择器类型")
            elif content_type == "text":
                text_type = kwargs.get("text_type")
                if text_type and text_type not in ["all", "heading", "paragraph", "list", "link"]:
                    raise ValidationError("不支持的文本类型")
        elif action == "click":
            if not kwargs.get("selector"):
                raise ValidationError("click操作需要指定selector参数")
