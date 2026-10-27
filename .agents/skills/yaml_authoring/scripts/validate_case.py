#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
YAML 测试用例合规性与静态 Schema 校验器 (YAML Case Validator)
=============================================================
用于在生成或修改 YAML 用例后，一键执行语法静态检查，确保：
1. YAML 语法与数据结构完全合规（包含 name 与 steps 数组）。
2. 使用系统支持的标准动作词汇表，无拼写错误。
3. 杜绝违禁用法：
   - 严禁使用 reload/refresh（会导致 UE 像素流断开）；
   - 严禁使用硬编码 DOM/XPath 选择器（违背视觉双擎定位哲学）。
4. 各步骤必填参数检查（如 action/assert/wait_for 必须有 prompt）。
"""

import sys
import argparse
from pathlib import Path

# 确保在 Windows 控制台下支持 UTF-8 打印
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

try:
    import yaml
except ImportError:
    print("[Error] 缺少 PyYAML 依赖，请运行 pip install pyyaml")
    sys.exit(1)

VALID_TYPES = {
    "action",
    "input",
    "assert",
    "api_assert",
    "freeze_check",
    "wait_for",
    "zoom", "zoom_3d",
    "rotate_3d", "orbit",
    "wheel", "mouse_wheel",
    "scroll", "scroll_element",
    "slide", "slider",
    "drag",
    "back", "go_back", "navigate_back",
    "wait",
}

FORBIDDEN_TYPES = {
    "reload": "在 WebRTC 像素流架构下网页刷新会切断与 UE 信号服务器连接，严禁使用 reload！",
    "refresh": "在 WebRTC 像素流架构下网页刷新会切断与 UE 信号服务器连接，严禁使用 refresh！",
}

DOM_SELECTOR_PATTERNS = ["xpath=", "//", "css=", "id=", "querySelector", "class="]


def validate_yaml_case(case_path: Path) -> bool:
    print("=" * 60)
    print(f"🔍 开始校验用例: {case_path}")
    print("=" * 60)

    if not case_path.exists():
        print(f"❌ 文件不存在: {case_path}")
        return False

    try:
        with open(case_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as e:
        print(f"❌ YAML 解析失败！语法错误: {e}")
        return False

    if not isinstance(data, dict):
        print("❌ 用例顶层必须是一个 Mapping 字典对象！")
        return False

    case_name = data.get("name")
    if not case_name:
        print("⚠️ 警告: 缺少用例名称 'name' 字段。")
    else:
        print(f"📋 用例名称: {case_name}")

    steps = data.get("steps")
    if not isinstance(steps, list) or len(steps) == 0:
        print("❌ 'steps' 必须为非空的列表！")
        return False

    errors = []
    warnings = []

    has_wait_for = False
    has_api_assert = False

    for idx, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            errors.append(f"Step {idx}: 步骤必须是对象映射，实际为 {type(step)}")
            continue

        step_type = step.get("type")
        if not step_type:
            errors.append(f"Step {idx}: 缺少 'type' 动作类型！")
            continue

        # 1. 禁用词校验
        if step_type in FORBIDDEN_TYPES:
            errors.append(f"Step {idx}: 【严重违禁】{FORBIDDEN_TYPES[step_type]}")

        # 2. 合法动作类型校验
        if step_type not in VALID_TYPES:
            errors.append(f"Step {idx}: 未知的动作类型 '{step_type}'，请检查拼写。")

        # 3. 必填字段检查
        prompt = step.get("prompt", "")
        if step_type in ("action", "assert", "api_assert", "wait_for"):
            if not prompt or not str(prompt).strip():
                errors.append(f"Step {idx} ({step_type}): 必须提供有效的 'prompt' 自然语言指令！")

        if step_type == "input":
            text = step.get("text")
            fuzz = step.get("fuzz", False)
            if not text and not fuzz:
                errors.append(f"Step {idx} (input): 必须提供 'text' 输入内容或指定 fuzz: true！")

        if step_type == "wait_for":
            has_wait_for = True

        if step_type == "api_assert":
            has_api_assert = True

        # 4. 反模式检测：严禁在 prompt 中出现传统 XPath / 选择器
        for pat in DOM_SELECTOR_PATTERNS:
            if pat in prompt:
                warnings.append(
                    f"Step {idx} ({step_type}): prompt 包含可疑的选择器特征 '{pat}'。"
                    f"请务必使用自然语言意图描述，严禁依赖底层 DOM 选择器！"
                )

    # 业务规范提示
    if not has_wait_for and len(steps) > 1:
        warnings.append("用例开篇建议使用 'wait_for' 智能等待主标题或首页加载就绪，避免因网络抖动造成首步失败。")
    if not has_api_assert:
        warnings.append("用例未包含 'api_assert' 接口交叉断言。若涉及核心业务指标，请遵循矿山大屏三大铁律加入数据核验。")

    # 汇报结果
    if warnings:
        print("\n⚠️ 发现以下改进建议/警告:")
        for w in warnings:
            print(f"  - {w}")

    if errors:
        print("\n❌ 发现以下严重错误 (用例未通过校验):")
        for err in errors:
            print(f"  - {err}")
        print("=" * 60)
        return False

    print("\n✅ 语法与 Schema 校验通过！总计步骤数:", len(steps))
    print("=" * 60)
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="YAML 用例合规性校验工具")
    parser.add_argument("path", type=str, help="YAML 用例路径")
    args = parser.parse_args()

    success = validate_yaml_case(Path(args.path))
    sys.exit(0 if success else 1)
