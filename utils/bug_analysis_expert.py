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
    """构建精简、精准、直击根因的研发级初诊 Prompt"""
    system_prompt = (
        "你是一个资深客户端/全栈测试诊断专家，需要将自动化捕获的缺陷提炼为【极简精准】的研发排查结论，推送至禅道。\n"
        "【核心原则】：开发只看干货！总字数严格控制在 200 字以内，严禁长篇大论、严禁教科书式原理解释、严禁写‘跨环境/多机差异分析’、严禁贴大段泛泛伪代码、严禁主观臆测。\n"
        "【实事求是】：\n"
        "- 404/500/业务错误：直接写出报错接口方法名、URL、HTTP/业务状态码及核心报错原因。\n"
        "- 前端 JS 崩溃：直接写出报错属性/方法及空值/渲染时机问题。\n"
        "- 视觉/数据不匹配：直接写出界面值与接口原始值的差异点。\n\n"
        "你必须且只能返回一个合法的 JSON 对象，包含以下 4 个精简字段：\n"
        "{\n"
        '  "category": "一句话技术定性（如：【后端】MySQL 排序规则冲突 / 【前端】未判空读取 offsetWidth）",\n'
        '  "root_cause": "1~3条直接事实（用简短要点列出问题接口名/URL/报错堆栈/异常字段，每条不超过1行）",\n'
        '  "fix_action": "1~2句具体可执行的修改建议（直接说改哪个接口/字段/判空逻辑）",\n'
        '  "recommended_assignee": "陈贻雄 (前端) 或 梅本霞 (后端) 或 李云骢 (数据接入)"\n'
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
        "当前页面访问协议为 HTTP 真实 IP 域名（非安全上下文，仅在涉及剪贴板、原生硬件交互等明确依赖 Secure Context 的高级 Web API 报错时参考，其他常规网络请求/Vue组件错误切勿强行套用）。"
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

    # 提取精简结构化字段并统一排版
    category = str(result.get("category") or "技术定性待定").strip()
    root_cause = str(result.get("root_cause") or result.get("root_cause_analysis") or result.get("summary") or "暂无").strip()
    fix_action = str(result.get("fix_action") or result.get("solution_patch") or "请结合案发堆栈与截图定位处理").strip()
    assignee = str(result.get("recommended_assignee") or "陈贻雄 (前端)").strip()

    formatted_md = (
        f"**【问题定性】** {category}\n\n"
        f"**【直接根因】**\n{root_cause}\n\n"
        f"**【修复建议】** {fix_action}\n\n"
        f"**【建议指派】** {assignee}"
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
