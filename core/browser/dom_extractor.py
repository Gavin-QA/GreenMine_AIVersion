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
                // a. 原生可交互与多媒体/内嵌标签
                const tag = el.tagName.toLowerCase();
                const isNativeInteractive = ['button', 'a', 'input', 'select', 'textarea', 'li', 'img', 'svg', 'video', 'iframe'].includes(tag);
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
                    
                    // 如果本身没有文字，且不是 input，可能是一个纯图标，尽量尝试获取 aria-label, title, alt 或 class
                    let cls = (typeof el.className === 'string' ? el.className : el.getAttribute('class')) || '';
                    const lowerCls = cls.toLowerCase();
                    const isModalCloseBtn = lowerCls.includes('teleportbox-close') || lowerCls.includes('dialog__close') || lowerCls.includes('modal-close') || lowerCls.includes('dialog__headerbtn');

                    if (isModalCloseBtn) {
                        text = '弹窗右上角关闭按钮❌ (class_teleportbox-close)';
                    } else if (tag === 'video') {
                        const playStatus = el.paused ? '暂停中' : '播放中';
                        const cur = Math.floor(el.currentTime || 0);
                        const dur = Math.floor(el.duration || 0);
                        text = '视频播放区域 (' + playStatus + (dur > 0 ? ' ' + cur + 's/' + dur + 's' : '') + ')';
                    } else if (tag === 'iframe') {
                        text = el.getAttribute('title') || '内嵌文档/图纸查看视窗 (iframe)';
                    } else if (!text && !['input', 'textarea'].includes(tag)) {
                        let clsHint = cls.trim() ? 'class_' + cls.trim().split(/\\s+/).join('_') : 'icon_or_empty';
                        let altText = el.getAttribute('alt');
                        text = el.getAttribute('title') || (altText && altText.trim() !== '' ? altText : null) || clsHint;
                        
                        // 对于 img 标签，如果还是 icon_or_empty，提取它的 src 文件名作为强力线索
                        if (tag === 'img' && text === 'icon_or_empty' && el.src) {
                            if (el.src.startsWith('data:')) {
                                text = 'img_data_uri';
                            } else {
                                try {
                                    let url = new URL(el.src);
                                    let filename = url.pathname.split('/').pop();
                                    if (filename) {
                                        text = 'img_' + decodeURIComponent(filename);
                                    }
                                } catch (e) {}
                            }
                        }
                    }
                    
                    // 3. 推断组件类型与语义角色 (Component Awareness)
                    let isInteractiveCandidate = isPointer || isNativeInteractive || hasClickRole || hasOnClick || isModalCloseBtn;
                    let componentType = isInteractiveCandidate ? 'clickable' : 'text_display';
                    if (isModalCloseBtn) {
                        componentType = 'button';
                    } else if (tag === 'video') {
                        componentType = 'video';
                    } else if (tag === 'iframe') {
                        componentType = 'iframe';
                    } else if (el.closest('.el-pagination')) {
                        componentType = 'pagination';
                    } else if (el.closest('.el-carousel')) {
                        componentType = 'carousel';
                    } else if (tag === 'input') {
                        const inputType = (el.getAttribute('type') || 'text').toLowerCase();
                        if (inputType === 'checkbox') componentType = 'checkbox';
                        else if (inputType === 'radio') componentType = 'radio';
                        else componentType = 'input';
                    } else if (tag === 'textarea') {
                        componentType = 'input';
                    } else if (tag === 'select' || el.closest('.el-select, .ant-select, [role="combobox"]')) {
                        componentType = 'select';
                    } else if (tag === 'button' || el.getAttribute('role') === 'button') {
                        componentType = 'button';
                    } else if (el.getAttribute('role') === 'tab' || (typeof el.className === 'string' && el.className.includes('tabs__item'))) {
                        componentType = 'tab';
                    } else if (tag === 'canvas' || tag === 'svg') {
                        componentType = 'canvas_or_map';
                    }

                    // 4. 向上推断父容器上下文 (Container Context)
                    let containerName = null;
                    let containerType = null;

                    const modalEl = el.closest('.el-dialog, .el-drawer, .ant-modal, .ant-drawer, [role="dialog"], .modal, .class_teleportbox, [class*="teleportbox"], [class*="teleport"]');
                    if (modalEl) {
                        containerType = 'modal';
                        const titleEl = modalEl.querySelector('.el-dialog__title, .ant-modal-title, .modal-title, [class*="header"] [class*="title"], h3, h4');
                        if (titleEl && titleEl.innerText) {
                            containerName = titleEl.innerText.trim();
                        } else if (modalEl.className && (modalEl.className.includes('teleportbox') || modalEl.className.includes('teleport'))) {
                            containerName = '模态弹窗预览窗口';
                        }
                    } else if (el.closest('.el-carousel')) {
                        containerType = 'carousel';
                        containerName = '走马灯轮播看板';
                    } else if (el.closest('.el-pagination')) {
                        containerType = 'pagination';
                        containerName = '列表分页翻页器';
                    } else {
                        const tableEl = el.closest('table, .el-table, .ant-table, [role="grid"]');
                        if (tableEl) {
                            containerType = 'table';
                            // 尝试找到表格前面的标题或卡片头
                            const cardEl = tableEl.closest('.el-card, [class*="card"], [class*="panel"], [class*="box"]');
                            if (cardEl) {
                                const cardHeader = cardEl.querySelector('[class*="header"], [class*="title"]');
                                if (cardHeader && cardHeader.innerText) {
                                    containerName = cardHeader.innerText.trim().slice(0, 30);
                                }
                            }
                        }
                    }

                    results.push({
                        id: index++,
                        tag: tag,
                        text: text,
                        component_type: componentType,
                        container_name: containerName,
                        container_type: containerType,
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

    def detect_visible_modals(self) -> List[Dict[str, Any]]:
        """
        检测页面当前是否存在可见的弹窗、模态框或抽屉组件 (Zero-Token DOM 检测)。
        """
        self.get_active_page()
        if not self.page or self.page.is_closed():
            return []

        js_code = """
        () => {
            const selectors = [
                '.el-dialog:not([style*="display: none"])',
                '.el-dialog__wrapper:not([style*="display: none"])',
                '.el-drawer:not([style*="display: none"])',
                '.ant-modal:not(.ant-modal-hidden)',
                '.ant-drawer:not(.ant-drawer-hidden)',
                '[role="dialog"]:not([style*="display: none"])',
                '.modal.show',
                '.modal:not([style*="display: none"])',
                '.class_teleportbox:not([style*="display: none"])',
                '[class*="teleportbox"]:not([style*="display: none"])',
                '[class*="mailing"]:not([style*="display: none"])',
                '[class*="ai-dialog"]:not([style*="display: none"])'
            ];
            
            const modals = [];
            for (const selector of selectors) {
                const elements = document.querySelectorAll(selector);
                for (const el of elements) {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    if (rect.width > 50 && rect.height > 50 && 
                        style.display !== 'none' && 
                        style.visibility !== 'hidden' && 
                        style.opacity !== '0') {
                        
                        // 提取标题
                        const titleEl = el.querySelector('.el-dialog__title, .ant-modal-title, .modal-title, [class*="title"], h3, h4');
                        let title = titleEl && titleEl.innerText ? titleEl.innerText.trim() : '';
                        
                        // 如果没有直接标题，查找第一个有意义的文字
                        if (!title) {
                            const headerEl = el.querySelector('.el-dialog__header, .ant-modal-header, [class*="header"]');
                            if (headerEl && headerEl.innerText) {
                                title = headerEl.innerText.trim().split('\\n')[0];
                            }
                        }

                        // 针对迈灵/智能助手定制弹窗补充语义标题
                        const classStr = typeof el.className === 'string' ? el.className : '';
                        if (classStr.includes('teleportbox') || classStr.includes('mailing') || classStr.includes('ai-dialog')) {
                            if (!title || title === '未知弹窗') {
                                title = '“迈灵”AI助手对话框';
                            }
                        }
                        
                        modals.push({
                            title: title || '未知弹窗',
                            rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height }
                        });
                    }
                }
            }
            return modals;
        }
        """
        try:
            return self.page.evaluate(js_code)
        except Exception as e:
            logger.warning(f"检测可见弹窗失败: {e}")
            return []


