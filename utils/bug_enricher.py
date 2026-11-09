# -*- coding: utf-8 -*-
"""
utils/bug_enricher.py —— 缺陷元数据智能增强、规范化与快照萃取器

核心职责：
1. 元数据智能抽取：从测试步骤文本中自动提取规范的 UI 路径、交互动作类型(action_type)与目标元素。
2. 严重级别对齐：将中英文、数字等多种等级表示统一归一化为禅道标准 1~4 级（致命、严重、一般、轻微）。
3. 快照凭证萃取：在运行产物中自动关联案发现场高精切片(ROI)与全屏原图，补齐 Bug 证据链。
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional


def extract_ui_path_from_step(step_str: Any, default: str = "首页") -> str:
    """从 step 描述中智能提炼业务路径，例如从 '(页面路径: 智控管理 -> 智能溜破)' 中提取"""
    if not step_str:
        return default
    s = str(step_str).strip()
    m = re.search(r'\(?(?:页面)?路径[:：]\s*([^)]+)\)?', s)
    if m:
        extracted = m.group(1).strip()
        if extracted and extracted != "无":
            return extracted
    return default


def normalize_severity(val: Any) -> int:
    """与禅道标准对齐：1(致命), 2(严重), 3(一般,默认), 4(轻微)"""
    if val is None or val == "" or val == "无":
        return 3
    s = str(val).lower().strip()
    if s in ["1", "critical", "fatal", "blocker", "致命"]:
        return 1
    if s in ["2", "high", "major", "严重"]:
        return 2
    if s in ["3", "medium", "normal", "一般"]:
        return 3
    if s in ["4", "low", "minor", "trivial", "轻微"]:
        return 4
    try:
        num = int(s)
        if 1 <= num <= 4:
            return num
    except Exception:
        pass
    return 3


def enrich_bug_metadata(
    b_dict: Dict[str, Any],
    shots_dir: Optional[Path] = None,
    matched_step: Optional[int] = None
) -> Dict[str, Any]:
    """
    统一的 Bug 元数据智能增强处理（单一数据源）：
    从 step 文本或 details 中自动解析并规范化：
    - action_type (CLICK, HOVER, WAIT 等)
    - target_element (目标交互元素名称)
    - ui_path (业务页面路径)
    - tags (业务标签数组)
    - step_num 与 before_screenshot (操作前快照)
    """
    if not isinstance(b_dict, dict):
        return b_dict

    details = b_dict.get("details") if isinstance(b_dict.get("details"), dict) else {}
    step_str = str(details.get("step") or b_dict.get("step") or "")

    # 1. 提炼动作类型 action_type
    if not b_dict.get("action_type") or b_dict.get("action_type") == "无":
        m_act = re.search(r"\[([A-Z_]+)\]", step_str)
        if m_act:
            b_dict["action_type"] = m_act.group(1).strip()

    # 2. 提炼交互目标 target_element
    if not b_dict.get("target_element") or b_dict.get("target_element") == "无":
        m_tgt = re.search(r"交互目标[:：]\s*['\"]?(.*?)['\"]?\s*(?:\(|$)", step_str)
        if m_tgt:
            b_dict["target_element"] = m_tgt.group(1).strip()

    # 3. 提炼业务路径 ui_path
    if not b_dict.get("ui_path") or b_dict.get("ui_path") in ("无", "首页"):
        b_dict["ui_path"] = extract_ui_path_from_step(step_str, default=b_dict.get("ui_path") or "首页")

    # 4. 关联执行树对应步骤编号与执行前截图
    if matched_step:
        b_dict["step_num"] = matched_step
    elif not b_dict.get("step_num") and b_dict.get("global_step"):
        try:
            m_s = re.search(r"\d+", str(b_dict["global_step"]))
            if m_s:
                b_dict["step_num"] = int(m_s.group(0))
        except Exception:
            pass

    if shots_dir and b_dict.get("step_num") and not b_dict.get("before_screenshot"):
        before_file = f"explore_step_{b_dict['step_num']}.png"
        if (shots_dir / before_file).exists():
            b_dict["before_screenshot"] = f"screenshots/{before_file}"

    # 5. 智能推导业务标签 tags
    raw_tags = b_dict.get("tags")
    if not raw_tags or raw_tags == "无" or raw_tags == [] or raw_tags == "":
        auto_tags: List[str] = []
        if b_dict.get("action_type") and b_dict["action_type"] != "无":
            auto_tags.append(b_dict["action_type"])
        u_path = b_dict.get("ui_path", "")
        if u_path and u_path != "无":
            auto_tags.extend([p.strip() for p in u_path.split("->") if p.strip()])
        t_elem = b_dict.get("target_element", "")
        if t_elem and t_elem != "无":
            for k in ["一级菜单", "二级菜单", "按钮", "图表", "弹窗", "折线图", "柱状图", "表格"]:
                if k in t_elem and k not in auto_tags:
                    auto_tags.append(k)
        b_dict["tags"] = list(dict.fromkeys(auto_tags)) if auto_tags else ["常规交互"]
    elif isinstance(raw_tags, str) and "," in raw_tags:
        b_dict["tags"] = [t.strip() for t in raw_tags.split(",") if t.strip()]

    # 6. 统一严重程度格式化
    if "severity" in b_dict:
        b_dict["severity"] = normalize_severity(b_dict["severity"])

    return b_dict
