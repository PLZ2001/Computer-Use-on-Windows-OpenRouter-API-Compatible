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
                "description": "浏览器操作类型: visit(访问URL), get_content(获取页面内容), click(点击元素), back(返回上一页), type(在文本框中输入文本)"
            },
            "url": {
                "type": "string",
                "description": "要访问的URL"
            },
            "selector": {
                "type": "string",
                "description": "要点击或输入文本的元素的CSS选择器"
            },
            "text": {
                "type": "string",
                "description": "要输入的文本内容"
            },
            "content_type": {
                "type": "string",
                "enum": ["text", "title", "clickable", "screenshot", "structure", "form", "media", "element_state", "dynamic"],
                "description": "获取内容的类型: text(文本), title(标题), clickable(可点击元素及其选择器), screenshot(截图), structure(页面结构), form(表单), media(媒体), element_state(元素状态), dynamic(动态内容)"
            },
            "selector_type": {
                "type": "string",
                "enum": ["text", "id", "class", "tag", "position"],
                "description": "当content_type为clickable时使用，指定要获取的选择器类型: text(文本内容), id(ID属性), class(class属性), tag(标签属性), position(位置)"
            },
            "text_type": {
                "type": "string",
                "enum": ["heading", "paragraph", "list", "link", "table", "code", "quote", "comment", "button", "label", "placeholder", "message"],
                "description": "当content_type为text时使用，指定要获取的文本类型: heading(标题), paragraph(段落), list(列表), link(链接), table(表格), code(代码), quote(引用), comment(注释), button(按钮), label(标签), placeholder(占位符), message(提示信息)"
            }
        },
        "required": ["action"]
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

    def _get_page_content(self, content_type: str = None, selector_type: str = "text", text_type: str = "paragraph") -> Dict[str, Any]:
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
            elif text_type == "table":
                elements = []
                # 处理表格内容
                tables = soup.find_all('table')
                for table in tables:
                    # 获取表头
                    headers = [th.get_text(strip=True) for th in table.find_all('th')]
                    if headers:
                        text_parts.append("表头: " + " | ".join(headers))
                    # 获取数据行
                    for row in table.find_all('tr'):
                        cells = [td.get_text(strip=True) for td in row.find_all('td')]
                        if cells:
                            text_parts.append("数据: " + " | ".join(cells))
            elif text_type == "code":
                elements = soup.find_all(['code', 'pre'])
            elif text_type == "quote":
                elements = soup.find_all(['blockquote', 'q', 'cite'])
            elif text_type == "comment":
                elements = []
                # 获取HTML注释
                from bs4.element import Comment
                comments = soup.find_all(string=lambda text: isinstance(text, Comment))
                for comment in comments:
                    text_parts.append(f"注释: {comment.strip()}")
            elif text_type == "button":
                elements = soup.find_all(['button', 'input[type="button"]', 'input[type="submit"]'])
            elif text_type == "label":
                elements = soup.find_all('label')
            elif text_type == "placeholder":
                elements = []
                # 处理占位符文本
                for input_elem in soup.find_all(['input', 'textarea']):
                    if placeholder := input_elem.get('placeholder'):
                        text_parts.append(f"占位符: {placeholder}")
            elif text_type == "message":
                # 查找常见的消息容器
                elements = soup.find_all(class_=lambda x: x and any(c in str(x).lower() for c in 
                    ['message', 'alert', 'notification', 'toast', 'error', 'warning', 'success', 'info']))
            
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
                    elif text_type == "code":
                        text_parts.append(f"代码:\n{text}")
                    elif text_type == "quote":
                        text_parts.append(f"引用: {text}")
                    elif text_type == "button":
                        text_parts.append(f"按钮: {text}")
                    elif text_type == "label":
                        for_id = elem.get('for', '')
                        if for_id:
                            text_parts.append(f"标签[{for_id}]: {text}")
                        else:
                            text_parts.append(f"标签: {text}")
                    elif text_type == "message":
                        classes = elem.get('class', [])
                        msg_type = next((c for c in classes if any(t in c.lower() for t in 
                            ['error', 'warning', 'success', 'info'])), 'message')
                        text_parts.append(f"{msg_type}: {text}")
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
            
        elif content_type == "structure":
            # 提取页面的DOM结构
            structure = {
                'main': [],
                'navigation': [],
                'sidebar': [],
                'footer': []
            }
            
            # 提取主要内容
            main = soup.find('main') or soup.find(id='main') or soup.find(class_='main')
            if main:
                structure['main'] = [elem.get_text(strip=True) for elem in main.find_all(['h1', 'h2', 'h3', 'p'])]
                
            # 提取导航
            nav = soup.find('nav') or soup.find(id='nav') or soup.find(class_='nav')
            if nav:
                structure['navigation'] = [{'text': a.get_text(strip=True), 'href': a.get('href')} 
                                        for a in nav.find_all('a')]
                
            # 提取侧边栏
            sidebar = soup.find(id='sidebar') or soup.find(class_='sidebar')
            if sidebar:
                structure['sidebar'] = [elem.get_text(strip=True) for elem in sidebar.find_all(['h3', 'h4', 'p'])]
                
            # 提取页脚
            footer = soup.find('footer') or soup.find(id='footer') or soup.find(class_='footer')
            if footer:
                structure['footer'] = [elem.get_text(strip=True) for elem in footer.find_all(['p', 'a'])]
                
            result['structure'] = structure
            
        elif content_type == "form":
            forms = []
            for form in soup.find_all('form'):
                form_data = {
                    'id': form.get('id', ''),
                    'action': form.get('action', ''),
                    'method': form.get('method', 'get'),
                    'fields': []
                }
                for field in form.find_all(['input', 'select', 'textarea']):
                    field_info = {
                        'type': field.get('type', 'text'),
                        'name': field.get('name', ''),
                        'id': field.get('id', ''),
                        'required': field.has_attr('required'),
                        'value': field.get('value', ''),
                        'placeholder': field.get('placeholder', '')
                    }
                    form_data['fields'].append(field_info)
                forms.append(form_data)
            result['forms'] = forms
            
        elif content_type == "media":
            media = {
                'images': [],
                'videos': [],
                'audio': []
            }
            # 收集图片信息
            for img in soup.find_all('img'):
                img_info = {
                    'src': img.get('src', ''),
                    'alt': img.get('alt', ''),
                    'width': img.get('width', ''),
                    'height': img.get('height', '')
                }
                media['images'].append(img_info)
            
            # 收集视频信息    
            for video in soup.find_all(['video', 'iframe']):
                video_info = {
                    'src': video.get('src', ''),
                    'type': video.name,
                    'width': video.get('width', ''),
                    'height': video.get('height', '')
                }
                media['videos'].append(video_info)
                
            # 收集音频信息
            for audio in soup.find_all('audio'):
                audio_info = {
                    'src': audio.get('src', ''),
                    'type': audio.get('type', '')
                }
                media['audio'].append(audio_info)
                
            result['media'] = media
            
        elif content_type == "element_state":
            element_states = []
            for element in soup.find_all(['button', 'input', 'a']):
                selector = self._get_element_selector(element, selector_type)
                if selector:
                    try:
                        web_element = self._driver.find_element(By.CSS_SELECTOR, selector)
                        state = {
                            'selector': selector,
                            'visible': web_element.is_displayed(),
                            'enabled': web_element.is_enabled(),
                            'selected': web_element.is_selected() if web_element.get_attribute('type') in ['checkbox', 'radio'] else None,
                            'classes': web_element.get_attribute('class'),
                            'attributes': {
                                attr: web_element.get_attribute(attr)
                                for attr in ['disabled', 'readonly', 'aria-hidden']
                            }
                        }
                        element_states.append(state)
                    except:
                        continue
            result['element_states'] = element_states
            
        elif content_type == "dynamic":
            # 等待动态内容加载
            try:
                # 等待页面不再有网络请求
                self._wait.until(
                    lambda driver: driver.execute_script('return jQuery.active == 0')
                )
                # 等待页面加载完成
                self._wait.until(
                    lambda driver: driver.execute_script('return document.readyState') == 'complete'
                )
            except:
                pass # 继续处理已加载的内容
            
            # 获取动态加载的内容
            dynamic_content = {
                'ajax_content': self._driver.execute_script(
                    'return window.ajaxResponses || []'
                ),
                'dom_changes': self._driver.execute_script(
                    'return window.domChanges || []'
                )
            }
            result['dynamic'] = dynamic_content
            
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
                    text_type=kwargs.get("text_type", "paragraph")
                )
                
                if content_type == "text":
                    result = ToolResult(output=content['text'])
                    return result
                    
                elif content_type == "title":
                    result = ToolResult(output=content['title'])
                    return result
                    
                elif content_type == "clickable":
                    elements = content['clickable_elements']
                    output = []
                    for i, elem in enumerate(elements, 1):
                        output.append(f"{i}. {elem['text']} ({elem['tag']})")
                        output.append(f"   选择器: {elem['selector']}")
                        if 'url' in elem:
                            output.append(f"   链接: {elem['url']}")
                    result = ToolResult(output='\n'.join(output))
                    return result
                    
                elif content_type == "screenshot":
                    result = ToolResult(
                        output="页面截图",
                        base64_image=content['screenshot']
                    )
                    return result
                    
                elif content_type == "structure":
                    structure = content['structure']
                    output = []
                    if structure['main']:
                        output.append("主要内容:")
                        output.extend(f"  {text}" for text in structure['main'])
                    if structure['navigation']:
                        output.append("\n导航:")
                        output.extend(f"  {link['text']} -> {link['href']}" for link in structure['navigation'])
                    if structure['sidebar']:
                        output.append("\n侧边栏:")
                        output.extend(f"  {text}" for text in structure['sidebar'])
                    if structure['footer']:
                        output.append("\n页脚:")
                        output.extend(f"  {text}" for text in structure['footer'])
                    result = ToolResult(output='\n'.join(output))
                    return result
                    
                elif content_type == "form":
                    forms = content['forms']
                    output = []
                    for i, form in enumerate(forms, 1):
                        output.append(f"表单 {i}:")
                        output.append(f"  ID: {form['id']}")
                        output.append(f"  Action: {form['action']}")
                        output.append(f"  Method: {form['method']}")
                        output.append("  字段:")
                        for field in form['fields']:
                            output.append(f"    - {field['name']} ({field['type']})")
                            if field['required']:
                                output.append("      必填")
                            if field['placeholder']:
                                output.append(f"      提示: {field['placeholder']}")
                    result = ToolResult(output='\n'.join(output))
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
                    
                elif content_type == "element_state":
                    states = content['element_states']
                    output = []
                    for i, state in enumerate(states, 1):
                        output.append(f"元素 {i}:")
                        output.append(f"  选择器: {state['selector']}")
                        output.append(f"  可见: {'是' if state['visible'] else '否'}")
                        output.append(f"  启用: {'是' if state['enabled'] else '否'}")
                        if state['selected'] is not None:
                            output.append(f"  选中: {'是' if state['selected'] else '否'}")
                        if state['classes']:
                            output.append(f"  类: {state['classes']}")
                        for attr, value in state['attributes'].items():
                            if value:
                                output.append(f"  {attr}: {value}")
                    result = ToolResult(output='\n'.join(output))
                    return result
                    
                elif content_type == "dynamic":
                    dynamic = content['dynamic']
                    output = []
                    if dynamic['ajax_content']:
                        output.append("AJAX响应:")
                        for resp in dynamic['ajax_content']:
                            output.append(f"  {resp}")
                    if dynamic['dom_changes']:
                        output.append("\nDOM变更:")
                        for change in dynamic['dom_changes']:
                            output.append(f"  {change}")
                    result = ToolResult(output='\n'.join(output) if output else "未检测到动态内容")
                    return result

            elif action == "click":
                selector = kwargs.get("selector")
                if not selector:
                    raise ValidationError("未指定要点击的元素选择器")
                
                element = self._find_clickable_element(selector)
                if not element:
                    raise ToolError(f"未找到可点击的元素: {selector}")
                
                element.click()
                title = self._driver.title
                result = ToolResult(output=f"点击后跳转到: {title}\nURL: {self._driver.current_url}")
                return result

            elif action == "type":
                selector = kwargs.get("selector")
                text = kwargs.get("text")
                if not selector:
                    raise ValidationError("未指定要输入文本的元素选择器")
                if not text:
                    raise ValidationError("未指定要输入的文本内容")

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

        if action == "visit":
            if not kwargs.get("url"):
                raise ValidationError("visit操作需要指定url参数")
        
        elif action == "get_content":
            if not kwargs.get("content_type"):
                raise ValidationError("get_content操作需要指定content_type参数")
            content_type = kwargs.get("content_type")
            if content_type not in ["text", "title", "clickable", "screenshot", "structure", "form", "media", "element_state", "dynamic"]:
                raise ValidationError("不支持的内容类型")
            if content_type == "clickable":
                selector_type = kwargs.get("selector_type")
                if selector_type and selector_type not in ["text", "id", "class", "tag", "position"]:
                    raise ValidationError("不支持的选择器类型")
            elif content_type == "text":
                text_type = kwargs.get("text_type")
                if text_type and text_type not in ["heading", "paragraph", "list", "link", "table", "code", "quote", "comment", "button", "label", "placeholder", "message"]:
                    raise ValidationError("不支持的文本类型")
        elif action == "click":
            if not kwargs.get("selector"):
                raise ValidationError("click操作需要指定selector参数")
        elif action == "type":
            if not kwargs.get("selector"):
                raise ValidationError("type操作需要指定selector参数")
            if not kwargs.get("text"):
                raise ValidationError("type操作需要指定text参数")
