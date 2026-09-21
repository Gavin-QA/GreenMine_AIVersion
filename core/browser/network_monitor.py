import base64
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Generator, Optional, Tuple
from playwright.sync_api import BrowserContext, Page

logger = logging.getLogger("core.browser")

class NetworkMonitorMixin:
    def _setup_page_listeners(self):
        """挂载控制台日志与异常捕获"""
        if not self.page or self.page.is_closed():
            return
            
        def on_console(msg):
            if msg.type == "error":
                logger.debug(f"[Electron Console Error] {msg.text}")
                self.caught_bugs.append({"type": "console_error", "msg": msg.text})
            else:
                logger.debug(f"[Electron Console][{msg.type}] {msg.text}")

        def on_pageerror(err):
            logger.warning(f"[Electron PageError] {err}")
            self.caught_bugs.append({"type": "page_error", "msg": str(err)})

        try:
            self.page.on("console", on_console)
            self.page.on("pageerror", on_pageerror)
        except Exception:
            pass

    def _setup_network_listeners(self):
        """挂载底层 HTTP API 拦截器"""
        if not self.page or self.page.is_closed():
            return
            
        def handle_response(response):
            if response.request.method == "OPTIONS":
                return
                
            if response.status >= 400:
                self.caught_bugs.append({"type": "network_error", "url": response.url, "status": response.status})
                return
                
            if response.status == 200 and "application/json" in response.headers.get("content-type", ""):
                try:
                    data = response.json()
                    # 避免拦截巨大的无用报文或非业务接口
                    if data:
                        url_path = response.url.split("?")[0].split("/")[-1]
                        if len(url_path) < 2:
                            url_path = response.url.split("?")[0]
                        self.api_records.append({
                            "url": url_path,
                            "data": data
                        })
                except Exception:
                    pass
        
        self.page.on("response", handle_response)
        
    def clear_api_records(self):
        """清空缓存的网络接口记录，开始新的生命周期抓取"""
        self.api_records = []
        
    def get_api_records_summary(self) -> str:
        """返回最近拦截到的核心 JSON 数据（为了节约 Token，转为紧凑字符串）"""
        if not self.api_records:
            return "[]"
        import json
        # 缩小滑动窗口至最近 20 个接口，防止过度堆积
        recent_records = self.api_records[-20:]
        summary = json.dumps(recent_records, ensure_ascii=False)
        # 终极防御：硬截断超大 JSON 字符串，防止大模型报 400 (Token 爆炸)
        if len(summary) > 12000:
            summary = summary[:12000] + "\n...[Truncated, JSON string exceeded 12000 chars]"
        return summary

    def get_and_clear_bugs(self) -> list:
        """获取并清空后台捕获到的所有异常报错"""
        bugs = list(self.caught_bugs)
        self.caught_bugs = []
        return bugs

