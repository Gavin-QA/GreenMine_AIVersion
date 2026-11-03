# -*- coding: utf-8 -*-
"""
bug_analysis_expert.py — 研发级 AI 缺陷根因深度诊断与工单排障专家引擎

针对矿山大屏/Electron 复杂应用的缺陷，自动注入当前 Launcher 版本、网络协议环境（HTTP vs HTTPS 安全上下文）、
前端包基线与报错调用栈，驱动大模型以架构师视角输出具备“无可辩驳的证据链”与“拿来即用修复代码”的专业研发工单。
"""

import os
import re
import json
import base64
import logging
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger("utils.bug_analysis_expert")

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def get_file_version_fast(file_path: str) -> str:
    """通过 Windows 原生 ctypes API 毫秒级提取 exe/dll 的 FileVersion"""
    if not file_path or not os.path.exists(file_path):
        return "未知"
    try:
        import ctypes
        from ctypes import wintypes

        size = ctypes.windll.version.GetFileVersionInfoSizeW(str(file_path), None)
        if not size:
            return "未知"
        res = ctypes.create_string_buffer(size)
        if not ctypes.windll.version.GetFileVersionInfoW(str(file_path), None, size, res):
            return "未知"
        u_len = wintypes.UINT()
        lplp = ctypes.c_void_p()
        if ctypes.windll.version.VerQueryValueW(res, "\\", ctypes.byref(lplp), ctypes.byref(u_len)):
            class VS_FIXEDFILEINFO(ctypes.Structure):
                _fields_ = [
                    ("dwSignature", wintypes.DWORD),
                    ("dwStrucVersion", wintypes.DWORD),
                    ("dwFileVersionMS", wintypes.DWORD),
                    ("dwFileVersionLS", wintypes.DWORD),
                    ("dwProductVersionMS", wintypes.DWORD),
                    ("dwProductVersionLS", wintypes.DWORD),
                ]
            v = ctypes.cast(lplp, ctypes.POINTER(VS_FIXEDFILEINFO)).contents
            return f"{v.dwFileVersionMS >> 16}.{v.dwFileVersionMS & 0xffff}.{v.dwFileVersionLS >> 16}"
    except Exception as e:
        logger.debug(f"提取文件版本异常: {e}")
    return "未知"


def get_runtime_environment_context(app_key: Optional[str] = None) -> Dict[str, Any]:
    """
    自动采集当前被测应用的关键环境基因：
    - 所属矿山应用名称 (寨湾 / 天瑞 / 里伍铜)
    - 启动器物理路径与版本号 (如 1.4.2644)
    - 访问协议环境 (如 http://221.234.48.197:8808 -> 非安全上下文 Secure Context)
    - 前端静态包版本与 CDP 端口
    """
    from config.settings import settings

    target_app = app_key or getattr(settings, "active_app", "zhaiwan")
    apps_cfg = getattr(settings, "apps", {})
    app_info = apps_cfg.get(target_app, {})

    app_names = {
        "zhaiwan": "寨湾矿山",
        "tianrui": "天瑞矿山",
        "liwutong": "里伍铜矿",
    }
    app_chinese = app_names.get(target_app, f"{target_app}项目")

    launcher_path = app_info.get("launcher_path") or app_info.get("exe_path") or getattr(settings, "app_path", "")
    launcher_ver = get_file_version_fast(launcher_path)

    env_check = app_info.get("env_check", {})
    frontend_ver = env_check.get("frontend_version", "未指定")
    backend_api_base = env_check.get("backend_api_base", "未配置")

    # 安全上下文判断 (Chromium 规范：非 HTTPS 且非 localhost 属于非安全上下文，大量高级 Web API 会被静默禁用)
    is_secure = False
    if backend_api_base:
        lower_url = backend_api_base.lower()
        if lower_url.startswith("https://") or "localhost" in lower_url or "127.0.0.1" in lower_url:
            is_secure = True

    return {
        "app_key": target_app,
        "app_chinese": app_chinese,
        "launcher_path": launcher_path,
        "launcher_version": launcher_ver,
        "frontend_version": frontend_ver,
        "backend_api_base": backend_api_base,
        "is_secure_context": is_secure,
        "debug_port": app_info.get("debug_port", getattr(settings, "cdp_port", 9222)),
        "architecture": "Electron Chromium 渲染核 + WebRTC 像素流通讯 + Vue2/3 二维大屏业务面板",
    }


