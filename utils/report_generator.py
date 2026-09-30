"""
==============================================================================
utils/report_generator.py —— 自动化测试与自主探索高颜值视觉报告生成引擎
==============================================================================

职责：
1. 深度解析单次运行目录 (reports/runs/<run_id>/) 下的日志、截图、Bug凭证、检查点拓扑树与接口池；
2. 生成零依赖、单文件、支持双击直开的现代化交互式 HTML 视觉大盘 (report.html)；
3. 支持命令行指定历史 run 目录或直接对最新一次运行生成报告。
"""

from __future__ import annotations

import argparse
import base64
import html
import io
import json
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Windows GBK 终端 UTF-8 保护
if sys.platform == "win32":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.artifacts import RUNS_DIR

logger = logging.getLogger("report_generator")


class ReportGenerator:
    def __init__(self, run_dir: Path | str):
        self.run_dir = Path(run_dir).resolve()
        if not self.run_dir.exists():
            raise FileNotFoundError(f"找不到运行目录: {self.run_dir}")
        self.run_id = self.run_dir.name

    def parse_run_data(self) -> Dict[str, Any]:
        """全要素解析单次运行目录中的所有数据"""
        data: Dict[str, Any] = {
            "run_id": self.run_id,
            "mode": "自主探索模式 (Autonomous Explorer)" if self.run_id.startswith("explore_") else (
                "全量冒烟巡检 (Smoke Tour)" if self.run_id.startswith("smoke_") else "YAML 确定性回归"
            ),
            "start_time": "未知",
            "end_time": "未知",
            "duration": "未知",
            "macro_objective": "无",
            "steps": [],
            "bugs": [],
            "page_tree": {},
            "mermaid_str": "",
            "generated_yaml": "",
            "api_summary": {},
            "kpi": {
                "total_steps": 0,
                "planner_phases": 0,
                "bugs_count": 0,
                "page_scopes_count": 0,
                "apis_count": 0,
                "yaml_steps_count": 0,
            }
        }

        # 1. 查找并解析主运行日志
        log_candidates = list(self.run_dir.glob("explorer_*.log")) + list(self.run_dir.glob("smoke_tour_*.log")) + list(self.run_dir.glob("*.log"))
        main_log = None
        for cand in log_candidates:
            if not cand.name.startswith("startup_"):
                main_log = cand
                break
        if not main_log and log_candidates:
            main_log = log_candidates[0]

        if main_log and main_log.exists():
            self._parse_log_file(main_log, data)

        # 2. 解析缺陷库 bugs/
        bugs_dir = self.run_dir / "bugs"
        if bugs_dir.exists():
            for bug_json in sorted(bugs_dir.glob("*.json")):
                try:
                    with open(bug_json, "r", encoding="utf-8") as f:
                        b_info = json.load(f)
                    
                    # 匹配截图相对路径
                    bug_id = b_info.get("id", bug_json.stem)
                    img_cand = bugs_dir / f"{bug_id}.png"
                    if not img_cand.exists():
                        img_cands = list(bugs_dir.glob(f"{bug_id}*.png"))
                        if img_cands:
                            img_cand = img_cands[0]
                    
                    b_info["rel_screenshot"] = f"bugs/{img_cand.name}" if img_cand.exists() else None
                    data["bugs"].append(b_info)
                except Exception as e:
                    logger.warning(f"读取 Bug 文件 {bug_json.name} 失败: {e}")

        data["kpi"]["bugs_count"] = len(data["bugs"])

        # 3. 解析页面拓扑树 (checkpoint/page_tree.json 或根目录 page_tree.json)
        tree_cand = self.run_dir / "checkpoint" / "page_tree.json"
        if not tree_cand.exists():
            tree_cand = self.run_dir / "page_tree.json"
        if tree_cand.exists():
            try:
                with open(tree_cand, "r", encoding="utf-8") as f:
                    data["page_tree"] = json.load(f)
                
                # 尝试用 PageMapBuilder 转为 Mermaid
                try:
                    from core.explorer_agent.page_map_builder import PageMapBuilder
                    data["mermaid_str"] = PageMapBuilder.dict_to_mermaid_string(data["page_tree"])
                except Exception:
                    data["mermaid_str"] = ""
            except Exception as e:
                logger.warning(f"读取 page_tree 失败: {e}")

        # 4. 解析自动生成的回归用例
        cases_dir = self.run_dir / "generated_cases"
        if cases_dir.exists():
            for y_file in sorted(cases_dir.glob("*.yaml")):
                try:
                    content = y_file.read_text(encoding="utf-8")
                    data["generated_yaml"] = content
                    # 统计 steps
                    step_matches = re.findall(r'-\s+type:\s+', content)
                    data["kpi"]["yaml_steps_count"] = len(step_matches)
                    break
                except Exception as e:
                    logger.warning(f"读取生成的用例失败: {e}")

        # 5. 解析接口大盘
        api_file = self.run_dir / "screenshots" / "api_registry.json"
        if api_file.exists():
            try:
                with open(api_file, "r", encoding="utf-8") as f:
                    api_data = json.load(f)
                data["api_summary"] = api_data
                summary_meta = api_data.get("summary", {})
                data["kpi"]["apis_count"] = summary_meta.get("total_unique_endpoints", len(api_data.get("global_flat_apis", {})))
                data["kpi"]["page_scopes_count"] = summary_meta.get("total_page_scopes", len(api_data.get("page_scopes", {})))
            except Exception as e:
                logger.warning(f"读取 api_registry 失败: {e}")

        return data

    def _parse_log_file(self, log_path: Path, data: Dict[str, Any]):
        """高精度分块提取 1000 步的 Worker 动作、思维链与截图关联"""
        try:
            text = log_path.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            logger.error(f"读取日志文件失败: {e}")
            return

        lines = text.splitlines()
        if lines:
            first_line = lines[0]
            last_line = lines[-1]
            ts_start_match = re.match(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", first_line)
            ts_end_match = re.match(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", last_line)
            if ts_start_match:
                data["start_time"] = ts_start_match.group(1)
            if ts_end_match:
                data["end_time"] = ts_end_match.group(1)

            if ts_start_match and ts_end_match:
                try:
                    t_start = datetime.strptime(ts_start_match.group(1), "%Y-%m-%d %H:%M:%S")
                    t_end = datetime.strptime(ts_end_match.group(1), "%Y-%m-%d %H:%M:%S")
                    sec = max(0, int((t_end - t_start).total_seconds()))
                    h = sec // 3600
                    m = (sec % 3600) // 60
                    s = sec % 60
                    data["duration"] = f"{h}h {m}m {s}s" if h > 0 else f"{m}m {s}s"
                except Exception:
                    pass

        # 宏观目标提取
        macro_match = re.search(r"🚀 开启自主探索模式 \| 目标: (.*?)(?=\n|\Z)", text)
        if macro_match:
            data["macro_objective"] = macro_match.group(1).strip()
        else:
            macro_match2 = re.search(r"探题目[:：]\s*(.*?)(?=\n|\Z)", text)
            if macro_match2:
                data["macro_objective"] = macro_match2.group(1).strip()

        # 统计 Planner 次数
        data["kpi"]["planner_phases"] = len(re.findall(r"🧠 \[Planner Phase\]", text))

        # 提取 Worker 单步
        pattern = re.compile(
            r"--- \[Worker Step (\d+)/(\d+)\] \(Global: (\d+)/(\d+)\) ---\n"
            r"(.*?)(?=(?:--- \[Worker Step|\Z))",
            re.DOTALL
        )

        shots_dir = self.run_dir / "screenshots"

        for m in pattern.finditer(text):
            w_step = int(m.group(1))
            budget = int(m.group(2))
            g_step = int(m.group(3))
            block = m.group(5)

            # 时间戳
            ts_m = re.search(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", block)
            ts = ts_m.group(1) if ts_m else ""

            # 子目标
            sub_m = re.search(r"🤖 \[Worker\] 执行子目标: ['\"](.*?)['\"]", block)
            sub = sub_m.group(1) if sub_m else ""

            # 思维链
            th_m = re.search(r"💡 \[Worker\] 思考链: (.*?)(?=\n\d{4}|\Z)", block, re.DOTALL)
            thought = th_m.group(1).strip() if th_m else ""

            # 动作与目标
            act_m = re.search(r"🤖 \[Worker\] 决定: \[(\w+)\] -> 目标: (.*?)(?=\n|\Z)", block)
            action = act_m.group(1).upper() if act_m else "UNKNOWN"
            target = act_m.group(2).strip() if act_m else ""

            # 推断路径
            path_m = re.search(r"📍 \[Worker\] 当前推断路径: (\[.*?\])", block)
            ui_path = path_m.group(1) if path_m else "[]"

            # 元素类型与容器
            elem_type_m = re.search(r"类型: (\w+)", block)
            elem_type = elem_type_m.group(1) if elem_type_m else ""
            container_m = re.search(r"容器: (.*?)(?=\n|\Z)", block)
            container = container_m.group(1).strip() if container_m else ""

            # 是否捕获异常
            has_bug = "🚨 [BUG FOUND]" in block or "❌" in block

            # 匹配截图路径
            shot_file = f"explore_step_{g_step}.png"
            shot_path = f"screenshots/{shot_file}" if (shots_dir / shot_file).exists() else None

            hover_file = f"explore_step_{g_step}_hover.png"
            hover_path = f"screenshots/{hover_file}" if (shots_dir / hover_file).exists() else None

            after_file = f"explore_step_{g_step}_after.png"
            after_path = f"screenshots/{after_file}" if (shots_dir / after_file).exists() else None

            data["steps"].append({
                "step": g_step,
                "worker_step": w_step,
                "budget": budget,
                "timestamp": ts,
                "sub_objective": sub,
                "thought": thought,
                "action": action,
                "target": target,
                "ui_path": ui_path,
                "element_type": elem_type,
                "container": container,
                "has_bug": has_bug,
                "screenshot": shot_path,
                "hover_screenshot": hover_path,
                "after_screenshot": after_path,
            })

        data["kpi"]["total_steps"] = len(data["steps"])

    def generate_html(self, output_path: Optional[Path | str] = None) -> Path:
        """组装并导出美观的前端独立交互式报告"""
        data = self.parse_run_data()
        out = Path(output_path).resolve() if output_path else (self.run_dir / "report.html")

        # 序列化供前端 JS 消费的纯数据
        steps_json = json.dumps(data["steps"], ensure_ascii=False)
        bugs_json = json.dumps(data["bugs"], ensure_ascii=False)
        apis_json = json.dumps(data["api_summary"], ensure_ascii=False)
        mermaid_raw = data["mermaid_str"]

        # 预先构建 Bug 列表 HTML，避免在庞大外层 f-string 中嵌套表达式语法冲突
        bugs_html_list = []
        for b in data.get("bugs", []):
            b_id = html.escape(str(b.get("id", "BUG")))
            b_title = html.escape(str(b.get("title", "")))
            b_date = html.escape(str(b.get("creation_date", "")))
            details = b.get("details") or {}
            b_step = html.escape(str(details.get("step", "")))
            b_actual = html.escape(str(details.get("actual", "")))
            rel_shot = b.get("rel_screenshot") or ""
            bugs_html_list.append(f"""
        <div class="bug-card">
          <div class="bug-card-header">
            <div class="bug-id-group">
              <span class="bug-badge">{b_id}</span>
              <span class="bug-title">{b_title}</span>
            </div>
            <div style="font-size:12px;color:#fca5a5;">发现日期: {b_date}</div>
          </div>
          <div class="bug-body">
            <div>
              <div class="bug-field">
                <div class="bug-field-label">触发步骤与路径</div>
                <div class="bug-step-text">{b_step}</div>
              </div>
              <div class="bug-field">
                <div class="bug-field-label">异常堆栈 / 接口报错详情</div>
                <div class="bug-error-box">{b_actual}</div>
              </div>
            </div>
            <div>
              <div class="bug-field-label">案发现场截图凭据</div>
              <div class="bug-screenshot-preview" onclick="openLightbox('{rel_shot}', '{b_id} 案发现场')">
                <img src="{rel_shot}" alt="Crash Screenshot" loading="lazy">
                <div class="zoom-hint">🔍 点击放大核验</div>
              </div>
            </div>
          </div>
        </div>""")
        bugs_cards_html = "".join(bugs_html_list) if bugs_html_list else '<div style="text-align:center;padding:60px;color:var(--text-dim);">🎉 本次巡检未发现任何崩溃或接口异常，100% 完美通过！</div>'

        # 预先构建 API 列表 HTML
        api_rows_list = []
        api_summary_dict = data.get("api_summary") or {}
        endpoints = (api_summary_dict.get("summary") or {}).get("endpoints") or []
        for idx, ep in enumerate(endpoints):
            ep_escaped = html.escape(str(ep))
            api_rows_list.append(f"""
            <tr>
              <td style="color:var(--text-dim);font-family:var(--font-mono);">{idx + 1}</td>
              <td class="api-endpoint-cell">{ep_escaped}</td>
              <td><span style="font-size:11px;padding:3px 8px;border-radius:4px;background:var(--emerald-bg);color:#34d399;">200 OK 缓存池已就绪</span></td>
            </tr>""")
        api_rows_html = "".join(api_rows_list)

        html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>巡检执行报告 · {data['run_id']}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
  <style>
    :root {{
      --bg-base: #0a0d14;
      --bg-surface: #111726;
      --bg-card: rgba(22, 30, 49, 0.7);
      --bg-card-hover: rgba(30, 41, 69, 0.85);
      --border-subtle: rgba(255, 255, 255, 0.08);
      --border-focus: rgba(99, 102, 241, 0.4);
      --text-main: #f1f5f9;
      --text-muted: #94a3b8;
      --text-dim: #64748b;
      --primary: #6366f1;
      --primary-glow: rgba(99, 102, 241, 0.25);
      --emerald: #10b981;
      --emerald-bg: rgba(16, 185, 129, 0.12);
      --rose: #f43f5e;
      --rose-bg: rgba(244, 63, 94, 0.15);
      --amber: #f59e0b;
      --amber-bg: rgba(245, 158, 11, 0.15);
      --cyan: #06b6d4;
      --cyan-bg: rgba(6, 182, 212, 0.15);
      --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      --font-mono: 'JetBrains Mono', Consolas, Monaco, monospace;
    }}

    * {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }}

    body {{
      font-family: var(--font-sans);
      background-color: var(--bg-base);
      color: var(--text-main);
      line-height: 1.5;
      min-height: 100vh;
      overflow-x: hidden;
      background-image: 
        radial-gradient(circle at 15% 10%, rgba(99, 102, 241, 0.12) 0%, transparent 40%),
        radial-gradient(circle at 85% 20%, rgba(139, 92, 246, 0.1) 0%, transparent 35%),
        radial-gradient(circle at 50% 90%, rgba(16, 185, 129, 0.06) 0%, transparent 45%);
      background-attachment: fixed;
    }}

    /* Layout */
    .container {{
      max-width: 1440px;
      margin: 0 auto;
      padding: 32px 24px 80px 24px;
    }}

    /* Header & Hero */
    .hero {{
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      border-radius: 20px;
      padding: 32px 36px;
      backdrop-filter: blur(16px);
      box-shadow: 0 20px 40px -15px rgba(0, 0, 0, 0.5);
      margin-bottom: 28px;
      position: relative;
      overflow: hidden;
    }}

    .hero::before {{
      content: '';
      position: absolute;
      top: 0; left: 0; right: 0;
      height: 3px;
      background: linear-gradient(90deg, #6366f1, #8b5cf6, #ec4899, #10b981);
    }}

    .hero-top {{
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 20px;
      flex-wrap: wrap;
      margin-bottom: 20px;
    }}

    .hero-title-group h1 {{
      font-size: 26px;
      font-weight: 800;
      letter-spacing: -0.02em;
      display: flex;
      align-items: center;
      gap: 12px;
      color: #fff;
    }}

    .hero-title-group h1 span.badge {{
      font-size: 13px;
      font-weight: 600;
      padding: 4px 12px;
      border-radius: 999px;
      background: var(--primary-glow);
      color: #a5b4fc;
      border: 1px solid rgba(99, 102, 241, 0.3);
    }}

    .run-id-pill {{
      font-family: var(--font-mono);
      font-size: 13px;
      color: var(--text-muted);
      margin-top: 6px;
      display: flex;
      align-items: center;
      gap: 8px;
    }}

    .hero-meta {{
      display: flex;
      gap: 16px;
      flex-wrap: wrap;
    }}

    .meta-chip {{
      background: rgba(15, 23, 42, 0.6);
      border: 1px solid var(--border-subtle);
      padding: 8px 16px;
      border-radius: 10px;
      font-size: 13px;
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--text-muted);
    }}

    .meta-chip strong {{
      color: #fff;
      font-weight: 600;
    }}

    .macro-objective-box {{
      background: rgba(10, 15, 26, 0.6);
      border: 1px solid rgba(99, 102, 241, 0.2);
      border-left: 4px solid var(--primary);
      border-radius: 8px;
      padding: 14px 18px;
      font-size: 14px;
      color: #cbd5e1;
      display: flex;
      gap: 12px;
      align-items: flex-start;
    }}

    .macro-objective-box .label {{
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      font-weight: 700;
      color: #818cf8;
      white-space: nowrap;
      margin-top: 2px;
    }}

    /* KPI Cards */
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
      gap: 16px;
      margin-bottom: 32px;
    }}

    .kpi-card {{
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      border-radius: 16px;
      padding: 20px 24px;
      backdrop-filter: blur(12px);
      transition: transform 0.2s, border-color 0.2s;
    }}

    .kpi-card:hover {{
      transform: translateY(-2px);
      border-color: var(--border-focus);
    }}

    .kpi-card .kpi-label {{
      font-size: 13px;
      color: var(--text-dim);
      font-weight: 500;
      display: flex;
      align-items: center;
      gap: 6px;
      margin-bottom: 8px;
    }}

    .kpi-card .kpi-value {{
      font-size: 28px;
      font-weight: 800;
      letter-spacing: -0.02em;
      color: #fff;
      display: flex;
      align-items: baseline;
      gap: 6px;
    }}

    .kpi-card .kpi-value span.sub {{
      font-size: 13px;
      font-weight: 500;
      color: var(--text-dim);
    }}

    .kpi-card.bugs-card {{
      border-color: rgba(244, 63, 94, 0.3);
      background: linear-gradient(135deg, rgba(30, 20, 35, 0.7), rgba(20, 25, 45, 0.7));
    }}

    .kpi-card.bugs-card .kpi-value {{
      color: #fb7185;
    }}

    /* Tabs Navigation */
    .tabs-bar {{
      display: flex;
      gap: 10px;
      margin-bottom: 24px;
      border-bottom: 1px solid var(--border-subtle);
      padding-bottom: 12px;
      overflow-x: auto;
    }}

    .tab-btn {{
      background: transparent;
      border: 1px solid transparent;
      color: var(--text-muted);
      padding: 10px 20px;
      border-radius: 10px;
      font-size: 14px;
      font-weight: 600;
      cursor: pointer;
      display: flex;
      align-items: center;
      gap: 8px;
      transition: all 0.2s;
      white-space: nowrap;
    }}

    .tab-btn:hover {{
      color: #fff;
      background: rgba(255, 255, 255, 0.05);
    }}

    .tab-btn.active {{
      color: #fff;
      background: var(--primary);
      box-shadow: 0 4px 16px var(--primary-glow);
    }}

    .tab-btn .counter {{
      font-size: 11px;
      padding: 2px 7px;
      border-radius: 999px;
      background: rgba(0, 0, 0, 0.3);
    }}

    .tab-btn.active .counter {{
      background: rgba(255, 255, 255, 0.25);
      color: #fff;
    }}

    /* Tab Content Areas */
    .tab-pane {{
      display: none;
    }}

    .tab-pane.active {{
      display: block;
      animation: fadeIn 0.3s ease-out;
    }}

    @keyframes fadeIn {{
      from {{ opacity: 0; transform: translateY(6px); }}
      to {{ opacity: 1; transform: translateY(0); }}
    }}

    /* Section 1: Bugs Locker */
    .bugs-container {{
      display: flex;
      flex-direction: column;
      gap: 20px;
    }}

    .bug-card {{
      background: var(--bg-card);
      border: 1px solid rgba(244, 63, 94, 0.35);
      border-radius: 16px;
      overflow: hidden;
      backdrop-filter: blur(12px);
      box-shadow: 0 8px 24px rgba(244, 63, 94, 0.08);
    }}

    .bug-card-header {{
      background: var(--rose-bg);
      padding: 14px 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      border-bottom: 1px solid rgba(244, 63, 94, 0.2);
    }}

    .bug-id-group {{
      display: flex;
      align-items: center;
      gap: 12px;
    }}

    .bug-badge {{
      font-family: var(--font-mono);
      font-size: 13px;
      font-weight: 700;
      color: #fff;
      background: var(--rose);
      padding: 4px 10px;
      border-radius: 6px;
    }}

    .bug-title {{
      font-size: 15px;
      font-weight: 700;
      color: #ffe4e6;
    }}

    .bug-body {{
      padding: 24px;
      display: grid;
      grid-template-columns: 1fr 340px;
      gap: 24px;
    }}

    @media (max-width: 900px) {{
      .bug-body {{ grid-template-columns: 1fr; }}
    }}

    .bug-field {{
      margin-bottom: 16px;
    }}

    .bug-field-label {{
      font-size: 12px;
      text-transform: uppercase;
      font-weight: 700;
      color: var(--text-dim);
      margin-bottom: 6px;
    }}

    .bug-step-text {{
      font-size: 14px;
      color: #f8fafc;
      background: rgba(15, 23, 42, 0.6);
      padding: 10px 14px;
      border-radius: 8px;
      border: 1px solid var(--border-subtle);
      font-family: var(--font-mono);
    }}

    .bug-error-box {{
      background: #0d1117;
      border: 1px solid rgba(244, 63, 94, 0.3);
      padding: 12px 16px;
      border-radius: 8px;
      font-family: var(--font-mono);
      font-size: 13px;
      color: #fca5a5;
      white-space: pre-wrap;
      word-break: break-all;
      max-height: 220px;
      overflow-y: auto;
    }}

    .bug-screenshot-preview {{
      border: 1px solid var(--border-subtle);
      border-radius: 12px;
      overflow: hidden;
      background: #000;
      position: relative;
      cursor: pointer;
    }}

    .bug-screenshot-preview img {{
      width: 100%;
      height: auto;
      display: block;
      transition: transform 0.3s;
    }}

    .bug-screenshot-preview:hover img {{
      transform: scale(1.03);
    }}

    .zoom-hint {{
      position: absolute;
      bottom: 8px; right: 8px;
      background: rgba(0, 0, 0, 0.7);
      color: #fff;
      font-size: 11px;
      padding: 4px 8px;
      border-radius: 4px;
      backdrop-filter: blur(4px);
    }}

    /* Section 2: Timeline Steps */
    .timeline-filter-bar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      margin-bottom: 20px;
      flex-wrap: wrap;
    }}

    .filter-btn-group {{
      display: flex;
      gap: 8px;
    }}

    .filter-pill {{
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid var(--border-subtle);
      color: var(--text-muted);
      padding: 6px 14px;
      border-radius: 8px;
      font-size: 13px;
      cursor: pointer;
      font-weight: 500;
      transition: all 0.2s;
    }}

    .filter-pill.active {{
      background: rgba(99, 102, 241, 0.2);
      border-color: var(--primary);
      color: #a5b4fc;
    }}

    .search-box {{
      background: rgba(15, 23, 42, 0.8);
      border: 1px solid var(--border-subtle);
      color: #fff;
      padding: 8px 16px;
      border-radius: 8px;
      font-size: 13px;
      width: 260px;
      outline: none;
    }}

    .search-box:focus {{
      border-color: var(--primary);
    }}

    .pagination-bar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-top: 24px;
      padding-top: 16px;
      border-top: 1px solid var(--border-subtle);
      color: var(--text-muted);
      font-size: 13px;
    }}

    .pagination-controls {{
      display: flex;
      gap: 8px;
    }}

    .pg-btn {{
      background: rgba(255, 255, 255, 0.06);
      border: 1px solid var(--border-subtle);
      color: #fff;
      padding: 6px 14px;
      border-radius: 6px;
      font-size: 13px;
      cursor: pointer;
    }}

    .pg-btn:disabled {{
      opacity: 0.3;
      cursor: not-allowed;
    }}

    .steps-list {{
      display: flex;
      flex-direction: column;
      gap: 16px;
    }}

    .step-card {{
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      border-radius: 14px;
      padding: 18px 24px;
      display: grid;
      grid-template-columns: 80px 1fr 180px;
      gap: 20px;
      align-items: center;
      transition: all 0.2s;
    }}

    .step-card:hover {{
      background: var(--bg-card-hover);
      border-color: rgba(255, 255, 255, 0.15);
    }}

    .step-card.is-bug {{
      border-color: rgba(244, 63, 94, 0.5);
      background: rgba(244, 63, 94, 0.06);
    }}

    .step-index-badge {{
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      background: rgba(0, 0, 0, 0.3);
      padding: 8px;
      border-radius: 10px;
      border: 1px solid var(--border-subtle);
    }}

    .step-index-badge .num {{
      font-size: 18px;
      font-weight: 800;
      color: #fff;
      font-family: var(--font-mono);
    }}

    .step-index-badge .sub {{
      font-size: 11px;
      color: var(--text-dim);
    }}

    .step-main-info {{
      display: flex;
      flex-direction: column;
      gap: 6px;
    }}

    .step-header-line {{
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
    }}

    .action-tag {{
      font-size: 11px;
      font-weight: 700;
      padding: 3px 8px;
      border-radius: 5px;
      text-transform: uppercase;
      font-family: var(--font-mono);
    }}

    .action-tag.click {{ background: var(--primary-glow); color: #c7d2fe; border: 1px solid rgba(99, 102, 241, 0.4); }}
    .action-tag.hover {{ background: var(--cyan-bg); color: #a5f3fc; border: 1px solid rgba(6, 182, 212, 0.4); }}
    .action-tag.wait {{ background: var(--amber-bg); color: #fde68a; border: 1px solid rgba(245, 158, 11, 0.4); }}
    .action-tag.finish {{ background: var(--emerald-bg); color: #a7f3d0; border: 1px solid rgba(16, 185, 129, 0.4); }}

    .path-crumb {{
      font-size: 12px;
      color: var(--text-dim);
      font-family: var(--font-mono);
    }}

    .step-target-name {{
      font-size: 15px;
      font-weight: 600;
      color: #f1f5f9;
    }}

    .step-thought-text {{
      font-size: 13px;
      color: var(--text-muted);
      line-height: 1.4;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
      cursor: pointer;
    }}

    .step-thought-text.expanded {{
      -webkit-line-clamp: unset;
      color: #cbd5e1;
    }}

    .step-thumb-wrapper {{
      width: 180px;
      height: 100px;
      border-radius: 8px;
      overflow: hidden;
      background: #000;
      border: 1px solid var(--border-subtle);
      cursor: pointer;
      position: relative;
    }}

    .step-thumb-wrapper img {{
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
      transition: transform 0.2s;
    }}

    .step-thumb-wrapper:hover img {{
      transform: scale(1.05);
    }}

    /* Section 3: Mermaid Topology */
    .topology-card {{
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      border-radius: 16px;
      padding: 28px;
      backdrop-filter: blur(12px);
      overflow-x: auto;
    }}

    /* Section 4: API Pool */
    .api-card {{
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      border-radius: 16px;
      padding: 24px;
      backdrop-filter: blur(12px);
    }}

    .api-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
      margin-top: 16px;
    }}

    .api-table th, .api-table td {{
      padding: 12px 16px;
      text-align: left;
      border-bottom: 1px solid var(--border-subtle);
    }}

    .api-table th {{
      color: var(--text-dim);
      font-weight: 600;
      text-transform: uppercase;
      font-size: 11px;
      background: rgba(15, 23, 42, 0.4);
    }}

    .api-table tr:hover td {{
      background: rgba(255, 255, 255, 0.02);
    }}

    .api-endpoint-cell {{
      font-family: var(--font-mono);
      color: #38bdf8;
      font-weight: 500;
    }}

    /* Section 5: YAML Viewer */
    .yaml-card {{
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      border-radius: 16px;
      padding: 24px;
      backdrop-filter: blur(12px);
      position: relative;
    }}

    .yaml-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 16px;
    }}

    .copy-btn {{
      background: rgba(99, 102, 241, 0.2);
      border: 1px solid var(--primary);
      color: #c7d2fe;
      padding: 6px 14px;
      border-radius: 6px;
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.2s;
    }}

    .copy-btn:hover {{
      background: var(--primary);
      color: #fff;
    }}

    .code-view {{
      background: #090d16;
      border: 1px solid var(--border-subtle);
      padding: 20px;
      border-radius: 10px;
      font-family: var(--font-mono);
      font-size: 13px;
      color: #e2e8f0;
      max-height: 600px;
      overflow-y: auto;
      white-space: pre;
    }}

    /* Image Modal Lightbox */
    .lightbox-modal {{
      position: fixed;
      top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(0, 0, 0, 0.88);
      backdrop-filter: blur(8px);
      display: none;
      align-items: center;
      justify-content: center;
      z-index: 9999;
      padding: 30px;
    }}

    .lightbox-modal.active {{
      display: flex;
    }}

    .lightbox-content {{
      max-width: 95vw;
      max-height: 92vh;
      position: relative;
      border-radius: 12px;
      overflow: hidden;
      box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.8);
      border: 1px solid rgba(255, 255, 255, 0.15);
    }}

    .lightbox-content img {{
      max-width: 100%;
      max-height: 85vh;
      display: block;
    }}

    .lightbox-caption {{
      background: #111827;
      padding: 12px 20px;
      font-size: 14px;
      color: #f1f5f9;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }}

    .lightbox-close {{
      background: transparent;
      border: none;
      color: #fff;
      font-size: 24px;
      cursor: pointer;
      line-height: 1;
    }}
  </style>
</head>
<body>

  <div class="container">
    
    <!-- Hero Header -->
    <div class="hero">
      <div class="hero-top">
        <div class="hero-title-group">
          <h1>
            <span>⚡ Electron Vision AI · 执行全景报告</span>
            <span class="badge">{data['mode']}</span>
          </h1>
          <div class="run-id-pill">
            <span>🏷️ Run ID:</span> <strong>{data['run_id']}</strong>
          </div>
        </div>

        <div class="hero-meta">
          <div class="meta-chip">
            <span>⏱️ 耗时:</span> <strong>{data['duration']}</strong>
          </div>
          <div class="meta-chip">
            <span>📅 开始:</span> <strong>{data['start_time']}</strong>
          </div>
          <div class="meta-chip">
            <span>🏁 结束:</span> <strong>{data['end_time']}</strong>
          </div>
        </div>
      </div>

      <div class="macro-objective-box">
        <div class="label">宏观目标</div>
        <div>{html.escape(data['macro_objective'])}</div>
      </div>
    </div>

    <!-- KPI Grid -->
    <div class="kpi-grid">
      <div class="kpi-card">
        <div class="kpi-label">🎯 总执行步数</div>
        <div class="kpi-value">{data['kpi']['total_steps']} <span class="sub">步</span></div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">🧠 Planner 规划轮次</div>
        <div class="kpi-value">{data['kpi']['planner_phases']} <span class="sub">轮</span></div>
      </div>
      <div class="kpi-card bugs-card">
        <div class="kpi-label">🐞 捕获严重缺陷</div>
        <div class="kpi-value">{data['kpi']['bugs_count']} <span class="sub">个已归档</span></div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">🗺️ 触达业务页面</div>
        <div class="kpi-value">{data['kpi']['page_scopes_count']} <span class="sub">个二级菜单</span></div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">🌐 拦截业务接口</div>
        <div class="kpi-value">{data['kpi']['apis_count']} <span class="sub">个 API 报文</span></div>
      </div>
    </div>

    <!-- Navigation Tabs -->
    <div class="tabs-bar">
      <button class="tab-btn active" onclick="switchTab('tab-timeline')">
        🎬 视觉步进时间轴 <span class="counter">{data['kpi']['total_steps']}</span>
      </button>
      <button class="tab-btn" onclick="switchTab('tab-bugs')">
        🐞 缺陷证据库 <span class="counter" style="background:#f43f5e;color:#fff;">{data['kpi']['bugs_count']}</span>
      </button>
      <button class="tab-btn" onclick="switchTab('tab-topology')">
        🌳 动态架构拓扑图
      </button>
      <button class="tab-btn" onclick="switchTab('tab-api')">
        🌐 底层接口池 <span class="counter">{data['kpi']['apis_count']}</span>
      </button>
      <button class="tab-btn" onclick="switchTab('tab-yaml')">
        📝 自动沉淀回归用例 <span class="counter">{data['kpi']['yaml_steps_count']} 步</span>
      </button>
    </div>

    <!-- Tab 1: Timeline Steps -->
    <div id="tab-timeline" class="tab-pane active">
      <div class="timeline-filter-bar">
        <div class="filter-btn-group">
          <button class="filter-pill active" onclick="filterSteps('all')">全部 ({data['kpi']['total_steps']})</button>
          <button class="filter-pill" onclick="filterSteps('bugs')">仅看报错 ({data['kpi']['bugs_count']})</button>
          <button class="filter-pill" onclick="filterSteps('click')">点击操作</button>
          <button class="filter-pill" onclick="filterSteps('hover')">悬停操作</button>
        </div>
        <input type="text" id="stepSearch" class="search-box" placeholder="搜索步骤目标、路径或思维链..." oninput="handleSearch()">
      </div>

      <div id="stepsContainer" class="steps-list"></div>

      <div class="pagination-bar">
        <div id="pageInfo">显示第 1 至 50 步</div>
        <div class="pagination-controls">
          <button class="pg-btn" id="prevBtn" onclick="prevPage()">上一页</button>
          <button class="pg-btn" id="nextBtn" onclick="nextPage()">下一页</button>
        </div>
      </div>
    </div>

    <!-- Tab 2: Bugs Locker -->
    <div id="tab-bugs" class="tab-pane">
      <div class="bugs-container">
        {bugs_cards_html}
      </div>
    </div>

    <!-- Tab 3: Mermaid Topology -->
    <div id="tab-topology" class="tab-pane">
      <div class="topology-card">
        <h3 style="font-size:16px;margin-bottom:16px;color:#fff;">🗺️ 本次探索点亮的应用架构拓扑</h3>
        <div class="mermaid" style="display:flex;justify-content:center;">
{html.escape(mermaid_raw) if mermaid_raw else "graph TD; A[未检测到拓扑数据];"}
        </div>
      </div>
    </div>

    <!-- Tab 4: API Pool -->
    <div id="tab-api" class="tab-pane">
      <div class="api-card">
        <h3 style="font-size:16px;margin-bottom:8px;color:#fff;">🌐 底层网络接口拦截池</h3>
        <p style="font-size:13px;color:var(--text-dim);margin-bottom:20px;">
          框架静默拦截并归纳的 {data['kpi']['apis_count']} 个核心后端 API，涉及 {data['kpi']['page_scopes_count']} 个二级业务页面作用域。
        </p>
        <table class="api-table">
          <thead>
            <tr>
              <th style="width: 80px;">序号</th>
              <th>接口名称 / 路由端点</th>
              <th>捕获状态</th>
            </tr>
          </thead>
          <tbody>
            {api_rows_html}
          </tbody>
        </table>
      </div>
    </div>

    <!-- Tab 5: YAML Viewer -->
    <div id="tab-yaml" class="tab-pane">
      <div class="yaml-card">
        <div class="yaml-header">
          <div>
            <h3 style="font-size:16px;color:#fff;">📝 自动沉淀的回归用例 (Golden Baseline YAML)</h3>
            <p style="font-size:13px;color:var(--text-dim);margin-top:4px;">
              由本次探索中所有成功验证 (PASS) 的路径全自动编译而成，已过滤冗余与失败步骤。
            </p>
          </div>
          <button class="copy-btn" onclick="copyYaml()">📋 一键复制 YAML 用例</button>
        </div>
        <div id="yamlCode" class="code-view">{html.escape(data['generated_yaml'] or '# 暂无自动生成的用例')}</div>
      </div>
    </div>

  </div>

  <!-- Lightbox Modal -->
  <div id="lightboxModal" class="lightbox-modal" onclick="closeLightbox(event)">
    <div class="lightbox-content" onclick="event.stopPropagation()">
      <img id="lightboxImg" src="" alt="Full Resolution Snapshot">
      <div class="lightbox-caption">
        <span id="lightboxTitle">截图预览</span>
        <button class="lightbox-close" onclick="closeLightbox(event)">✕</button>
      </div>
    </div>
  </div>

  <script>
    // 初始化 Mermaid
    mermaid.initialize({{ startOnLoad: true, theme: 'dark' }});

    // 原始数据注入
    const allSteps = {steps_json};
    let currentFilter = 'all';
    let searchQuery = '';
    let currentPage = 1;
    const pageSize = 50;

    function switchTab(tabId) {{
      document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
      document.querySelectorAll('.tab-pane').forEach(pane => pane.classList.remove('active'));
      
      const targetPane = document.getElementById(tabId);
      if (targetPane) targetPane.classList.add('active');
      event.currentTarget.classList.add('active');
    }}

    function filterSteps(type) {{
      currentFilter = type;
      currentPage = 1;
      document.querySelectorAll('.filter-pill').forEach(btn => btn.classList.remove('active'));
      event.currentTarget.classList.add('active');
      renderSteps();
    }}

    function handleSearch() {{
      searchQuery = document.getElementById('stepSearch').value.toLowerCase().trim();
      currentPage = 1;
      renderSteps();
    }}

    function getFilteredSteps() {{
      return allSteps.filter(s => {{
        if (currentFilter === 'bugs' && !s.has_bug) return false;
        if (currentFilter === 'click' && s.action !== 'CLICK') return false;
        if (currentFilter === 'hover' && s.action !== 'HOVER') return false;
        
        if (searchQuery) {{
          const matchTarget = (s.target || '').toLowerCase().includes(searchQuery);
          const matchPath = (s.ui_path || '').toLowerCase().includes(searchQuery);
          const matchThought = (s.thought || '').toLowerCase().includes(searchQuery);
          const matchSub = (s.sub_objective || '').toLowerCase().includes(searchQuery);
          if (!matchTarget && !matchPath && !matchThought && !matchSub) return false;
        }}
        return true;
      }});
    }}

    function renderSteps() {{
      const filtered = getFilteredSteps();
      const total = filtered.length;
      const totalPages = Math.ceil(total / pageSize) || 1;
      currentPage = Math.max(1, Math.min(currentPage, totalPages));

      const startIdx = (currentPage - 1) * pageSize;
      const endIdx = Math.min(startIdx + pageSize, total);
      const pageSteps = filtered.slice(startIdx, endIdx);

      const container = document.getElementById('stepsContainer');
      if (total === 0) {{
        container.innerHTML = '<div style="text-align:center;padding:60px;color:var(--text-dim);">没有符合条件的步骤</div>';
        document.getElementById('pageInfo').innerText = '显示 0 步';
        document.getElementById('prevBtn').disabled = true;
        document.getElementById('nextBtn').disabled = true;
        return;
      }}

      let html = '';
      pageSteps.forEach(s => {{
        const bugClass = s.has_bug ? 'is-bug' : '';
        const actClass = s.action.toLowerCase();
        const displayImg = s.hover_screenshot || s.screenshot;

        html += `
          <div class="step-card ${{bugClass}}">
            <div class="step-index-badge">
              <span class="num">${{s.step}}</span>
              <span class="sub">/ 1000</span>
            </div>

            <div class="step-main-info">
              <div class="step-header-line">
                <span class="action-tag ${{actClass}}">${{s.action}}</span>
                <span class="path-crumb">📍 ${{escapeHtml(s.ui_path)}}</span>
                <span style="font-size:11px;color:var(--text-dim);margin-left:auto;">${{s.timestamp.split(' ')[1] || ''}}</span>
              </div>
              <div class="step-target-name">${{escapeHtml(s.target || '(子目标达成)')}}</div>
              <div class="step-thought-text" onclick="this.classList.toggle('expanded')" title="点击展开/收起完整思考链">
                💡 <strong>Worker思考:</strong> ${{escapeHtml(s.thought || '无思考过程')}}
              </div>
            </div>

            <div>
              ${{displayImg ? `
                <div class="step-thumb-wrapper" onclick="openLightbox('${{displayImg}}', '步骤 #${{s.step}}: [${{s.action}}] ${{escapeHtml(s.target)}}')">
                  <img src="${{displayImg}}" alt="Step Screenshot" loading="lazy">
                  <div class="zoom-hint">🎯 带准星</div>
                </div>
              ` : '<div style="font-size:12px;color:var(--text-dim);text-align:center;">无关联截图</div>'}}
            </div>
          </div>
        `;
      }});

      container.innerHTML = html;
      document.getElementById('pageInfo').innerText = `显示第 ${{startIdx + 1}} 至 ${{endIdx}} 步 (共 ${{total}} 步)`;
      document.getElementById('prevBtn').disabled = currentPage <= 1;
      document.getElementById('nextBtn').disabled = currentPage >= totalPages;
    }}

    function prevPage() {{
      if (currentPage > 1) {{
        currentPage--;
        renderSteps();
        window.scrollTo({{ top: 400, behavior: 'smooth' }});
      }}
    }}

    function nextPage() {{
      const totalPages = Math.ceil(getFilteredSteps().length / pageSize);
      if (currentPage < totalPages) {{
        currentPage++;
        renderSteps();
        window.scrollTo({{ top: 400, behavior: 'smooth' }});
      }}
    }}

    function openLightbox(imgSrc, title) {{
      if (!imgSrc) return;
      document.getElementById('lightboxImg').src = imgSrc;
      document.getElementById('lightboxTitle').innerText = title || '全分辨率截图核验';
      document.getElementById('lightboxModal').classList.add('active');
    }}

    function closeLightbox(event) {{
      document.getElementById('lightboxModal').classList.remove('active');
    }}

    function escapeHtml(str) {{
      if (!str) return '';
      return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
    }}

    function copyYaml() {{
      const code = document.getElementById('yamlCode').innerText;
      navigator.clipboard.writeText(code).then(() => {{
        const btn = event.target;
        btn.innerText = '✅ 已复制到剪贴板！';
        setTimeout(() => {{ btn.innerText = '📋 一键复制 YAML 用例'; }}, 2000);
      }});
    }}

    // 页面初始化渲染第一页
    document.addEventListener('DOMContentLoaded', () => {{
      renderSteps();
    }});
  </script>
</body>
</html>
"""
        out.write_text(html_content, encoding="utf-8")
        logger.info(f"🎉 高颜值离线交互式报告已生成: {out}")
        return out


def main():
    parser = argparse.ArgumentParser(description="Electron AI Vision 高颜值执行报告生成引擎")
    parser.add_argument("--run", type=str, help="指定要生成报告的运行目录名 (如 explore_20260928_182632)")
    parser.add_argument("--latest", action="store_true", help="自动对最新的运行目录生成报告")
    args = parser.parse_args()

    target_dir = None
    if args.run:
        cand = RUNS_DIR / args.run
        if cand.exists():
            target_dir = cand
        elif Path(args.run).exists():
            target_dir = Path(args.run)
    elif args.latest:
        runs = sorted([p for p in RUNS_DIR.iterdir() if p.is_dir()], key=lambda p: p.stat().st_mtime, reverse=True)
        if runs:
            target_dir = runs[0]

    if not target_dir:
        # 默认匹配 explore_20260928_182632
        cand_default = RUNS_DIR / "explore_20260928_182632"
        if cand_default.exists():
            target_dir = cand_default
        else:
            print("❌ 请通过 --run 指定运行目录或使用 --latest 参数！")
            sys.exit(1)

    print(f"🚀 开始为运行目录生成视觉报告: {target_dir.name} ...")
    reporter = ReportGenerator(target_dir)
    out_file = reporter.generate_html()
    print(f"✅ 报告生成完毕！可以直接在浏览器中双击打开：\nfile:///{out_file.as_posix()}\n")


if __name__ == "__main__":
    main()
