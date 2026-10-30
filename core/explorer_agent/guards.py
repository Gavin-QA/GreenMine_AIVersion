"""
core/explorer_agent/guards.py —— 探索执行与多模态断言的通用安全防御守卫
==============================================================================
职责：
1. is_valid_metric_chart: 探针提取数据有效性校验（排除 3D 占位态/默认视角）
2. check_chart_api_affinity: 图表指标实体与候选 API 报文的通用语义亲和度初筛（防非同源与探针偏靶）
3. extract_chart_metric_keywords: 从全量数据点中提取核心度量指标词根
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Set, Tuple

logger = logging.getLogger("explorer_agent.guards")


class ExplorerGuards:
    """自主探索通用防御守卫套件"""

    NON_METRIC_PLACEHOLDERS = {
        "默认视角", "none", "-", "null", "undefined", "暂无数据", "无", "0.0", "NaN"
    }

    @classmethod
    def is_valid_metric_chart(cls, points: List[Any]) -> bool:
        """
        探针点位有效性卫语句：检查图表是否仅捕获到非业务占位数据（如 3D 视口、占位字符）
        """
        if not points:
            return False

        for p in points:
            if isinstance(p, dict):
                vals = [str(v).strip() for v in p.values() if v is not None]
                if any(v and v not in cls.NON_METRIC_PLACEHOLDERS for v in vals):
                    return True
            elif isinstance(p, (int, float)):
                return True
            elif isinstance(p, str) and p.strip() and p.strip() not in cls.NON_METRIC_PLACEHOLDERS:
                return True

        return False

    @classmethod
    def extract_chart_metric_keywords(cls, points: List[Any]) -> Set[str]:
        """
        从探针采集到的各数据点 (Tooltip / Series) 中，抽离出关键度量指标名称集合
        自动剔除通用元数据键（如 raw, label, style, detail_* 等），并剥离单位括号
        """
        metric_keys: Set[str] = set()

        for p in points:
            if not isinstance(p, dict):
                continue
            for k in p.keys():
                k_str = str(k).strip()
                # 过滤通用元数据键
                if not k_str or k_str in ("raw", "label", "style", "itemStyle") or k_str.startswith("detail_"):
                    continue

                # 剥离括号与单位，例如 "油耗(L)" -> "油耗", "进尺[m]" -> "进尺"
                clean_k = re.sub(r'[\(（\[].*?[\)）\]]', '', k_str).strip()
                if clean_k and len(clean_k) >= 2:
                    metric_keys.add(clean_k)
                if len(k_str) >= 2:
                    metric_keys.add(k_str)

        return metric_keys

    @classmethod
    def check_chart_api_affinity(cls, points: List[Any], api_summary: str) -> Tuple[bool, List[str]]:
        """
        通用数据源亲和度初筛卫语句 (Semantic Affinity Pre-filter)
        
        原理：
        如果图表探针实际提取到了明确的业务指标名称，但候选 API 报文中连任何一个指标关键词的词根
        都完全不存在，说明该候选 API 与当前图表绝非同源数据（探针偏靶至相邻卡片，或倒排池未捕获到真实接口）。
        
        :return: (has_affinity, chart_metric_keys_list)
        """
        if not api_summary or api_summary.strip() == "[]":
            return False, []

        metric_keys = cls.extract_chart_metric_keywords(points)
        metric_keys_list = sorted(list(metric_keys))

        # 若图表完全未捕获到指标名（例如单纯是纯数字序列），不作阻断，放行给模型
        if not metric_keys:
            return True, []

        api_summary_lower = api_summary.lower()
        matched_any = any(k.lower() in api_summary_lower for k in metric_keys)

        if not matched_any:
            logger.info(
                f"🛡️ [AffinityGuard] 亲和度守卫拦截: 图表提取指标 {metric_keys_list} "
                f"与候选 API 报文无任何同源词根交集，判定为非同源数据源，免除误判。"
            )
            return False, metric_keys_list

        return True, metric_keys_list

    # ==========================================================================
    # 物理常识与前端脏值零 Token 静态预筛器 (Physics & Dirty Value Regex Guard)
    # ==========================================================================
    _DIRTY_TOKEN_PATTERNS = [
        (re.compile(r'(?<![A-Za-z])NaN(?![A-Za-z])'), "前端计算脏值 NaN"),
        (re.compile(r'(?<![A-Za-z])-?Infinity(?![A-Za-z])'), "前端除零溢出值 Infinity"),
        (re.compile(r'(?<![A-Za-z])undefined(?![A-Za-z])'), "前端未定义变量泄漏 undefined"),
        (re.compile(r'\[object\s+Object\]'), "前端对象未序列化泄漏 [object Object]"),
        (re.compile(r'Invalid\s+Date', re.IGNORECASE), "前端时间解析失败 Invalid Date"),
        (re.compile(r'1970[-/年]0?1[-/月]0?1'), "Unix零时间戳未初始化异常 (1970-01-01)"),
    ]

    # 绝对不允许为负数的矿山实体物理量（严格排除日期 2026-10-30 与区间 10-20人）
    _NEGATIVE_ENTITY_RE = re.compile(
        r'(?<!\d)(?<!\d\s)(?:^|[:：=]|(?<=\s))(-\d+(?:\.\d+)?)\s*(人|名|辆|台|座|万吨|千吨|m³/s|m3/s)'
    )

    # 严格有界 [0%, 100%] 的比率指标（不含同比/环比/完成率等可超100%指标）
    _BOUNDED_RATIO_RE = re.compile(
        r'(完好率|在线率|出勤率|合格率|稼动率|运转率|开动率|湿度|矿石品位|品位)[^\d\-%]{0,10}(-?\d+(?:\.\d+)?)\s*%'
    )

    @classmethod
    def scan_text_physics_anomalies(cls, texts_or_elements: List[Any], max_items: int = 12) -> List[str]:
        """
        零 Token 消耗的静态物理常识与渲染脏值扫描器。
        对 DOM 提取的可见文本列表进行毫秒级正则巡检，捕获明显泄漏的 NaN / undefined / 负人数 / 越界率值线索，
        供多模态大模型二次视觉复核。
        """
        if not texts_or_elements:
            return []

        anomalies: List[str] = []
        seen: Set[str] = set()

        for item in texts_or_elements:
            if isinstance(item, dict):
                raw_text = str(item.get("text") or "").strip()
                container = str(item.get("container_name") or "").strip()
            else:
                raw_text = str(item or "").strip()
                container = ""

            if not raw_text:
                continue

            prefix = f"[{container}] " if container else ""
            snippet = raw_text[:80].replace("\n", " ")

            # 1. 前端 JS 脏值泄漏检测
            for pattern, label in cls._DIRTY_TOKEN_PATTERNS:
                if pattern.search(raw_text):
                    msg = f"{prefix}{label}: '{snippet}'"
                    if msg not in seen:
                        seen.add(msg)
                        anomalies.append(msg)

            # 2. 矿山非负物理量出现负数检测
            for m in cls._NEGATIVE_ENTITY_RE.finditer(raw_text):
                val_str, unit_str = m.group(1), m.group(2)
                msg = f"{prefix}非负物理量出现负值 ({val_str}{unit_str}): '{snippet}'"
                if msg not in seen:
                    seen.add(msg)
                    anomalies.append(msg)

            # 3. 严格有界百分比 (<0% 或 >100%) 越界检测
            for m in cls._BOUNDED_RATIO_RE.finditer(raw_text):
                metric_name, num_str = m.group(1), m.group(2)
                try:
                    num_val = float(num_str)
                    if num_val < 0.0 or num_val > 100.0:
                        msg = f"{prefix}有界指标越界 ({metric_name}={num_val}% 超出 0~100%): '{snippet}'"
                        if msg not in seen:
                            seen.add(msg)
                            anomalies.append(msg)
                except ValueError:
                    pass

            if len(anomalies) >= max_items:
                break

        return anomalies