def build_expert_analysis_prompt(bug: Dict[str, Any], env_ctx: Dict[str, Any]) -> Tuple[str, str]:
    """构建研发级根因深度诊断的 System Prompt 与 User Prompt"""
    system_prompt = (
        "你是一个拥有 10 年以上经验的 Electron 桌面客户端架构师、前端高级技术专家与自动化测试全栈诊断顾问。\n"
        "当测试框架捕获到一个新的缺陷时，你的任务是输出一份具备【无可辩驳的技术证据链】与【拿来即用修复代码】的研发级深度初诊报告。\n"
        "这份报告将直接推送到禅道 (ZenTao) 指派给研发工程师（前端：陈贻雄 / 后端：梅本霞）。\n"
        "【严禁】输出空泛无用的套话（如仅回答'组件报错建议联系前端'）。\n"
        "你必须结合报错堆栈、W3C/MDN 浏览器规范（如 Chromium Secure Context 安全上下文策略）、WebRTC 握手通信逻辑、"
        "Vue 虚拟 DOM/生命周期、以及当前特定的软件版本与网络协议，给出具有高度说服力的技术论证。\n\n"
        "你必须且只能返回一个合法的 JSON 对象，包含以下字段：\n"
        "{\n"
        '  "category": "核心技术定性与分类（如：【前端】非安全HTTP上下文引发Web Crypto API受限 / 【启动器】WebRTC握手断流 / 【后端】500服务契约破损）",\n'
        '  "summary": "一句话核心案发判定（直击问题最根本的技术冲突点）",\n'
        '  "root_cause_analysis": "底层案发机理解析（结合规范、协议、调用链深入剖析为什么此处会报错，说明底层执行流程）",\n'
        '  "environment_diff": "跨环境与多端差异破局（专门分析解答为什么部分电脑能跑/测试不复现，而在此电脑复现，如版本断代、HTTP与HTTPS策略差异、控制台静默忽略等）",\n'
        '  "reproduction_impact": "业务影响与隐患评估（评估对三维孪生推流、大屏面板交互或数据渲染的破坏性）",\n'
        '  "solution_patch": "代码级修复建议与兼容性补丁（提供可以直接复制粘贴的 JavaScript/TypeScript 或后端补丁代码片段，必须具有生产级防御性）",\n'
        '  "recommended_assignee": "陈贻雄 (前端) 或 梅本霞 (后端)（附简要判定理由）",\n'
        '  "formatted_markdown": "由上述内容精心编排的高颜值、具备清晰小标题与代码块的完整 Markdown 诊断报告"\n'
        "}\n"
        "不要输出除该 JSON 对象之外的任何外部文本。"
    )

    bug_id = bug.get("id", "BUG-UNKNOWN")
    title = bug.get("title", "未命名缺陷")
    step = bug.get("step") or bug.get("step_prompt") or "无记录"
    ui_path = bug.get("ui_path", "未知")
    actual = bug.get("actual") or bug.get("error_log") or "无具体报错堆栈"
    occurrences = bug.get("occurrences", 1)

    security_note = (
        "⚠️ 注意：当前页面访问协议为 HTTP 真实 IP 域名（属于 Chromium 非安全上下文 Non-Secure Context）。"
        "W3C 与 MDN 规范明确规定：部分现代 Web API（例如 crypto.randomUUID、SubtleCrypto、Clipboard API、MediaDevices 等）"
        "在非安全上下文中会被 Chromium 强制挂起或设为 undefined！"
        if not env_ctx.get("is_secure_context")
        else "当前环境处于安全上下文 (HTTPS 或 Localhost)。"
    )

    user_prompt = (
        f"【缺陷基本档案】\n"
        f"- 缺陷编号: {bug_id}\n"
        f"- 缺陷标题: {title}\n"
        f"- 业务路径: {ui_path}\n"
        f"- 触发交互: {step}\n"
        f"- 历史累计复现: {occurrences} 次\n\n"
        f"【案发现场报错堆栈与实际结果】:\n"
        f"{actual}\n\n"
        f"【被测应用环境基因基线】:\n"
        f"- 所属矿山: {env_ctx.get('app_chinese')} ({env_ctx.get('app_key')})\n"
        f"- 客户端架构: {env_ctx.get('architecture')}\n"
        f"- 启动器路径: {env_ctx.get('launcher_path')}\n"
        f"- 启动器文件版本: {env_ctx.get('launcher_version')}\n"
        f"- 目标前端包版本: {env_ctx.get('frontend_version')}\n"
        f"- 后端网络基地址: {env_ctx.get('backend_api_base')}\n"
        f"- 协议安全上下文判定: {security_note}\n\n"
        f"请结合以上全部环境特征与报错堆栈，输出针对该缺陷的研发级初诊分析 JSON。"
    )

    return system_prompt, user_prompt


