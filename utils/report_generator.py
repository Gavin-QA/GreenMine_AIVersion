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
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.paths import RUNS_DIR

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
            if not cand.name.startswith("startup_") and not cand.name.startswith("summary_"):
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
                
                try:
                    from core.explorer_agent.page_map_builder import PageMapBuilder
                    # 直接复用原生的纯 Markdown 组件拓扑树
                    data["mermaid_str"] = PageMapBuilder.render_markdown_tree(data["page_tree"])
                except Exception as e:
                    logger.warning(f"生成纯 Markdown 树失败: {e}")
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

        # 预期目标和限制
        limit_match = re.search(r"🛑 最大步数限制: (\d+) \| 最大时间: (\d+)分钟", text)
        if limit_match:
            data["kpi"]["max_steps"] = limit_match.group(1)
            data["kpi"]["max_time"] = f"{limit_match.group(2)} 分钟"
        else:
            data["kpi"]["max_steps"] = "-"
            data["kpi"]["max_time"] = "-"

        # 宏观目标提取
        macro_match = re.search(r"🚀 开启自主探索模式 \| 目标: (.*?)(?=\n|\Z)", text)
        if macro_match:
            data["macro_objective"] = macro_match.group(1).strip()
        else:
            macro_match2 = re.search(r"探题目[:：]\s*(.*?)(?=\n|\Z)", text)
            if macro_match2:
                data["macro_objective"] = macro_match2.group(1).strip()
            else:
                macro_match3 = re.search(r"▶️ 开始执行巡检用例: (.*?)(?=\n|\Z)", text)
                if macro_match3:
                    data["macro_objective"] = macro_match3.group(1).strip()

        # 统计 Planner 次数
        data["kpi"]["planner_phases"] = len(re.findall(r"🧠 \[Planner Phase\]", text))

        # 提取 Planner 和 Worker 单步
        shots_dir = self.run_dir / "screenshots"
        
        # 按 Planner Phase 切分
        planner_blocks = re.split(r"🧠 \[Planner Phase\] 开始规划", text)
        if len(planner_blocks) > 1:
            for p_idx, p_block in enumerate(planner_blocks[1:]):
                planner_phase_num = p_idx + 1
                
                # 解析 Planner 信息
                ts_m = re.search(r"^，当前进度.*?\n(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", p_block) or re.search(r"\n(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", p_block)
                ts = ts_m.group(1) if ts_m else ""
                
                prog_m = re.search(r"^，当前进度[：:]\s*(.*?)(?=\n)", p_block)
                global_prog = prog_m.group(1).strip() if prog_m else ""
                
                plan_shot_m = re.search(r"截图已保存至: .*?screenshots[\\/](plan_step_\d+\.png)", p_block)
                plan_shot_path = f"screenshots/{plan_shot_m.group(1)}" if plan_shot_m else None
                
                th_m = re.search(r"💡 \[Planner\] 思考链: (.*?)(?=\n\d{4}|\n💡|\Z)", p_block, re.DOTALL)
                thought = th_m.group(1).strip() if th_m else ""
                
                target_m = re.search(r"🎯 \[Planner\] 下达新任务: ['\"](.*?)['\"]", p_block)
                if not target_m:
                    target_m = re.search(r"🎯 最终状态: (.*?)(?=\n|\Z)", p_block)
                target = target_m.group(1).strip() if target_m else "未解析到明确目标"
                
                data["steps"].append({
                    "type": "planner",
                    "step": planner_phase_num,
                    "timestamp": ts,
                    "global_prog": global_prog,
                    "thought": thought,
                    "target": target,
                    "action": "PLANNER",
                    "screenshot": plan_shot_path,
                    "has_bug": False
                })
                
                # 提取此 Phase 下的所有 Worker Step
                pattern = re.compile(
                    r"--- \[Worker Step (\d+)/(\d+)\] \(Global: (\d+)/(\d+)\) ---\n"
                    r"(.*?)(?=(?:--- \[Worker Step|\Z))",
                    re.DOTALL
                )
                for m in pattern.finditer(p_block):
                    w_step = int(m.group(1))
                    budget = int(m.group(2))
                    g_step = int(m.group(3))
                    block = m.group(5)

                    w_ts_m = re.search(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", block)
                    w_ts = w_ts_m.group(1) if w_ts_m else ""
                    sub_m = re.search(r"🤖 \[Worker\] 执行子目标: ['\"](.*?)['\"]", block)
                    sub = sub_m.group(1) if sub_m else ""
                    w_th_m = re.search(r"💡 \[Worker\] 思考链: (.*?)(?=\n\d{4}|\Z)", block, re.DOTALL)
                    w_thought = w_th_m.group(1).strip() if w_th_m else ""
                    act_m = re.search(r"🤖 \[Worker\] 决定: \[(\w+)\] -> 目标: (.*?)(?=\n|\Z)", block)
                    w_action = act_m.group(1).upper() if act_m else "UNKNOWN"
                    w_target = act_m.group(2).strip() if act_m else ""
                    path_m = re.search(r"📍 \[Worker\] 当前推断路径: (\[.*?\])", block)
                    ui_path = path_m.group(1) if path_m else "[]"
                    has_bug = "🚨 [" in block
                    
                    shot_file = f"explore_step_{g_step}.png"
                    shot_path = f"screenshots/{shot_file}" if (shots_dir / shot_file).exists() else None
                    hover_file = f"explore_step_{g_step}_hover.png"
                    hover_path = f"screenshots/{hover_file}" if (shots_dir / hover_file).exists() else None
                    after_file = f"explore_step_{g_step}_after.png"
                    after_path = f"screenshots/{after_file}" if (shots_dir / after_file).exists() else None
                    
                    data["steps"].append({
                        "type": "worker",
                        "step": g_step,
                        "worker_step": w_step,
                        "budget": budget,
                        "timestamp": w_ts,
                        "sub_objective": sub,
                        "thought": w_thought,
                        "action": w_action,
                        "target": w_target,
                        "ui_path": ui_path,
                        "has_bug": has_bug,
                        "screenshot": shot_path,
                        "hover_screenshot": hover_path,
                        "after_screenshot": after_path
                    })

        if len(data["steps"]) == 0:
            # 尝试提取 YAML 单步
            yaml_pattern = re.compile(
                r"--- \[Step (\d+)/(\d+)\] 类型: (\w+) ---\n"
                r"(.*?)(?=(?:--- \[Step |\Z))",
                re.DOTALL
            )
            for m in yaml_pattern.finditer(text):
                g_step = int(m.group(1))
                budget = int(m.group(2))
                step_type = m.group(3)
                block = m.group(4)
                
                # 时间戳
                ts_m = re.search(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", block)
                ts = ts_m.group(1) if ts_m else ""
                
                # 子目标/指令提取
                sub = ""
                sub_m1 = re.search(r"(?:执行断言指令|寻找元素指令|对比两张图).*?: ['\"](.*)['\"]$", block, re.MULTILINE)
                sub_m2 = re.search(r"⏳ \[Vision Wait\] 开始智能等待.*?: (.*)$", block, re.MULTILINE)
                if sub_m1:
                    sub = sub_m1.group(1).strip()
                elif sub_m2:
                    sub = sub_m2.group(1).strip()
                else:
                    sub = f"YAML 操作: {step_type}"
                
                # 思维链
                th_m = re.search(r"💡 AI 思考链(?: \(纯视觉\))?: (.*?)(?=\n\d{4}|\Z)", block, re.DOTALL)
                thought = th_m.group(1).strip() if th_m else ""
                
                # 动作与目标
                action = step_type.upper()
                # 强制令 target 等于子目标指令，即 YAML prompt
                target = sub
                
                has_bug = "❌ 步骤" in block or "🐞 捕获到缺陷异常" in block or "断言失败" in block
                
                shot_path = None
                if shots_dir.exists():
                    crash_imgs = list(shots_dir.glob(f"*_step_{g_step}.png"))
                    if crash_imgs:
                        shot_path = f"screenshots/{crash_imgs[0].name}"

                data["steps"].append({
                    "step": g_step,
                    "worker_step": g_step,
                    "budget": budget,
                    "timestamp": ts,
                    "sub_objective": sub,
                    "thought": thought,
                    "action": action,
                    "target": target,
                    "ui_path": "YAML 用例脚本",
                    "element_type": "",
                    "container": "",
                    "has_bug": has_bug,
                    "screenshot": shot_path,
                    "hover_screenshot": None,
                    "after_screenshot": None,
                })


        data["kpi"]["total_steps"] = len(data["steps"])

    def generate_html(self, output_path: Optional[Path | str] = None, disable_push: bool = False) -> Path:
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

        # ====== 双模自适应逻辑 ======
        is_yaml_mode = data['run_id'].startswith("yaml_")
        hero_title = "⚡ Electron Vision AI · 自动化回归测试报告" if is_yaml_mode else "⚡ Electron Vision AI · 自主探索报告"
        badge_text = "YAML 强校验模式" if is_yaml_mode else "自主探索驱动"
        
        planner_kpi_style = "display:none;" if is_yaml_mode else ""
        pass_rate_kpi_style = "" if is_yaml_mode else "display:none;"
        
        pass_count = data['kpi']['total_steps'] - data['kpi']['bugs_count']
        pass_rate = f"{int(pass_count / data['kpi']['total_steps'] * 100)}%" if data['kpi']['total_steps'] > 0 else "100%"
        
        tab_topology_style = "display:none;" if is_yaml_mode else ""
        tab_yaml_style = "display:none;" if is_yaml_mode else ""
        timeline_tab_name = "🎬 用例执行链路" if is_yaml_mode else "🎬 Planner-Worker 执行树"
        # ==========================

        html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>巡检执行报告 · {data['run_id']}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
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

    .page-tree-list {{
      list-style-type: none;
      padding-left: 20px;
      margin: 4px 0;
      border-left: 1px dashed rgba(99, 102, 241, 0.3);
    }}
    .page-tree-node {{
      margin: 6px 0;
    }}
    .node-content {{
      display: flex;
      align-items: center;
      padding: 6px 12px;
      border-radius: 6px;
      background: rgba(15, 23, 42, 0.5);
      border: 1px solid rgba(255, 255, 255, 0.05);
      transition: background 0.2s;
    }}
    .node-content:hover {{
      background: rgba(99, 102, 241, 0.15);
      border-color: rgba(99, 102, 241, 0.3);
    }}
    .node-icon {{
      margin-right: 10px;
      font-size: 14px;
    }}
    .node-text {{
      color: #cbd5e1;
      font-size: 13px;
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
      grid-template-columns: 80px 1fr auto;
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
      background: rgba(255, 255, 255, 0.1);
      color: #e2e8f0;
      border: 1px solid rgba(255, 255, 255, 0.2);
    }}

    .action-tag.click, .action-tag.action {{ background: var(--primary-glow); color: #c7d2fe; border: 1px solid rgba(99, 102, 241, 0.4); }}
    .action-tag.hover {{ background: var(--cyan-bg); color: #a5f3fc; border: 1px solid rgba(6, 182, 212, 0.4); }}
    .action-tag.wait, .action-tag.wait_for {{ background: var(--amber-bg); color: #fde68a; border: 1px solid rgba(245, 158, 11, 0.4); }}
    .action-tag.finish {{ background: var(--emerald-bg); color: #a7f3d0; border: 1px solid rgba(16, 185, 129, 0.4); }}
    .action-tag.input {{ background: var(--cyan-bg); color: #a5f3fc; border: 1px solid rgba(6, 182, 212, 0.4); }}
    .action-tag.assert {{ background: rgba(168, 85, 247, 0.15); color: #d8b4fe; border: 1px solid rgba(168, 85, 247, 0.4); }}
    .action-tag.api_assert {{ background: rgba(236, 72, 153, 0.15); color: #fbcfe8; border: 1px solid rgba(236, 72, 153, 0.4); }}
    .action-tag.freeze_check {{ background: rgba(56, 189, 248, 0.15); color: #bae6fd; border: 1px solid rgba(56, 189, 248, 0.4); }}

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

    /* Layout wrapper for Sidebar */
    .layout-wrapper {{
      display: flex;
      min-height: 100vh;
    }}

    .sidebar {{
      width: 280px;
      background: #0d121f;
      border-right: 1px solid var(--border-subtle);
      display: flex;
      flex-direction: column;
      flex-shrink: 0;
    }}

    .sidebar-header {{
      padding: 24px 20px;
      border-bottom: 1px solid var(--border-subtle);
      display: flex;
      flex-direction: column;
      gap: 12px;
    }}
    
    .back-btn {{
      display: inline-flex;
      justify-content: center;
      align-items: center;
      gap: 8px;
      background: linear-gradient(135deg, rgba(99, 102, 241, 0.15), rgba(79, 70, 229, 0.15));
      border: 1px solid rgba(99, 102, 241, 0.4);
      color: #e0e7ff;
      padding: 10px 16px;
      border-radius: 10px;
      font-size: 14px;
      font-weight: 700;
      text-decoration: none;
      cursor: pointer;
      transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
      box-shadow: 0 4px 12px -4px rgba(99, 102, 241, 0.2);
    }}

    .back-btn:hover {{
      background: linear-gradient(135deg, rgba(99, 102, 241, 0.3), rgba(79, 70, 229, 0.3));
      border-color: rgba(99, 102, 241, 0.8);
      color: #fff;
      transform: translateY(-1px);
      box-shadow: 0 6px 16px -4px rgba(99, 102, 241, 0.4);
    }}

    .sidebar-list {{
      flex: 1;
      overflow-y: auto;
      padding: 12px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }}

    .sidebar-item {{
      display: flex;
      flex-direction: column;
      padding: 12px;
      border-radius: 8px;
      background: transparent;
      border: 1px solid transparent;
      text-decoration: none;
      color: var(--text-muted);
      transition: all 0.2s;
    }}

    .sidebar-item:hover {{
      background: rgba(255, 255, 255, 0.03);
    }}

    .sidebar-item.active {{
      background: rgba(99, 102, 241, 0.1);
      border-color: var(--primary);
      color: #fff;
    }}

    .sidebar-item-title {{
      font-size: 13px;
      font-weight: 600;
      margin-bottom: 4px;
      word-break: break-all;
    }}

    .sidebar-item-meta {{
      font-size: 11px;
      color: var(--text-dim);
      display: flex;
      justify-content: space-between;
    }}
    
    .main-content {{
      flex: 1;
      min-width: 0; /* prevent flex blowout */
      overflow-y: auto;
    }}

  </style>
  <script src="../runs_data.js"></script>
</head>
<body>

<div class="layout-wrapper">
  <!-- Left Sidebar -->
  <div class="sidebar">
    <div class="sidebar-header">
      <a href="../index.html" class="back-btn">
        <span style="font-size: 16px;">⬅️</span> 返回大盘
      </a>
      <div style="font-size: 14px; font-weight: 700; color: #fff; margin-top: 8px;">📋 历史测试报告导航</div>
    </div>
    <div class="sidebar-list" id="sidebarList">
      <!-- Dynamically populated by JS -->
    </div>
  </div>

  <!-- Main Content -->
  <div class="main-content">
    <div class="container">
    
    <!-- Hero Header -->
    <div class="hero">
      <div class="hero-top">
        <div class="hero-title-group">
          <h1>
            <span>{hero_title}</span>
            <span class="badge">{badge_text}</span>
          </h1>
          <div class="run-id-pill">
            <span>🏷️ Run ID:</span> <strong>{data['run_id']}</strong>
          </div>
        </div>

        <div class="hero-meta">
          <div class="meta-chip" style="background: rgba(99, 102, 241, 0.15); border-color: rgba(99, 102, 241, 0.3);">
            <span>🎯 预期最大步数:</span> <strong style="color: #a5b4fc;">{data['kpi'].get('max_steps', '-')}</strong>
          </div>
          <div class="meta-chip" style="background: rgba(236, 72, 153, 0.15); border-color: rgba(236, 72, 153, 0.3);">
            <span>⏳ 预期运行时长:</span> <strong style="color: #f9a8d4;">{data['kpi'].get('max_time', '-')}</strong>
          </div>
        </div>
      </div>

      <div class="macro-objective-box">
        <div class="label">宏观目标</div>
        <div>{html.escape(data['macro_objective'])}</div>
      </div>
    </div>

    <!-- KPI Grid -->
    <div class="kpi-grid" style="grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));">
      <div class="kpi-card" style="background: rgba(16, 185, 129, 0.05); border-color: rgba(16, 185, 129, 0.2);">
        <div class="kpi-label">⏱️ 实际耗时</div>
        <div class="kpi-value" style="color:#6ee7b7; font-size:20px;">{data['duration']}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">📅 开始与结束</div>
        <div class="kpi-value" style="font-size:14px; line-height:1.5; color:var(--text-muted);">起: {data['start_time']}<br>止: {data['end_time']}</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">🎯 实际执行步数</div>
        <div class="kpi-value">{data['kpi']['total_steps']} <span class="sub">步</span></div>
      </div>
      <div class="kpi-card" style="{planner_kpi_style}">
        <div class="kpi-label">🧠 Planner 规划轮次</div>
        <div class="kpi-value">{data['kpi']['planner_phases']} <span class="sub">轮</span></div>
      </div>
      <div class="kpi-card" style="{pass_rate_kpi_style}">
        <div class="kpi-label">✅ 测试断言通过率</div>
        <div class="kpi-value" style="color: #34d399;">{pass_rate}</div>
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
        {timeline_tab_name} <span class="counter">{data['kpi']['total_steps']}</span>
      </button>
      <button class="tab-btn" onclick="switchTab('tab-bugs')">
        🐞 缺陷证据库 <span class="counter" style="background:#f43f5e;color:#fff;">{data['kpi']['bugs_count']}</span>
      </button>
      <button class="tab-btn" onclick="switchTab('tab-topology')" style="{tab_topology_style}">
        🌳 纯 Markdown 组件树
      </button>
      <button class="tab-btn" onclick="switchTab('tab-api')">
        🌐 底层接口池 <span class="counter">{data['kpi']['apis_count']}</span>
      </button>
      <button class="tab-btn" onclick="switchTab('tab-yaml')" style="{tab_yaml_style}">
        📝 自动沉淀回归用例 <span class="counter">{data['kpi']['yaml_steps_count']} 步</span>
      </button>
    </div>

    <!-- Tab 1: Timeline Steps -->
    <div id="tab-timeline" class="tab-pane active">
      <div class="timeline-filter-bar">
        <div class="filter-btn-group">
          <button class="filter-pill active" onclick="filterSteps('all')">全部 ({data['kpi']['total_steps']})</button>
          <button class="filter-pill" onclick="filterSteps('bugs')">仅看报错 ({data['kpi']['bugs_count']})</button>
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

    <!-- Tab 3: Pure Markdown Topology -->
    <div id="tab-topology" class="tab-pane">
      <div class="topology-card" style="padding:0; background:var(--bg-card); border-radius:12px; border:1px solid var(--border-subtle); overflow:hidden;">
        <div style="padding:16px 20px; border-bottom:1px solid var(--border-subtle); background:rgba(15,23,42,0.5);">
            <h3 style="font-size:15px;margin:0;color:#fff;display:flex;align-items:center;gap:8px;">🗺️ 纯 Markdown 组件拓扑树 <span style="font-size:12px;color:var(--text-dim);font-weight:normal;"></span></h3>
        </div>
        <div class="code-view" style="margin:0; border-radius:0; border:none; padding:20px; font-family:var(--font-mono); font-size:14px; line-height:1.6; white-space:pre; color:#a5b4fc; overflow-x:auto;">{html.escape(mermaid_raw) if mermaid_raw else "未检测到拓扑数据"}</div>
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

      if (tabId === 'tab-topology' && typeof window.mermaidRenderer === 'function') {{
        window.mermaidRenderer();
      }}
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
      const passFilter = allSteps.map(s => {{
        let pass = true;
        if (currentFilter === 'bugs' && !s.has_bug) pass = false;
        if (currentFilter === 'click' && s.action !== 'CLICK') pass = false;
        if (currentFilter === 'hover' && s.action !== 'HOVER') pass = false;
        
        if (searchQuery) {{
          const matchTarget = (s.target || '').toLowerCase().includes(searchQuery);
          const matchPath = (s.ui_path || '').toLowerCase().includes(searchQuery);
          const matchThought = (s.thought || '').toLowerCase().includes(searchQuery);
          const matchSub = (s.sub_objective || '').toLowerCase().includes(searchQuery);
          if (!matchTarget && !matchPath && !matchThought && !matchSub) pass = false;
        }}
        return pass;
      }});

      // Maintain Planner-Worker hierarchy for Explore Mode
      let currentPlannerIdx = -1;
      for (let i = 0; i < allSteps.length; i++) {{
          if (allSteps[i].type === 'planner') {{
              currentPlannerIdx = i;
          }} else if (allSteps[i].type === 'worker') {{
              // If a worker passes the filter, its parent planner MUST be visible
              if (passFilter[i] && currentPlannerIdx !== -1) {{
                  passFilter[currentPlannerIdx] = true;
              }}
          }}
      }}
      
      return allSteps.filter((s, i) => passFilter[i]);
    }}

    function togglePlanner(id) {{
        const el = document.getElementById(id);
        if(el) {{
            el.style.display = (el.style.display === 'none' ? 'block' : 'none');
        }}
    }}

    function renderSteps() {{
      const isYamlMode = (allSteps.length > 0 && allSteps[0].type !== 'planner' && allSteps[0].type !== 'worker');
      const filtered = getFilteredSteps();
      
      const container = document.getElementById('stepsContainer');
      if (filtered.length === 0) {{
        container.innerHTML = '<div style="text-align:center;padding:60px;color:var(--text-dim);">没有符合条件的步骤</div>';
        document.getElementById('pageInfo').innerText = '显示 0 步';
        if(document.getElementById('prevBtn')) document.getElementById('prevBtn').disabled = true;
        if(document.getElementById('nextBtn')) document.getElementById('nextBtn').disabled = true;
        return;
      }}

      let html = '';
      
      if (!isYamlMode && allSteps.some(s => s.type === 'planner')) {{
          // --- Explore Mode (Nested Rendering) ---
          const pgBar = document.querySelector('.pagination-bar');
          if (pgBar) pgBar.style.display = 'none';
          
          let currentPlannerHtml = '';
          let currentWorkersHtml = '';
          let plannerCount = 0;
          let displayCount = 0;
          
          const isFilterActive = (currentFilter !== 'all' || searchQuery !== '');
          const initialDisplay = isFilterActive ? 'block' : 'none';
          
          filtered.forEach(s => {{
              if (s.type === 'planner') {{
                  // Flush previous planner
                  if (currentPlannerHtml !== '') {{
                      html += currentPlannerHtml;
                      html += `<div id="planner-workers-${{plannerCount}}" style="display:${{initialDisplay}}; padding-left: 40px; border-left: 2px solid rgba(99,102,241,0.3); margin-left: 20px;">${{currentWorkersHtml}}</div>`;
                  }}
                  plannerCount = s.step;
                  currentWorkersHtml = ''; // reset
                  
                  currentPlannerHtml = `
                  <div class="step-card" style="border: 1px solid var(--primary); background: rgba(99, 102, 241, 0.05); cursor: pointer; margin-top: 16px;" onclick="togglePlanner('planner-workers-${{plannerCount}}')">
                    <div class="step-index-badge" style="background: var(--primary);">
                      <span class="num">P${{s.step}}</span>
                    </div>
                    <div class="step-main-info">
                      <div class="step-header-line">
                        <span class="action-tag" style="background:var(--primary);">🎯 PLANNER 制定规划 ${{s.global_prog ? `(全局进度: ${{s.global_prog}})` : ''}}</span>
                        <span style="font-size:11px;color:var(--text-dim);margin-left:auto;">${{(s.timestamp || '').split(' ')[1] || ''}}</span>
                      </div>
                      <div class="step-target-name" style="color: #c7d2fe; font-size: 15px;">👉 目标: ${{escapeHtml(s.target)}}</div>
                      <div class="step-thought-text expanded" onclick="event.stopPropagation(); this.classList.toggle('expanded')" title="思考过程">
                        🧠 <strong>Planner思考:</strong> ${{escapeHtml(s.thought || '')}}
                      </div>
                    </div>
                    <div>
                      ${{s.screenshot ? `
                        <div class="step-thumb-wrapper" onclick="event.stopPropagation(); openLightbox('${{s.screenshot}}', 'Planner 阶段 #${{s.step}}')">
                          <img src="${{s.screenshot}}" alt="Plan Screenshot" loading="lazy">
                        </div>
                      ` : ''}}
                    </div>
                  </div>`;
                  displayCount++;
              }} else if (s.type === 'worker') {{
                  const bugClass = s.has_bug ? 'is-bug' : '';
                  const actClass = (s.action || '').toLowerCase();
                  const displayImg = s.hover_screenshot || s.screenshot;
                  
                  currentWorkersHtml += `
                  <div class="step-card ${{bugClass}}" style="transform: scale(0.98); margin-bottom: 8px;">
                    <div class="step-index-badge">
                      <span class="num">${{s.worker_step}}</span>
                      <span class="sub">/ ${{s.budget}}</span>
                    </div>
                    <div class="step-main-info">
                      <div class="step-header-line">
                        <span class="action-tag ${{actClass}}">${{s.action}}</span>
                        <span class="path-crumb">📍 ${{escapeHtml(s.ui_path)}}</span>
                        <span style="font-size:11px;color:var(--text-dim);margin-left:auto;">${{(s.timestamp || '').split(' ')[1] || ''}}</span>
                      </div>
                      <div class="step-target-name">${{escapeHtml(s.target || '(子目标达成)')}}</div>
                      <div class="step-thought-text" onclick="event.stopPropagation(); this.classList.toggle('expanded')">
                        💡 <strong>Worker思考:</strong> ${{escapeHtml(s.thought || '无思考过程')}}
                      </div>
                    </div>
                    <div style="display: flex; gap: 8px;">
                      ${{s.screenshot ? `
                        <div class="step-thumb-wrapper" onclick="event.stopPropagation(); openLightbox('${{s.screenshot}}', '执行前 #${{s.step}}')" title="执行前截图">
                          <div style="position:absolute; top:4px; left:4px; background:rgba(0,0,0,0.6); color:#fff; font-size:10px; padding:2px 4px; border-radius:4px; pointer-events:none;">执行前</div>
                          <img src="${{s.screenshot}}" alt="Before" loading="lazy">
                        </div>
                      ` : ''}}
                      ${{(s.after_screenshot || s.hover_screenshot) ? `
                        <div class="step-thumb-wrapper" onclick="event.stopPropagation(); openLightbox('${{s.after_screenshot || s.hover_screenshot}}', '执行后 #${{s.step}}')" title="执行后截图">
                          <div style="position:absolute; top:4px; left:4px; background:rgba(0,0,0,0.6); color:#fff; font-size:10px; padding:2px 4px; border-radius:4px; pointer-events:none;">执行后</div>
                          <img src="${{s.after_screenshot || s.hover_screenshot}}" alt="After" loading="lazy">
                        </div>
                      ` : ''}}
                    </div>
                  </div>`;
              }}
          }});
          
          // Flush the last one
          if (currentPlannerHtml !== '') {{
              html += currentPlannerHtml;
              html += `<div id="planner-workers-${{plannerCount}}" style="display:${{typeof initialDisplay !== 'undefined' ? initialDisplay : 'none'}}; padding-left: 40px; border-left: 2px solid rgba(99,102,241,0.3); margin-left: 20px;">${{currentWorkersHtml}}</div>`;
          }}
          
          container.innerHTML = html;
          document.getElementById('pageInfo').innerText = `显示共 ${{displayCount}} 个 Planner 规划轮次 (点击展开对应 Worker 步骤)`;
      }} else {{
          // --- YAML Mode (Flat Rendering) ---
          const pgBar = document.querySelector('.pagination-bar');
          if (pgBar) pgBar.style.display = 'flex';
          const total = filtered.length;
          const totalPages = Math.ceil(total / pageSize) || 1;
          currentPage = Math.max(1, Math.min(currentPage, totalPages));

          const startIdx = (currentPage - 1) * pageSize;
          const endIdx = Math.min(startIdx + pageSize, total);
          const pageSteps = filtered.slice(startIdx, endIdx);

          pageSteps.forEach(s => {{
            const bugClass = s.has_bug ? 'is-bug' : '';
            const actClass = (s.action || '').toLowerCase();
            const displayImg = s.hover_screenshot || s.screenshot;

            html += `
              <div class="step-card ${{bugClass}}">
                <div class="step-index-badge">
                  <span class="num">${{s.step}}</span>
                </div>
                <div class="step-main-info">
                  <div class="step-header-line">
                    <span class="action-tag ${{actClass}}">${{s.action}}</span>
                    <span class="path-crumb">📍 ${{escapeHtml(s.ui_path)}}</span>
                    <span style="font-size:11px;color:var(--text-dim);margin-left:auto;">${{(s.timestamp || '').split(' ')[1] || ''}}</span>
                  </div>
                  <div class="step-target-name">${{escapeHtml(s.target || '(子目标达成)')}}</div>
                  <div class="step-thought-text" onclick="this.classList.toggle('expanded')" title="点击展开/收起完整思考链">
                    💡 <strong>思考:</strong> ${{escapeHtml(s.thought || '无思考过程')}}
                  </div>
                </div>
                <div style="display: flex; gap: 8px; justify-content: center;">
                  ${{s.screenshot ? `
                    <div class="step-thumb-wrapper" onclick="openLightbox('${{s.screenshot}}', '执行前 #${{s.step}}')" title="执行前截图">
                      <div style="position:absolute; top:4px; left:4px; background:rgba(0,0,0,0.6); color:#fff; font-size:10px; padding:2px 4px; border-radius:4px; pointer-events:none;">执行前</div>
                      <img src="${{s.screenshot}}" alt="Before" loading="lazy">
                    </div>
                  ` : ''}}
                  ${{(s.after_screenshot || s.hover_screenshot) ? `
                    <div class="step-thumb-wrapper" onclick="openLightbox('${{s.after_screenshot || s.hover_screenshot}}', '执行后 #${{s.step}}')" title="执行后截图">
                      <div style="position:absolute; top:4px; left:4px; background:rgba(0,0,0,0.6); color:#fff; font-size:10px; padding:2px 4px; border-radius:4px; pointer-events:none;">执行后</div>
                      <img src="${{s.after_screenshot || s.hover_screenshot}}" alt="After" loading="lazy">
                    </div>
                  ` : ''}}
                  ${{(!s.screenshot && !s.after_screenshot && !s.hover_screenshot) ? '<div style="font-size:12px;color:var(--text-dim);display:flex;align-items:center;">无关联截图</div>' : ''}}
                </div>
              </div>
            `;
          }});

          container.innerHTML = html;
          document.getElementById('pageInfo').innerText = `显示第 ${{startIdx + 1}} 至 ${{endIdx}} 步 (共 ${{total}} 步)`;
          if(document.getElementById('prevBtn')) document.getElementById('prevBtn').disabled = currentPage <= 1;
          if(document.getElementById('nextBtn')) document.getElementById('nextBtn').disabled = currentPage >= totalPages;
      }}
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
    function renderSidebar() {{
      const sidebarList = document.getElementById('sidebarList');
      if (typeof window.GLOBAL_RUNS_LIST === 'undefined' || !window.GLOBAL_RUNS_LIST.length) {{
          sidebarList.innerHTML = '<div style="color:var(--text-dim);font-size:12px;padding:12px;text-align:center;">暂无其他历史记录<br>(或未通过大盘构建)</div>';
          return;
      }}
      
      const currentRunId = "{data['run_id']}";
      let html = '';
      
      // 按照修改时间降序排序 (mtime)
      const sortedRuns = [...window.GLOBAL_RUNS_LIST].sort((a, b) => (b.mtime || 0) - (a.mtime || 0));
      
      sortedRuns.forEach(r => {{
          const isActive = r.run_id === currentRunId ? 'active' : '';
          const modeLabel = r.run_id && r.run_id.startsWith('explore') ? '自主探索' : '全量冒烟';
          html += `
            <a href="../${{r.run_id}}/report.html" class="sidebar-item ${{isActive}}">
              <div class="sidebar-item-title">${{r.run_id}}</div>
              <div class="sidebar-item-meta">
                <span>${{modeLabel}}</span>
                <span>${{r.kpi ? r.kpi.total_steps : 0}}步 | ${{r.kpi ? r.kpi.bugs_count : 0}}Bug</span>
              </div>
            </a>
          `;
      }});
      
      sidebarList.innerHTML = html;
      
      // 自动滚动到当前激活的项
      setTimeout(() => {{
          const activeItem = sidebarList.querySelector('.sidebar-item.active');
          if (activeItem) {{
              activeItem.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
          }}
      }}, 100);
    }}

    document.addEventListener('DOMContentLoaded', () => {{
      renderSteps();
      renderSidebar();
    }});
  </script>
  </div> <!-- end container -->
  </div> <!-- end main-content -->
</div> <!-- end layout-wrapper -->
</body>
</html>
"""
        out.write_text(html_content, encoding="utf-8")
        logger.info(f"🎉 高颜值离线交互式报告已生成: {out}")

        # 自动同步刷新全局门户首页 reports/runs/index.html
        try:
            from utils.report_hub import ReportHub
            ReportHub().build_index_html()
        except Exception as e:
            logger.debug(f"更新全局门户 index.html 失败: {e}")

        # 发送飞书通知
        if not disable_push:
            self._send_feishu_webhook(data)

        return out

    def _send_feishu_webhook(self, data: dict):
        webhook_url = None
        feishu_secret = None
        report_base_url = "http://localhost"
        try:
            import yaml
            with open("config.yaml", "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
                webhook_url = config.get("reports", {}).get("feishu_webhook")
                feishu_secret = config.get("reports", {}).get("feishu_secret")
                report_base_url = config.get("reports", {}).get("report_base_url", report_base_url)
        except Exception as e:
            logger.debug(f"读取 config.yaml 获取 webhook 失败: {e}")
            
        if not webhook_url:
            logger.debug("未配置飞书 webhook，跳过推送")
            return
        bugs_count = data['kpi'].get('bugs_count', 0)
        template = "red" if int(bugs_count) > 0 else "blue"
        
        import time
        import hashlib
        import base64
        import hmac

        payload = {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "template": template,
                    "title": {
                        "tag": "plain_text",
                        "content": "🚀 Electron Vision AI 测试报告已生成"
                    }
                },
                "elements": [
                    {
                        "tag": "div",
                        "text": {
                            "tag": "lark_md",
                            "content": f"**🏷️ Run ID:** {data.get('run_id')}\n**🎯 宏观目标:** {data.get('macro_objective')}\n\n**📉 预期步数:** {data['kpi'].get('max_steps', '-')} | **预期耗时:** {data['kpi'].get('max_time', '-')}\n**📈 实际执行:** {data['kpi'].get('total_steps')} 步 | **实际耗时:** {data.get('duration')}\n\n**🐞 捕获严重缺陷:** {bugs_count} 个\n**🗺️ 触达二级页面:** {data['kpi'].get('page_scopes_count', 0)} 个"
                        }
                    },
                    {
                        "tag": "action",
                        "actions": [
                            {
                                "tag": "button",
                                "text": {
                                    "tag": "plain_text",
                                    "content": "🔗 打开 HTML 详细测试报告"
                                },
                                "type": "primary",
                                "url": f"{report_base_url.rstrip('/')}/{data.get('run_id')}/report.html"
                            }
                        ]
                    }
                ]
            }
        }
        if feishu_secret:
            timestamp = str(int(time.time()))
            string_to_sign = '{}\n{}'.format(timestamp, feishu_secret)
            hmac_code = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
            sign = base64.b64encode(hmac_code).decode('utf-8')
            payload["timestamp"] = timestamp
            payload["sign"] = sign

        try:
            import requests
            resp = requests.post(webhook_url, json=payload, timeout=5)
            if resp.status_code == 200:
                logger.info("✅ 飞书群机器人测试报告通知发送成功！")
            else:
                logger.warning(f"❌ 飞书通知发送异常: {resp.text}")
        except Exception as e:
            logger.warning(f"❌ 飞书通知发送失败: {e}")


def main():
    parser = argparse.ArgumentParser(description="Electron AI Vision 高颜值执行报告生成引擎")
    parser.add_argument("--run", type=str, help="指定要生成报告的运行目录名 (如 explore_20260928_182632)")
    parser.add_argument("--latest", action="store_true", help="自动对最新的运行目录生成报告")
    parser.add_argument("--no-push", action="store_true", help="禁用生成报告时的飞书群通知推送")
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
        print("💡 未显式指定运行目录，自动寻找最近一次的测试产物目录...")
        runs = sorted([p for p in RUNS_DIR.iterdir() if p.is_dir() and (p.name.startswith("explore_") or p.name.startswith("smoke_"))], key=lambda p: p.stat().st_mtime, reverse=True)
        if runs:
            target_dir = runs[0]
        else:
            print("❌ 找不到任何历史运行目录，请先执行一次测试！")
            sys.exit(1)

    print(f"🚀 开始为运行目录生成视觉报告: {target_dir.name} ...")
    reporter = ReportGenerator(target_dir)
    out_file = reporter.generate_html(disable_push=args.no_push)
    print(f"✅ 报告生成完毕！可以直接在浏览器中双击打开：\nfile:///{out_file.as_posix()}\n")


if __name__ == "__main__":
    main()
