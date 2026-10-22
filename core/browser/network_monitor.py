import base64
import json
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
                loc_info = None
                loc_url = ""
                try:
                    loc = msg.location
                    if loc and loc.get("url"):
                        loc_url = loc["url"]
                        loc_clean = loc_url.split("?")[0].split("/")[-1]
                        line_no = loc.get("lineNumber", 0)
                        if loc_clean:
                            loc_info = f"{loc_clean}:{line_no}"
                except Exception:
                    pass

                if NetworkMonitorMixin.is_benign_noise(msg_text=msg.text, url=loc_url):
                    logger.debug(f"[Electron Console Filtered (Noise)] {msg.text} (loc: {loc_url})")
                    return
                logger.warning(f"[Electron Console Error] {msg.text}")

                bug_entry = {
                    "type": "console_error",
                    "msg": msg.text,
                    "location": loc_info
                }
                self.caught_bugs.append(bug_entry)
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

    def mark_action_timestamp(self):
        """记录当前交互动作（点击/悬停）的发生时间戳，供识别动作触发的新网络请求 (Delta-Capture)"""
        self.last_action_timestamp = time.time()
        logger.debug(f"⏱️ [Auto-API Delta] 记录动作触发时间戳: {self.last_action_timestamp:.3f}")

    def set_page_scope(self, scope_name: Optional[str] = None):
        """
        设置当前页面/路由的作用域（如 '首页 -> 证照管理'、'智控管理 -> 智能通风'）。
        后续拦截到的非全局接口将优先关联至该页面作用域，彻底杜绝跨页面历史旧接口串扰。
        """
        old_scope = getattr(self, "current_page_scope", "_global_shared")
        if not scope_name:
            self.current_page_scope = "_global_shared"
        else:
            self.current_page_scope = str(scope_name).strip()

        if self.current_page_scope != old_scope:
            self.scope_entry_time = time.time()
            logger.debug(f"🌐 [Auto-API Scope] 当前接口作用域已切换至: '{self.current_page_scope}' (重置页面进入时间戳)")

        if not hasattr(self, "page_scoped_registry") or self.page_scoped_registry is None:
            self.page_scoped_registry = {"_global_shared": {}}
        if not hasattr(self, "page_init_registry") or self.page_init_registry is None:
            self.page_init_registry = {"_global_shared": {}}

        if self.current_page_scope not in self.page_scoped_registry:
            self.page_scoped_registry[self.current_page_scope] = {}
        if self.current_page_scope not in self.page_init_registry:
            self.page_init_registry[self.current_page_scope] = {}

    def get_page_scope(self) -> str:
        """获取当前激活的页面作用域"""
        return getattr(self, "current_page_scope", "_global_shared")

    def _setup_network_listeners(self):
        """挂载底层 HTTP API 拦截器（维护多页面作用域隔离的 API 注册表与防暴洪时序流水）"""
        if not self.page or self.page.is_closed():
            return

        if not hasattr(self, "api_registry") or self.api_registry is None:
            self.api_registry = {}
        if not hasattr(self, "page_scoped_registry") or self.page_scoped_registry is None:
            self.page_scoped_registry = {"_global_shared": {}}
        if not hasattr(self, "page_init_registry") or self.page_init_registry is None:
            self.page_init_registry = {"_global_shared": {}}
        if not hasattr(self, "current_page_scope"):
            self.current_page_scope = "_global_shared"
        if not hasattr(self, "scope_entry_time"):
            self.scope_entry_time = time.time()
        if not hasattr(self, "last_action_timestamp"):
            self.last_action_timestamp = 0.0
            
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
                    lower_url = response.url.lower()
                    # 过滤 GIS / 瓦片 / 地图等静态配置 JSON，避免挤占业务接口打分与候选席位
                    gis_keywords = (
                        "approximateterrainheights", "layer.json", "tileset.json",
                        "/cesium/", "/terrain/", "/geoserver/", "defaultlayers.json"
                    )
                    if any(k in lower_url for k in gis_keywords):
                        return

                    data = response.json()
                    # 避免拦截巨大的无用报文或非业务接口
                    if data:
                        url_clean = response.url.split("?")[0]
                        endpoint_name = url_clean.split("/")[-1]
                        if len(endpoint_name) < 2:
                            endpoint_name = url_clean

                        active_scope = getattr(self, "current_page_scope", "_global_shared")
                        now_ts = time.time()
                        prev_hit = self.api_registry.get(endpoint_name, {}).get("hit_count", 0)
                        hit_count = prev_hit + 1

                        # 场景 1 核心支持：进入页面的前 15 秒捕获的数据接口，认定为页面初始化底座接口 (Page-Init)
                        elapsed_since_entry = now_ts - getattr(self, "scope_entry_time", now_ts)
                        is_page_init = elapsed_since_entry <= 15.0

                        # 高频轮询识别：若同一个接口在当前作用域被反复调用 3 次以上，标记为轮询 (is_polling)
                        is_polling = (hit_count >= 3)

                        record = {
                            "url": endpoint_name,
                            "full_url": url_clean,
                            "data": data,
                            "timestamp": now_ts,
                            "scope": active_scope,
                            "hit_count": hit_count,
                            "is_page_init": is_page_init,
                            "is_polling": is_polling
                        }

                        # 核心黑科技 1：检测 HTTP 200 里的业务异常 (code != 0/200, 比如权限不足、系统内部错误)
                        if isinstance(data, dict):
                            code = data.get("code") if "code" in data else data.get("status")
                            msg_val = str(data.get("msg") or data.get("message") or "")
                            
                            # 判定业务逻辑报错 (code 非 0/200，或者 msg 明确包含权限不足/失败等)
                            biz_err_codes = (7, 401, 403, 500, -1, "7", "401", "403", "500", "-1")
                            is_biz_err = False
                            if code in biz_err_codes:
                                is_biz_err = True
                            elif code not in (None, 0, 200, "0", "200") and msg_val and any(k in msg_val for k in ["权限", "失败", "异常", "错误", "未登录", "拒绝", "无权"]):
                                is_biz_err = True

                            if is_biz_err:
                                logger.warning(f"🚨 [Auto-API] 捕获到底层业务接口异常: {endpoint_name} -> code: {code}, msg: '{msg_val}'")
                                self.caught_bugs.append({
                                    "type": "api_biz_error",
                                    "url": url_clean,
                                    "endpoint": endpoint_name,
                                    "status": response.status,
                                    "biz_code": code,
                                    "msg": f"接口业务报错: {msg_val or f'code={code}'}",
                                    "response": data
                                })

                        # 1. 全局扁平注册表（便于跨页面全局查找与快速定位）
                        self.api_registry[endpoint_name] = record

                        # 2. 页面作用域隔离注册表（严格按二级页面隔离，彻底杜绝跨页面历史旧接口串扰）
                        if not hasattr(self, "page_scoped_registry") or self.page_scoped_registry is None:
                            self.page_scoped_registry = {"_global_shared": {}}
                        if active_scope not in self.page_scoped_registry:
                            self.page_scoped_registry[active_scope] = {}
                        self.page_scoped_registry[active_scope][endpoint_name] = record

                        # 3. 页面底座持久化注册表（场景1保障：Canvas 初始数据永久在位，不被轮询冲刷）
                        if is_page_init:
                            if not hasattr(self, "page_init_registry") or self.page_init_registry is None:
                                self.page_init_registry = {"_global_shared": {}}
                            if active_scope not in self.page_init_registry:
                                self.page_init_registry[active_scope] = {}
                            self.page_init_registry[active_scope][endpoint_name] = record

                        # 4. 时序流水记录（带防高频轮询暴洪：若与上一条是相同接口，则就地更新）
                        if self.api_records and self.api_records[-1].get("url") == endpoint_name:
                            self.api_records[-1] = record
                        else:
                            self.api_records.append(record)
                            if len(self.api_records) > 200:
                                self.api_records = self.api_records[-200:]
                except Exception:
                    pass
        
        self.page.on("response", handle_response)
        
    def clear_api_records(self):
        """清空缓存的网络接口记录与全局/页面作用域注册表，开始新的生命周期抓取"""
        self.api_records = []
        self.api_registry = {}
        self.page_scoped_registry = {"_global_shared": {}}
        self.page_init_registry = {"_global_shared": {}}
        self.current_page_scope = "_global_shared"
        self.scope_entry_time = time.time()
        self.last_action_timestamp = 0.0

    def get_all_registered_endpoints(self) -> List[str]:
        """获取当前生命周期内捕获到的所有唯一业务接口名称列表"""
        if not hasattr(self, "api_registry") or not self.api_registry:
            return []
        return sorted(list(self.api_registry.keys()))

    def get_api_by_name(self, api_name: str) -> Optional[dict]:
        """按接口名称精准获取最新报文数据（支持大小写模糊容错）"""
        if not hasattr(self, "api_registry") or not self.api_registry:
            return None
        if api_name in self.api_registry:
            return self.api_registry[api_name]
        lower_name = api_name.lower()
        for k, v in self.api_registry.items():
            if k.lower() == lower_name:
                return v
        return None

    def dump_api_registry(self, save_path: Optional[str] = None) -> str:
        """
        将当前捕获到的全部业务接口最新快照导出为结构化 JSON 文件（含按二级页面隔离的结构树），供人类查阅与断言诊断。
        返回导出文件的绝对路径。
        """
        import json
        if not hasattr(self, "api_registry") or not self.api_registry:
            self.api_registry = {}
        if not hasattr(self, "page_scoped_registry") or not self.page_scoped_registry:
            self.page_scoped_registry = {"_global_shared": {}}

        if not save_path:
            save_path = os.path.abspath("api_registry.json")
        save_file = Path(save_path).resolve()
        save_file.parent.mkdir(parents=True, exist_ok=True)

        dump_data = {
            "summary": {
                "total_unique_endpoints": len(self.api_registry),
                "total_page_scopes": len(self.page_scoped_registry),
                "current_scope": getattr(self, "current_page_scope", "_global_shared"),
                "endpoints": self.get_all_registered_endpoints(),
                "exported_at": time.strftime("%Y-%m-%d %H:%M:%S")
            },
            "page_scopes": {
                scope: {
                    ep: {
                        "url": ep,
                        "full_url": r.get("full_url"),
                        "timestamp": r.get("timestamp"),
                        "hit_count": r.get("hit_count", 1),
                        "data": r.get("data")
                    } for ep, r in eps.items()
                } for scope, eps in self.page_scoped_registry.items()
            },
            "global_flat_apis": self.api_registry
        }

        with open(save_file, "w", encoding="utf-8") as f:
            json.dump(dump_data, f, ensure_ascii=False, indent=2)
        logger.info(f"💾 [Auto-API] 页面作用域接口大盘已固化至: {save_file} (共 {len(self.api_registry)} 个独立接口，分布于 {len(self.page_scoped_registry)} 个页面作用域)")
        return str(save_file)

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
            "弹出", "浮层", "悬浮框", "框中", "测试", "检查", "页面", "右侧", "左侧", "顶部", "底部",
            "主卡片", "所有字段", "所有", "字段", "上的", "在", "主卡", "主"
        }

        # 0. 规范化数值：合并千分位逗号 (如 "42,024.35" -> "42024.35", "14,200t" -> "14200t")
        normalized_query = re.sub(r'(\d)[,，](\d)', r'\1\2', query_text)

        # 1. 完整日期特征 (如 2026-09-24, 2026/09/24)
        dates = re.findall(r'\d{4}[-/]\d{1,2}[-/]\d{1,2}', normalized_query)
        for d in dates:
            tokens.add(d)

        # 2. 括号/引号内的强实体 (如 ‘矿用液压锚杆台车’, 【采掘设备】, "G230324004")
        quoted = re.findall(r'[\'\"‘“【（\(]([^\'\"’”】）\)]+)[\'\"’”】）\)]', normalized_query)
        for q in quoted:
            q_clean = q.strip()
            if len(q_clean) >= 2 and q_clean.lower() not in stop_phrases:
                tokens.add(q_clean)

        # 3. 字母数字混合编码与业务ID (如 G230324004, ZW00101, FCB-1.5, KCG240201, 鄂PZZR02)
        plate_or_codes = re.findall(r'[\u4e00-\u9fa5]?[A-Za-z0-9_\-\.]{3,}', normalized_query)
        for c in plate_or_codes:
            if c.lower() not in stop_phrases and any(ch.isdigit() for ch in c) and not re.match(r'^\d{4}[-/]\d{1,2}[-/]\d{1,2}$', c):
                tokens.add(c)

        # 4. 数值与百分比指标 (如 89%, 59.5%, 42024.35, 14200)
        metrics = re.findall(r'\d+(?:\.\d+)?%?', normalized_query)
        for m in metrics:
            if len(m) > 1 or (m.isdigit() and int(m) > 0):
                tokens.add(m)
                # 若包含小数且整数部分 >= 3位，提取整数前缀 (如 42024.35 -> 42024，解决后端以整数或基础单位存储问题)
                if '.' in m:
                    int_part = m.split('.')[0]
                    if len(int_part) >= 3:
                        tokens.add(int_part)

        # 5. 按标点符号切分出的业务短语 (支持多层连续剥离前后停用词)
        clauses = re.split(r'[,，。！？、\s（）()“”"\'‘【】\[\]\-_：:‘’’“”]+', normalized_query)
        sorted_stops = sorted(stop_phrases, key=len, reverse=True)
        for clause in clauses:
            cleaned = clause.strip()
            if len(cleaned) < 2:
                continue
            changed = True
            while changed and len(cleaned) >= 2:
                changed = False
                for sp in sorted_stops:
                    if cleaned.lower().startswith(sp):
                        cleaned = cleaned[len(sp):].strip()
                        changed = True
                    if cleaned.lower().endswith(sp):
                        cleaned = cleaned[:-len(sp)].strip()
                        changed = True
            if len(cleaned) >= 2 and cleaned.lower() not in stop_phrases:
                tokens.add(cleaned)

        filtered = []
        for t in sorted(list(tokens), key=len, reverse=True):
            if t.lower() not in stop_phrases:
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

        date_years = {"2022", "2023", "2024", "2025", "2026", "2027", "2028", "2029", "2030"}

        DOMAIN_KEYWORD_MAP = {
            "采掘": ["mining", "extract", "excavate"],
            "产量": ["yield", "output", "production"],
            "计划": ["plan", "target"],
            "统计": ["statistics", "stats"],
            "电耗": ["power", "electric", "powerconsumption"],
            "水耗": ["water", "waterconsumption"],
            "油耗": ["fuel", "fuelconsumption"],
            "巡检": ["inspect", "inspection", "inspectrecord"],
            "资源": ["resource", "situation"],
            "储量": ["reserve", "situation", "reserves"],
            "车辆": ["vehicle", "truck", "car", "location"],
            "人员": ["staff", "person", "staffcount", "personnel"],
            "溜井": ["bin", "pass", "chute", "passbasic"],
            "矿仓": ["bin", "inventory", "binstats"],
            "通风": ["ventilation", "wind", "fan"],
            "风速": ["wind", "speed", "windspeed"],
            "环境": ["environment", "sensor"],
            "预警": ["alarm", "warn", "warning"],
            "告警": ["alarm"],
            "设备": ["equipment", "device"],
            "采场": ["stope", "stopebasic"],
            "钻孔": ["borehole", "hole"],
            "回采": ["mining", "stoping"],
        }

        for token in tokens:
            token_matched = False
            is_code = bool(re.search(r'[A-Za-z]', token) and re.search(r'\d', token))
            is_metric = bool(re.search(r'\d', token) and not re.search(r'[A-Za-z]', token))
            is_generic_date_part = token in date_years or (token.isdigit() and len(token) <= 2 and int(token) <= 31)

            if token in data_str:
                token_matched = True
                if is_code:
                    score += 60.0
                elif is_generic_date_part:
                    # 通用年份或月日纯数字，赋予较低基础分，防止冲高霸榜
                    score += 6.0
                elif is_metric:
                    score += 35.0
                else:
                    score += 40.0
            elif is_metric and token.endswith("%") and token[:-1] in data_str:
                token_matched = True
                score += 25.0

            if token.lower() == url_str:
                # 显式指定或全量命中接口名称，赋予极高权重
                score += 100.0
                token_matched = True
            elif len(token) >= 3 and token.lower() in url_str:
                score += 30.0
                token_matched = True

            # 领域业务关键词智能映射与加权 (解决中文图表 vs 英文接口名/字段名脱节痛点)
            for kw, en_terms in DOMAIN_KEYWORD_MAP.items():
                if kw in token:
                    for term in en_terms:
                        if term in url_str:
                            score += 50.0
                            token_matched = True
                            if f"{kw}->{term}" not in matched:
                                matched.append(f"{kw}->{term}")
                        elif term in data_str.lower():
                            score += 30.0
                            token_matched = True
                            if f"{kw}->{term}" not in matched:
                                matched.append(f"{kw}->{term}")

            if token_matched and token not in matched:
                matched.append(token)

        # =========================================================================
        # 方案 2 核心：业务实体强约束与防侥幸撞车过滤 (Entity Guard)
        # =========================================================================
        # 若检索词包含业务实体词（中文业务词、设备编码、或领域映射词），但该接口仅仅命中了弱纯数字或通用字段，
        # 则说明该接口纯属数值撞车，绝非专属数据源！直接将得分一票否决清零，杜绝误入候选池。
        has_strong_entity_in_tokens = any(
            re.search(r'[\u4e00-\u9fa5]', t) or
            (re.search(r'[A-Za-z]', t) and re.search(r'\d', t)) or
            any(kw in t for kw in DOMAIN_KEYWORD_MAP)
            for t in tokens
        )
        if has_strong_entity_in_tokens:
            has_strong_hit = False
            for m in matched:
                if "->" in m:
                    has_strong_hit = True
                    break
                if re.search(r'[\u4e00-\u9fa5]', m) and len(m) >= 2:
                    has_strong_hit = True
                    break
                if re.search(r'[A-Za-z]', m) and re.search(r'\d', m):
                    has_strong_hit = True
                    break
                if len(m) >= 3 and m.lower() in url_str:
                    has_strong_hit = True
                    break
            
            if not has_strong_hit:
                return 0.0, []

        # 方案 1 场景支持：页面初始化底座接口加权 (Page-Init Bonus)
        if record.get("is_page_init", False):
            score += 20.0

        # 高频轮询降权 (Poller Demotion)：若被标记为轮询，且未精确命中其专属 URL，得分打折
        if record.get("is_polling", False):
            if not any(m.lower() == url_str for m in matched):
                score *= 0.35

        # 方案 2 场景支持：交互动作差量加权 (Action Delta-Capture)
        action_ts = record.get("_action_ts", 0.0)
        rec_ts = record.get("timestamp", 0.0)
        if action_ts > 0 and rec_ts >= (action_ts - 0.2) and (rec_ts - action_ts) <= 3.0:
            score += 45.0

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

    def get_focused_api_records_summary(self, query_text: str = "", max_records: int = 6, max_total_chars: int = 24000, page_scope: Optional[str] = None) -> str:
        """
        通用两级智能接口寻索机制 (Two-Tier Intelligent API Retrieval)：
        - 【第一级：页面作用域优先定向检索 (Tier 1)】
          1. 优先在【当前页面作用域池】及【关联过渡态作用域】中定向匹配，彻底杜绝跨页面历史旧接口串扰；
          2. 智能聚合页面切换瞬时发出的过渡请求（如 '首页 -> 资源管理' 与 '资源管理 -> 资源储量'）；
          3. 智能融合【页面初始化底座接口池 (Page-Init)】，确保 Canvas 初始图表接口无论经过多少次轮询永远在线！
        - 【第二级：全量注册表智能穿透与兜底 (Tier 2)】
          若作用域池未命中核心业务特征，自动穿透检索全量会话注册表 (api_registry)。一旦命中高置信度业务数据源，自动补齐至当前页面池并消除误报！
        - 严格按 URL 去重选取 Top 核心接口（杜绝同一个轮询接口占满全部候选席位）；
        - 结构自适应智能脱敏压缩，保证输出合法的压缩 JSON。
        """
        if not hasattr(self, "api_registry") or self.api_registry is None:
            self.api_registry = {}
        if not hasattr(self, "page_scoped_registry") or self.page_scoped_registry is None:
            self.page_scoped_registry = {"_global_shared": {}}
        if not hasattr(self, "page_init_registry") or self.page_init_registry is None:
            self.page_init_registry = {"_global_shared": {}}

        active_scope = page_scope or getattr(self, "current_page_scope", "_global_shared")

        # =========================================================================
        # 【第一级：页面作用域优先定向检索 (Tier 1: Page-Scoped Direct Search)】
        # 1. 汇聚当前页面作用域池与全局常驻池，并智能关联跳转过渡态作用域
        # =========================================================================
        scoped_map = {}
        if "_global_shared" in self.page_scoped_registry:
            scoped_map.update(self.page_scoped_registry["_global_shared"])
        if active_scope in self.page_scoped_registry:
            scoped_map.update(self.page_scoped_registry[active_scope])

        # 场景 1 核心保障：将该页面的持久化底座接口也合并进来！确保 Canvas 刚进页面时的接口永远在线
        if active_scope in self.page_init_registry:
            for ep_name, record in self.page_init_registry[active_scope].items():
                if ep_name not in scoped_map:
                    scoped_map[ep_name] = record

        # 关联过渡态作用域：如果 active_scope 为 "A -> B"，智能汇聚包含 A 或 B 的过渡注册表（解决页面跳转瞬时接口归属时差）
        scope_parts = [p.strip() for p in active_scope.split("->") if p.strip()]
        if scope_parts:
            for reg_scope, eps in self.page_scoped_registry.items():
                if reg_scope in ("_global_shared", active_scope):
                    continue
                if any(part in reg_scope for part in scope_parts):
                    for ep_name, record in eps.items():
                        if ep_name not in scoped_map:
                            scoped_map[ep_name] = record

        tokens = self.extract_search_tokens(query_text) if query_text else []
        action_ts = getattr(self, "last_action_timestamp", 0.0)

        tier1_scored = []
        for r in scoped_map.values():
            if action_ts > 0:
                r["_action_ts"] = action_ts
            score, matched = self.score_record(r, tokens)
            tier1_scored.append((score, matched, r))
        tier1_scored.sort(key=lambda x: x[0], reverse=True)

        date_set = {"2022", "2023", "2024", "2025", "2026", "2027", "2028", "2029", "2030"}
        def is_business_confident_hit(scored_list: List[tuple]) -> bool:
            if not scored_list or scored_list[0][0] <= 0:
                return False
            best_score, best_matched, _ = scored_list[0]
            non_date_hits = [m for m in best_matched if m not in date_set and not (m.isdigit() and len(m) <= 2)]
            return bool(non_date_hits or best_score >= 40.0)

        selected_candidates = []
        seen_urls = set()
        direct_hit = False

        tier1_confident = is_business_confident_hit(tier1_scored)

        # =========================================================================
        # 【第二级：全量注册表智能穿透与兜底 (Tier 2: Global Penetration & Fallback)】
        # 当且仅当 Tier 1 未命中核心业务特征，或全量注册表中存在压倒性的高分接口时触发穿透
        # =========================================================================
        if not tier1_confident and self.api_registry:
            tier2_scored = []
            for r in self.api_registry.values():
                if action_ts > 0:
                    r["_action_ts"] = action_ts
                score, matched = self.score_record(r, tokens)
                if score > 0:
                    tier2_scored.append((score, matched, r))
            tier2_scored.sort(key=lambda x: x[0], reverse=True)

            if is_business_confident_hit(tier2_scored):
                best_g_score, best_g_matched, best_g_record = tier2_scored[0]
                t1_score = tier1_scored[0][0] if tier1_scored else 0.0
                if best_g_score > t1_score or not tier1_confident:
                    logger.info(f"✨ [Auto-API Two-Tier] 作用域池未命中专属业务数据，触发二级全局穿透！命中全量注册表核心接口: '{best_g_record['url']}'(得分:{best_g_score}, 命中:{best_g_matched})！跨页面补齐数据源。")
                    # 动态将该接口补齐挂载到当前页面作用域池 (Dynamic Scope Healing)
                    if active_scope not in self.page_scoped_registry:
                        self.page_scoped_registry[active_scope] = {}
                    self.page_scoped_registry[active_scope][best_g_record["url"]] = best_g_record

                    for g_score, g_matched, g_r in tier2_scored:
                        if is_business_confident_hit([(g_score, g_matched, g_r)]) and g_r.get("url") not in seen_urls:
                            selected_candidates.append((g_score, g_matched, g_r))
                            seen_urls.add(g_r.get("url"))
                            if len(selected_candidates) >= max_records:
                                break
                    direct_hit = True

        # 若二级穿透未触发，按常规 Tier 1 结果选取（限制轮询接口最多占1个席位，杜绝轮询霸榜）
        if not selected_candidates:
            if tier1_scored and tier1_scored[0][0] > 0:
                direct_hit = True
                polling_count = 0
                for score, matched, r in tier1_scored:
                    u = r.get("url")
                    is_poll = r.get("is_polling", False)
                    if is_poll and polling_count >= 1:
                        continue
                    if score > 0 and u not in seen_urls and len(selected_candidates) < max_records:
                        selected_candidates.append((score, matched, r))
                        seen_urls.add(u)
                        if is_poll:
                            polling_count += 1
                hit_info = ", ".join([f"'{r['url']}'(得分:{s}, 命中:{m})" for s, m, r in selected_candidates])
                logger.info(f"🎯 [Auto-API Inverted Index][作用域: {active_scope}] 倒排索引命中核心候选接口: {hit_info}")
            else:
                logger.info(f"ℹ️ [Auto-API Inverted Index][作用域: {active_scope}] 未直接命中特征Token，回退选取最近活跃的 {max_records} 个独立业务接口供全量核验。")
                fallback_pool = list(scoped_map.values()) if scoped_map else list(self.api_registry.values())
                sorted_by_time = sorted(fallback_pool, key=lambda x: x.get("timestamp", 0), reverse=True)
                polling_count = 0
                for r in sorted_by_time:
                    u = r.get("url")
                    is_poll = r.get("is_polling", False)
                    if is_poll and polling_count >= 1:
                        continue
                    if u not in seen_urls and len(selected_candidates) < max_records:
                        selected_candidates.append((0.0, [], r))
                        seen_urls.add(u)
                        if is_poll:
                            polling_count += 1

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
                "page_scope": active_scope,
                "extracted_tokens": tokens,
                "direct_hit": direct_hit,
                "candidate_urls": [c["url"] for c in compressed_apis]
            },
            "candidate_apis": compressed_apis
        }

        summary = json.dumps(output_struct, ensure_ascii=False, indent=2)
        if len(summary) > max_total_chars:
            # 安全压缩避免非法截断 JSON
            for c in output_struct["candidate_apis"]:
                if isinstance(c.get("data"), dict):
                    for k in list(c["data"].keys()):
                        if isinstance(c["data"][k], list) and len(c["data"][k]) > 2:
                            c["data"][k] = c["data"][k][:2] + [{"_further_compressed": True}]
            summary = json.dumps(output_struct, ensure_ascii=False, indent=2)
        return summary

    def get_api_records_summary(self, query_text: str = "") -> str:
        """返回核心 JSON 数据（向前兼容，自动支持带 query 的动态聚焦检索）"""
        return self.get_focused_api_records_summary(query_text=query_text)

    def get_and_clear_bugs(self) -> list:
        """获取并清空后台捕获到的所有异常报错"""
        bugs = list(self.caught_bugs)
        self.caught_bugs = []
        return bugs



