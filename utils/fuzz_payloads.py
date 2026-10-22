# -*- coding: utf-8 -*-
"""
表单边界值与异常脏数据生成器 (Form Fuzz Payloads Generator)
专门用于大屏与 Web 应用输入框的健壮性、防爆破与边界值测试。
"""

import random
from typing import List, Dict

NUMERIC_BOUNDARY_PAYLOADS = [
    "-1",
    "-999999",
    "0",
    "999999999",
    "9999999999999999",
    "-0.0000001",
    "99999.999999",
    "NaN",
    "Infinity",
    "-Infinity",
]

SPECIAL_CHARACTER_PAYLOADS = [
    "!@#$%^&*()_+",
    "[]{}|;:'\",.<>/?`~",
    "<script>alert('xss')</script>",
    "' OR '1'='1' --",
    "{{7*7}}",
    "${7*7}",
    "⛏️🔥⚠️💎🚀⚡",
]

LONG_STRING_PAYLOADS = [
    "A" * 128,
    "超长边界测试" * 30,
    "1234567890" * 25,
]

WHITESPACE_PAYLOADS = [
    "   ",
    " \t \n ",
    "   admin   ",
]

def get_fuzz_payload(element_desc: str = "", category: str = "auto") -> str:
    """
    根据输入框的语义描述或指定的分类，智能返回最具杀伤力的边界探测数据
    :param element_desc: 输入框的自然语言语义描述 (如 '风量上限阈值输入框', '设备名称搜索框')
    :param category: 强制指定的分类 ("numeric" | "special" | "long" | "whitespace" | "auto")
    """
    desc_lower = (element_desc or "").lower()

    if category == "numeric" or any(k in desc_lower for k in [
        "阈值", "上限", "下限", "人数", "风量", "温度", "浓度", "风速",
        "转速", "频率", "功率", "电流", "电压", "量程", "数值", "数字", "倍数"
    ]):
        return random.choice(NUMERIC_BOUNDARY_PAYLOADS)

    if category == "special" or any(k in desc_lower for k in ["搜索", "查找", "查询", "名称", "编码", "编号", "关键字", "过滤"]):
        candidates = SPECIAL_CHARACTER_PAYLOADS + [
            "测试' OR '1'='1",
            "NonExist_#@!",
            "<img src=x onerror=alert(1)>",
            "   "
        ]
        return random.choice(candidates)

    if category == "long":
        return random.choice(LONG_STRING_PAYLOADS)

    # 默认混合随机选择
    all_candidates = (
        NUMERIC_BOUNDARY_PAYLOADS[:4] +
        SPECIAL_CHARACTER_PAYLOADS[:4] +
        LONG_STRING_PAYLOADS[:1]
    )
    return random.choice(all_candidates)