def analyze_bug_expertly(
    agent,
    model: str,
    bug: Dict[str, Any],
    crash_image_path: Optional[str] = None,
    app_key: Optional[str] = None
) -> Tuple[str, Dict[str, Any]]:
    """
    统一执行专家级 AI 缺陷根因深度诊断，返回格式化 Markdown 文本及结构化字典
    """
    env_ctx = get_runtime_environment_context(app_key or bug.get("app"))
    system_prompt, user_prompt = build_expert_analysis_prompt(bug, env_ctx)

    base64_img = None
    target_img = crash_image_path or bug.get("screenshot") or bug.get("crash_screenshot")
    if target_img and Path(target_img).exists():
        try:
            with open(target_img, "rb") as f:
                base64_img = base64.b64encode(f.read()).decode("utf-8")
        except Exception as ie:
            logger.debug(f"读取缺陷截图 base64 失败 (降级为纯文本分析): {ie}")

    result = agent._call_llm(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        base64_image=base64_img,
        model=model
    )

    # 提取结构化数据
    category = result.get("category", "技术定性待定")
    summary = result.get("summary", "暂无简要概述")
    root_cause = result.get("root_cause_analysis", result.get("root_cause", "暂无机理解析"))
    env_diff = result.get("environment_diff", "暂无跨环境差异分析")
    solution = result.get("solution_patch", result.get("troubleshooting", "暂无代码补丁"))
    assignee = result.get("recommended_assignee", "陈贻雄 (前端)")

    formatted_md = result.get("formatted_markdown")
    if not formatted_md or len(formatted_md.strip()) < 50:
        # 兜底生成高质量 Markdown
        formatted_md = (
            f"### 🤖 AI 架构师缺陷根因诊断与研发整改指引\n\n"
            f"**【核心技术定性】**：{category}\n\n"
            f"**【案发速览】**：{summary}\n\n"
            f"#### 1. 底层案发机理深度剖析\n"
            f"{root_cause}\n\n"
            f"#### 2. 跨环境与多机差异破局（为何部分电脑不复现）\n"
            f"{env_diff}\n\n"
            f"#### 3. 推荐代码级修复补丁 (Copy-Paste Ready)\n"
            f"```javascript\n"
            f"{solution}\n"
            f"```\n\n"
            f"#### 4. 责任归属与联调指引\n"
            f"建议指派至：**{assignee}**"
        )

    return formatted_md, result


def markdown_to_zentao_rich_html(md_text: str) -> str:
    """
    将 AI 分析的 Markdown 文本转换为适合禅道富文本编辑器的现代化内联样式 HTML
    """
    if not md_text or not md_text.strip():
        return "<p><em>暂无 AI 归因研判内容</em></p>"

    try:
        import markdown

        # 预处理：将 markdown 转为标准 html
        html_body = markdown.markdown(
            md_text,
            extensions=["fenced_code", "tables", "nl2br"]
        )

        # 注入优雅且兼容禅道的行内 CSS
        # 1. 替换标题样式
        html_body = re.sub(
            r"<h3>(.*?)</h3>",
            r"<h3 style='margin:12px 0 8px 0;font-size:16px;color:#1e3a8a;border-bottom:1px solid #bfdbfe;padding-bottom:4px;'>\1</h3>",
            html_body
        )
        html_body = re.sub(
            r"<h4>(.*?)</h4>",
            r"<h4 style='margin:10px 0 6px 0;font-size:14px;color:#1d4ed8;border-left:3px solid #3b82f6;padding-left:6px;'>\1</h4>",
            html_body
        )

        # 2. 保护 <pre><code> 块，防止内嵌 code 被重复加行内样式
        pre_blocks = []
        def stash_pre(m):
            idx = len(pre_blocks)
            attrs = m.group(1) or ""
            code_text = m.group(2)
            styled_pre = (
                f"<pre style='background:#1e293b;color:#f8fafc;padding:12px;border-radius:6px;"
                f"font-family:Consolas, Monaco, monospace;font-size:12px;line-height:1.5;"
                f"overflow-x:auto;margin:8px 0;'><code{attrs}>{code_text}</code></pre>"
            )
            pre_blocks.append(styled_pre)
            return f"__PRE_CODE_BLOCK_{idx}__"

        html_body = re.sub(r"<pre><code(.*?)>(.*?)</code></pre>", stash_pre, html_body, flags=re.DOTALL)

        # 3. 替换独立的行内 <code> 样式
        html_body = re.sub(
            r"<code>(.*?)</code>",
            r"<code style='background:#e2e8f0;color:#0f172a;padding:2px 5px;border-radius:3px;font-family:monospace;font-size:12px;'>\1</code>",
            html_body
        )

        # 4. 还原预格式化代码块
        for i, block in enumerate(pre_blocks):
            html_body = html_body.replace(f"__PRE_CODE_BLOCK_{i}__", block)

        # 5. 替换引用 blockquote 样式
        html_body = re.sub(
            r"<blockquote>(.*?)</blockquote>",
            r"<blockquote style='background:#f8fafc;border-left:4px solid #94a3b8;margin:8px 0;padding:8px 12px;color:#475569;'>\1</blockquote>",
            html_body,
            flags=re.DOTALL
        )

        styled_wrapper = (
            f"<div class='ai-diagnosis-container' style='background:#f8fafc;border:1px solid #e2e8f0;border-left:4px solid #2563eb;border-radius:6px;padding:14px 16px;color:#1e293b;font-size:13px;line-height:1.7;'>"
            f"{html_body}"
            f"</div>"
        )
        return styled_wrapper

    except Exception as e:
        logger.warning(f"Markdown 转换禅道 HTML 异常: {e}，回退简单替换")
        escaped = md_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")
        return f"<div style='background:#eff6ff;color:#1e3a8a;padding:12px;border-radius:6px;'>{escaped}</div>"
