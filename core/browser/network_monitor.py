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
    @staticmethod
    def is_benign_noise(msg_text: str = "", url: str = "", status: int = 0) -> bool:
        """
        判断捕获到的控制台/页面/网络异常是否属于已知的非阻塞性良性背景噪音
        返回 True 表示忽略过滤，False 表示确属真实异常
        """
        lower_msg = (msg_text or "").lower()
        lower_url = (url or "").lower()
        
        # 1. 静态资源与媒体文件缺失 (404/403)
        static_exts = ('.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.woff', '.woff2', '.ttf', '.eot', '.mp4', '.webm')
        if any(lower_url.endswith(ext) or (ext + '?') in lower_url for ext in static_exts):
            return True
        if "failed to load resource" in lower_msg and any(ext in lower_msg for ext in static_exts):
            return True

        # 2. 视频监控 / 摄像头离线推流报错 (flv/rtmp/live2/504)
        video_keywords = ("live2", "flv", "stream=", "stream", "hls", "m3u8", "1935", "loader error", "transmuxingcontroller", "iocontroller")
        if any(k in lower_url for k in video_keywords) or any(k in lower_msg for k in video_keywords):
            return True

        # 3. 外部第三方地图/SDK Token 鉴权失败 (如 Cesium Ion 401)
        if "cesium" in lower_url or "cesium" in lower_msg or "access_token" in lower_url:
            return True

        # 4. 本地 WebSocket 心跳重连
        if "wsconverter" in lower_url or "wsconverter" in lower_msg or "websocket" in lower_msg:
            return True

        # 5. 前端混淆代码中的自发性背景轮询定时器异常 (与用户交互无关)
        noise_err_patterns = [
            "httputils_error bo",
            "cannot set properties of undefined (setting 'config')",
            "failed to load resource: the server responded with a status of 401",
            "failed to load resource: the server responded with a status of 504"
        ]
        if any(p in lower_msg for p in noise_err_patterns):
            return True
            
        # 单独的混淆小词 (如 'Bo', 'iR', 'Uq', 'Event')
        clean_msg = (msg_text or "").strip()
        if clean_msg in ("Bo", "iR", "Uq", "Event", "[object Event]"):
            return True

        return False

    def _setup_page_listeners(self):
        """挂载控制台日志与异常捕获"""
        if not self.page or self.page.is_closed():
            return
            
        def on_console(msg):
            if msg.type == "error":
                if NetworkMonitorMixin.is_benign_noise(msg_text=msg.text):
                    logger.debug(f"[Electron Console Filtered (Noise)] {msg.text}")
                    return
                logger.warning(f"[Electron Console Error] {msg.text}")
                self.caught_bugs.append({"type": "console_error", "msg": msg.text})
            else:
                logger.debug(f"[Electron Console][{msg.type}] {msg.text}")

        def on_pageerror(err):
            err_str = str(err)
            if NetworkMonitorMixin.is_benign_noise(msg_text=err_str):
                logger.debug(f"[Electron PageError Filtered (Noise)] {err_str}")
                return
            logger.warning(f"[Electron PageError] {err_str}")
            self.caught_bugs.append({"type": "page_error", "msg": err_str})

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
                if NetworkMonitorMixin.is_benign_noise(url=response.url, status=response.status):
                    return
                # 记录真正的业务接口异常 (HTTP 4xx/5xx)
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

    @staticmethod
    def extract_search_tokens(query_text: str) -> List[str]:
        """通用文本特征提取器（Zero-Hardcoding，提取强特征编码、数值、百分比及业务实体）"""
        if not query_text:
            return []
        import re
        tokens = set()
        stop_phrases = {
            "验证", "当前", "悬浮", "显示", "后台", "接口", "返回", "原始", "数据", "是否",
            "一致", "信息", "包括", "列表", "区域", "卡片", "点击", "悬停", "核验", "指令",
            "如图", "截图中", "中的", "一个", "展示", "用户", "系统", "与", "和", "或", "等",
            "进行", "对应", "数值", "详情", "内容", "状态", "类型", "名称", "编号", "json", "null", "true", "false",
            "弹出", "浮层", "悬浮框", "框中", "测试", "检查", "页面", "右侧", "左侧", "顶部", "底部"
        }

        # 1. 括号/引号内的强实体 (如 ‘矿用液压锚杆台车’, 【采掘设备】, "G230324004")
        quoted = re.findall(r'[\'\"‘“【（\(]([^\'\"’”】）\)]+)[\'\"’”】）\)]', query_text)
        for q in quoted:
            q_clean = q.strip()
            if len(q_clean) >= 2 and q_clean not in stop_phrases:
                tokens.add(q_clean)

        # 2. 字母数字混合编码与业务ID (如 G230324004, ZW00101, FCB-1.5, KCG240201, 鄂PZZR02)
        plate_or_codes = re.findall(r'[\u4e00-\u9fa5]?[A-Za-z0-9_\-\.]{3,}', query_text)
        for c in plate_or_codes:
            if c.lower() not in stop_phrases and any(ch.isdigit() for ch in c):
                tokens.add(c)

        # 3. 数值与百分比指标 (如 89%, 59.5%, 1450)
        metrics = re.findall(r'\d+(?:\.\d+)?%?', query_text)
        for m in metrics:
            if len(m) > 1 or (m.isdigit() and int(m) > 0):
                tokens.add(m)

        # 4. 按标点符号切分出的业务短语
        clauses = re.split(r'[,，。！？、\s（）()“”"\'‘【】\[\]\-_：:‘’’“”]+', query_text)
        for clause in clauses:
            clause = clause.strip()
            if len(clause) < 2:
                continue
            cleaned = clause
            for sp in stop_phrases:
                if cleaned.startswith(sp):
                    cleaned = cleaned[len(sp):].strip()
                if cleaned.endswith(sp):
                    cleaned = cleaned[:-len(sp)].strip()
            if len(cleaned) >= 2 and cleaned not in stop_phrases:
                tokens.add(cleaned)

        filtered = []
        for t in sorted(list(tokens), key=len, reverse=True):
            if t not in stop_phrases:
                filtered.append(t)
        return filtered

    @staticmethod
    def score_record(record: dict, tokens: List[str]) -> Tuple[float, List[str]]:
        """计算接口报文与特征 Token 的倒排匹配度得分"""
        import json
        import re
        data_str = json.dumps(record.get("data", {}), ensure_ascii=False)
        url_str = record.get("url", "").lower()
        score = 0.0
        matched = []

        for token in tokens:
            token_matched = False
            is_code = bool(re.search(r'[A-Za-z]', token) and re.search(r'\d', token))
            is_metric = bool(re.search(r'\d', token) and not re.search(r'[A-Za-z]', token))

            if token in data_str:
                token_matched = True
                if is_code:
                    score += 60.0
                elif is_metric:
                    score += 25.0
                else:
                    score += 30.0
            elif is_metric and token.endswith("%") and token[:-1] in data_str:
                token_matched = True
                score += 20.0

            if token.lower() in url_str:
                score += 15.0
                token_matched = True

            if token_matched:
                matched.append(token)

        return round(score, 2), matched

    @classmethod
    def compress_record_data(cls, data: Any, matched_tokens: List[str], max_list_items: int = 4) -> Any:
        """结构自适应智能脱敏与压缩（保留命中记录、样本记录，折叠海量冗余项，剥离超长 base64/SVG）"""
        import json
        if isinstance(data, dict):
            compressed = {}
            for k, v in data.items():
                if isinstance(v, str):
                    if len(v) > 400 and ("base64," in v or v.startswith("data:")):
                        compressed[k] = f"<Base64 Data Omitted, len={len(v)}>"
                        continue
                    if len(v) > 800:
                        compressed[k] = v[:150] + f"... <Omitted {len(v)-150} chars>"
                        continue
                compressed[k] = cls.compress_record_data(v, matched_tokens, max_list_items)
            return compressed
        elif isinstance(data, list):
            if len(data) <= max_list_items:
                return [cls.compress_record_data(item, matched_tokens, max_list_items) for item in data]

            matched_indices = []
            for idx, item in enumerate(data):
                item_str = json.dumps(item, ensure_ascii=False)
                if any(t in item_str for t in matched_tokens):
                    matched_indices.append(idx)

            keep_indices = set([0, len(data) - 1])
            if len(data) > 1:
                keep_indices.add(1)
            keep_indices.update(matched_indices)
            sorted_keep = sorted(list(keep_indices))

            result = []
            last_idx = -1
            for idx in sorted_keep:
                if idx > last_idx + 1:
                    result.append({"_omitted_records_count": idx - last_idx - 1})
                result.append(cls.compress_record_data(data[idx], matched_tokens, max_list_items))
                last_idx = idx
            if last_idx < len(data) - 1:
                result.append({"_omitted_records_count": len(data) - 1 - last_idx})
            return result
        else:
            return data

    def get_focused_api_records_summary(self, query_text: str = "", max_records: int = 3, max_total_chars: int = 14000) -> str:
        """
        通用两阶段接口检索：通过倒排索引与结构自适应压缩，精准返回与测试目标最相关的核心接口报文。
        彻底杜绝张冠李戴与全局暴力截断。
        """
        if not self.api_records:
            return "[]"

        import json
        tokens = self.extract_search_tokens(query_text) if query_text else []
        recent_records = self.api_records[-30:]

        scored_records = []
        for r in recent_records:
            score, matched = self.score_record(r, tokens)
            scored_records.append((score, matched, r))

        scored_records.sort(key=lambda x: x[0], reverse=True)

        selected_candidates = []
        direct_hit = False

        if scored_records and scored_records[0][0] > 0:
            direct_hit = True
            for score, matched, r in scored_records:
                if score > 0 and len(selected_candidates) < max_records:
                    selected_candidates.append((score, matched, r))
            hit_info = ", ".join([f"'{r['url']}'(得分:{s}, 命中:{m})" for s, m, r in selected_candidates])
            logger.info(f"🎯 [Auto-API Inverted Index] 倒排索引命中核心候选接口: {hit_info}")
        else:
            # 未直接命中特征 Token 时，回退选取最近的核心业务接口
            logger.info(f"ℹ️ [Auto-API Inverted Index] 未直接命中特征Token，回退加载最近 {max_records} 个业务接口供全量核验。")
            for r in recent_records[-max_records:]:
                selected_candidates.append((0.0, [], r))

        # 压缩报文
        compressed_apis = []
        for score, matched, r in selected_candidates:
            compressed_apis.append({
                "url": r.get("url"),
                "relevance_score": score,
                "matched_tokens": matched,
                "data": self.compress_record_data(r.get("data"), matched)
            })

        output_struct = {
            "_retrieval_meta": {
                "query": query_text,
                "extracted_tokens": tokens,
                "direct_hit": direct_hit,
                "candidate_urls": [c["url"] for c in compressed_apis]
            },
            "candidate_apis": compressed_apis
        }

        summary = json.dumps(output_struct, ensure_ascii=False, indent=2)
        if len(summary) > max_total_chars:
            summary = summary[:max_total_chars] + "\n...[Truncated, JSON exceeded character limit]"
        return summary

    def get_api_records_summary(self, query_text: str = "") -> str:
        """返回核心 JSON 数据（向前兼容，自动支持带 query 的动态聚焦检索）"""
        return self.get_focused_api_records_summary(query_text=query_text)

    def get_and_clear_bugs(self) -> list:
        """获取并清空后台捕获到的所有异常报错"""
        bugs = list(self.caught_bugs)
        self.caught_bugs = []
        return bugs


