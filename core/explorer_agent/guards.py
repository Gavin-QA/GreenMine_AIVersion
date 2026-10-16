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
