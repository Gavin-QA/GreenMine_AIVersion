import base64
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Generator, Optional, Tuple
from playwright.sync_api import BrowserContext, Page

logger = logging.getLogger("core.browser")

class DomExtractorMixin:
    def extract_interactive_elements(self) -> List[Dict[str, Any]]:
        """
        [Hybrid Mode] 提取视口内所有可见可交互元素的文本与几何包围盒 (BoundingRect)。
        用于 Midscene 风格的精确 DOM 匹配。
        """
        self.get_active_page()
        if not self.page or self.page.is_closed():
            return []

        js_code = """
        () => {
            // 获取所有元素，通过通用规则和样式来过滤可交互元素
            const elements = document.querySelectorAll('*');
            const results = [];
            let index = 0;
            
            for (const el of elements) {
                // 1. 基础过滤：排除不可见或在屏幕外的元素
                const rect = el.getBoundingClientRect();
                if (rect.width <= 0 || rect.height <= 0 || rect.bottom <= 0 || rect.right <= 0 || 
                    rect.top >= window.innerHeight || rect.left >= window.innerWidth) {
                    continue;
                }
                
                // 1.5 深度遮挡检测 (Z-index / Modal 弹窗蒙版检测)
                // 取元素的中心点，判断该点最上层的 DOM 元素是谁
                const centerX = rect.x + rect.width / 2;
                const centerY = rect.y + rect.height / 2;
                const topEl = document.elementFromPoint(centerX, centerY);
                
                // 如果中心点最上层的元素不是自己，且不是自己的子元素（比如按钮里面的文字/图标），
                // 则说明该元素被弹窗蒙版、悬浮层或别的组件彻底遮挡了，不可交互。
                if (topEl && topEl !== el && !el.contains(topEl)) {
                    continue;
                }
                
                // 2. 交互性判断：
                // a. 原生可交互标签
                const tag = el.tagName.toLowerCase();
                const isNativeInteractive = ['button', 'a', 'input', 'select', 'textarea', 'li'].includes(tag);
                // b. 具有可点击角色或属性
                const hasClickRole = ['button', 'menuitem', 'tab', 'link', 'option', 'listbox', 'treeitem'].includes(el.getAttribute('role'));
                const hasOnClick = el.hasAttribute('onclick');
                // c. Vue/React 单页面应用常用做法：普通的 div/span 加上 cursor: pointer
                const style = window.getComputedStyle(el);
                const isPointer = style.cursor === 'pointer';
                // d. 包含直接文本的节点（很多大屏开发者会把普通的 div/span 当做按钮，且忘了加 cursor: pointer）
                const hasDirectText = Array.from(el.childNodes).some(node => node.nodeType === Node.TEXT_NODE && node.textContent.trim().length > 0);
                
                if (isNativeInteractive || hasClickRole || hasOnClick || isPointer || hasDirectText) {
                    // 获取可读文本或标签
                    let text = el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || '';
                    text = String(text).trim().replace(/\\n/g, ' ').slice(0, 50);
                    
                    // 如果本身没有文字，且不是 input，可能是一个纯图标，尽量尝试获取 aria-label
                    if (!text && !['input', 'textarea'].includes(tag)) {
                        text = el.getAttribute('title') || 'icon_or_empty';
                    }
                    
                    results.push({
                        id: index++,
                        tag: tag,
                        text: text,
                        rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height }
                    });
                }
            }
            return results;
        }
        """
        try:
            return self.page.evaluate(js_code)
        except Exception as e:
            logger.warning(f"获取页面可交互元素失败，自动回退到纯视觉模式: {e}")
            return []


