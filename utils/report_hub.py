"""
==============================================================================
utils/report_hub.py —— 自动化巡检与探索全量大盘门户引擎 (Test Report Hub)
==============================================================================

职责：
1. 遍历 reports/runs/ 下的所有历史运行目录；
2. 聚合全局运行指标（总运行次数、总步数、总Bug数、总运行时长）；
3. 生成 reports/runs/index.html 统一门户首页，彻底消灭默认的黑白目录列表；
4. 支持一键本地/内网启动固定服务：python utils/report_hub.py --serve --port 8080。
"""

from __future__ import annotations

import argparse
import html
import io
import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Windows GBK 终端保护
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.paths import RUNS_DIR, GLOBAL_BUGS_DIR, get_all_run_folders, find_run_dir

logger = logging.getLogger("report_hub")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s")

APP_NAME_MAP = {
    "zhaiwan": "寨湾矿山",
    "liwutong": "里伍铜矿山"
}


def extract_ui_path_from_step(step_str: Any, default: str = "首页") -> str:
    """从 step 描述中智能提炼业务路径，例如从 '(路径: 生产管理 -> 能耗监测)' 中提取"""
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


def enrich_bug_metadata_dict(b_dict: dict) -> None:
    """智能元数据增强：从 step 文本自动推导缺失的 action_type, target_element, ui_path, tags"""
    step_str = str(b_dict.get("step") or (b_dict.get("details") or {}).get("step") or "")
    if not b_dict.get("action_type") or b_dict.get("action_type") == "无":
        m_act = re.search(r"\[([A-Z_]+)\]", step_str)
        if m_act:
            b_dict["action_type"] = m_act.group(1).strip()
    if not b_dict.get("target_element") or b_dict.get("target_element") == "无":
        m_tgt = re.search(r"交互目标[:：]\s*['\"]?(.*?)['\"]?\s*(?:\(|$)", step_str)
        if m_tgt:
            b_dict["target_element"] = m_tgt.group(1).strip()
    if not b_dict.get("ui_path") or b_dict.get("ui_path") in ("无", "首页"):
        m_path = re.search(r"(?:页面路径|路径)[:：]\s*(.*?)\)", step_str)
        if m_path:
            b_dict["ui_path"] = m_path.group(1).strip()
    
    # 智能推导业务标签
    raw_tags = b_dict.get("tags")
    if not raw_tags or raw_tags == "无" or raw_tags == [] or raw_tags == "":
        auto_tags = []
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



class ReportHub:
    def __init__(self, runs_dir: Optional[Path | str] = None):
        self.runs_dir = Path(runs_dir).resolve() if runs_dir else RUNS_DIR.resolve()

    def collect_all_runs(self) -> List[Dict[str, Any]]:
        """扫描所有运行目录（支持按应用分层与旧单层），聚合元数据与项目归属"""
        from utils.report_generator import ReportGenerator

        runs_data = []
        if not self.runs_dir.exists():
            return runs_data

        all_dirs = get_all_run_folders()

        for d in all_dirs:
            report_file = d / "report.html"
            generator = ReportGenerator(d)
            if not report_file.exists():
                try:
                    generator.generate_html()
                except Exception as e:
                    logger.warning(f"为 {d.name} 补充生成 report.html 失败: {e}")

            try:
                data = generator.parse_run_data()
                # 计算相对于 runs_dir 的相对路径
                try:
                    rel_p = d.relative_to(self.runs_dir).as_posix()
                except Exception:
                    rel_p = d.name

                # 判定所属应用
                if "/" in rel_p:
                    app_key = rel_p.split("/")[0]
                else:
                    # 兼容历史根目录旧运行：通过日志判定或默认归属寨湾
                    log_files = list(d.glob("*.log"))
                    is_liwutong = False
                    if log_files:
                        try:
                            sample = log_files[0].read_text(encoding="utf-8", errors="ignore")[:2000]
                            if "liwutong" in sample:
                                is_liwutong = True
                        except Exception:
                            pass
                    app_key = "liwutong" if is_liwutong else "zhaiwan"

                data["app"] = app_key
                data["app_name"] = APP_NAME_MAP.get(app_key, app_key)
                data["rel_path"] = rel_p
                data["folder_name"] = d.name
                data["report_url"] = f"./{rel_p}/report.html"
                data["mtime"] = d.stat().st_mtime
                runs_data.append(data)
            except Exception as e:
                logger.error(f"解析运行目录 {d.name} 失败: {e}")

        return runs_data

    def build_index_html(self, output_path: Optional[Path | str] = None) -> Path:
        """生成统一门户首页 reports/runs/index.html"""
        runs = self.collect_all_runs()
        out_file = Path(output_path).resolve() if output_path else (self.runs_dir / "index.html")

        # 统计宏观总计数据
        total_runs = len(runs)
        total_steps = sum(r.get("kpi", {}).get("total_steps", 0) for r in runs)
        # 加载全局缺陷库附加信息 (聚合所有应用专属及通用 global_bugs*.json)
        global_bugs_map = {}
        if GLOBAL_BUGS_DIR.exists():
            for global_bugs_file in sorted(GLOBAL_BUGS_DIR.glob("global_bugs*.json")):
                try:
                    import json
                    with open(global_bugs_file, "r", encoding="utf-8") as f:
                        gb_list = json.load(f)
                        for gb in gb_list:
                            if isinstance(gb, dict) and gb.get("id"):
                                global_bugs_map[gb.get("id")] = gb
                except Exception as e:
                    logger.warning(f"加载 {global_bugs_file.name} 失败: {e}")

        all_bugs_dict = {}
        # 1. 以全局库为主导
        for b_id, gb in global_bugs_map.items():
            r_id = gb.get("run_id", "")
            target_run_dir = find_run_dir(r_id)
            rel_shot = f"bugs/{b_id}.png"
            if target_run_dir:
                try:
                    rel_run_path = target_run_dir.relative_to(self.runs_dir).as_posix()
                except Exception:
                    rel_run_path = r_id
                if not (target_run_dir / rel_shot).exists():
                    rel_shot = ""
            else:
                rel_run_path = r_id
                rel_shot = ""

            raw_step = gb.get("step")
            if raw_step is None:
                raw_step = gb.get("global_step") or ""
            step_text = str(raw_step).strip()
            raw_ui_path = gb.get("ui_path", "")
            if not raw_ui_path or raw_ui_path == "无":
                raw_ui_path = extract_ui_path_from_step(step_text, default="首页")

            status_val = gb.get("status", "激活")
            if status_val == "Open" or not status_val:
                status_val = "激活"

            raw_analysis = gb.get("analysis_notes", "")
            if raw_analysis == "无":
                raw_analysis = ""

            all_bugs_dict[b_id] = {
                "id": b_id,
                "title": gb.get("title", ""),
                "run_id": r_id,
                "rel_run_path": rel_run_path,
                "date": gb.get("date", ""),
                "status": status_val,
                "step": step_text,
                "actual": gb.get("error_log") or gb.get("actual", ""),
                "rel_screenshot": rel_shot,
                "before_screenshot": "",
                "step_num": None,
                "report_link": f"./{rel_run_path}/report.html" if rel_run_path else "#",
                "occurrences": gb.get("occurrences", 1),
                "last_seen": gb.get("last_seen", gb.get("date") or ""),
                "global_step": gb.get("global_step", "无"),
                "action_type": gb.get("action_type", "无"),
                "target_element": gb.get("target_element", "无"),
                "assignee": gb.get("assignee", "Unassigned"),
                "tags": ", ".join(gb.get("tags", [])) if isinstance(gb.get("tags"), list) else (gb.get("tags") or "无"),
                "severity": normalize_severity(gb.get("severity", 3)),
                "ui_path": raw_ui_path,
                "analysis_notes": raw_analysis
            }
            enrich_bug_metadata_dict(all_bugs_dict[b_id])

        # 2. 从当前存在的 runs 中补充截图等确切数据，或新增尚未并入 global 的 bug
        for r in runs:
            r_id = r.get("run_id", "")
            r_link = r.get("report_url", "#")
            r_rel = r.get("rel_path", r_id)
            target_run_dir = find_run_dir(r_id)
            for b in r.get("bugs", []):
                b_id = b.get("id", "BUG")
                rel_shot = b.get("rel_screenshot", "")
                before_shot = b.get("before_screenshot", "")
                step_num = b.get("step_num")
                if b_id in all_bugs_dict:
                    if rel_shot:
                        if target_run_dir and (target_run_dir / rel_shot).exists():
                            all_bugs_dict[b_id]["rel_screenshot"] = rel_shot
                            all_bugs_dict[b_id]["rel_run_path"] = r_rel
                        else:
                            all_bugs_dict[b_id].pop("rel_screenshot", None)
                    if before_shot and target_run_dir and (target_run_dir / before_shot).exists():
                        all_bugs_dict[b_id]["before_screenshot"] = before_shot
                    if step_num:
                        all_bugs_dict[b_id]["step_num"] = step_num
                    all_bugs_dict[b_id]["report_link"] = r_link
                    all_bugs_dict[b_id]["rel_run_path"] = r_rel
                    
                    # 若已有的 ui_path 缺失或为首页，尝试用 run 中的数据补充
                    if (all_bugs_dict[b_id]["ui_path"] in ("", "无", "首页")) and b.get("ui_path"):
                        all_bugs_dict[b_id]["ui_path"] = b.get("ui_path")
                    if not all_bugs_dict[b_id].get("analysis_notes") and b.get("analysis_notes"):
                        all_bugs_dict[b_id]["analysis_notes"] = b.get("analysis_notes")
                    # 同步单次报告中更精准推导出的动作、目标与业务标签
                    if b.get("action_type") and b["action_type"] != "无":
                        all_bugs_dict[b_id]["action_type"] = b["action_type"]
                    if b.get("target_element") and b["target_element"] != "无":
                        all_bugs_dict[b_id]["target_element"] = b["target_element"]
                    if b.get("tags") and b["tags"] != "无":
                        all_bugs_dict[b_id]["tags"] = b["tags"]
                    enrich_bug_metadata_dict(all_bugs_dict[b_id])
                else:
                    if rel_shot and target_run_dir and not (target_run_dir / rel_shot).exists():
                        rel_shot = ""
                    if before_shot and target_run_dir and not (target_run_dir / before_shot).exists():
                        before_shot = ""

                    raw_step = (b.get("details") or {}).get("step", b.get("step", ""))
                    step_val = str(raw_step if raw_step is not None else "").strip()
                    run_ui_path = b.get("ui_path")
                    if not run_ui_path or run_ui_path == "无":
                        run_ui_path = extract_ui_path_from_step(step_val, default="首页")

                    run_status = b.get("status", "激活")
                    if run_status == "Open" or not run_status:
                        run_status = "激活"

                    run_analysis = b.get("analysis_notes", "")
                    if run_analysis == "无":
                        run_analysis = ""

                    all_bugs_dict[b_id] = {
                        "id": b_id,
                        "title": b.get("title", ""),
                        "rel_run_path": r_rel,
                        "run_id": r_id,
                        "date": b.get("creation_date", b.get("date", "")),
                        "status": run_status,
                        "step": step_val,
                        "actual": (b.get("details") or {}).get("actual", b.get("actual", "")),
                        "rel_screenshot": rel_shot,
                        "before_screenshot": before_shot,
                        "step_num": step_num,
                        "report_link": r_link,
                        "occurrences": 1,
                        "last_seen": b.get("creation_date", b.get("date", "")),
                        "global_step": "无",
                        "action_type": b.get("action_type") or "无",
                        "target_element": b.get("target_element") or "无",
                        "assignee": b.get("assignee", "Unassigned"),
                        "tags": b.get("tags") or "无",
                        "severity": normalize_severity(b.get("severity", 3)),
                        "ui_path": run_ui_path,
                        "analysis_notes": run_analysis
                    }
                    enrich_bug_metadata_dict(all_bugs_dict[b_id])
                    
        # 3. 生成 all_bugs 并修正总数
        all_bugs = list(all_bugs_dict.values())
        total_bugs = len(all_bugs)

        # 4. 计算各个模式的数量
        count_runs_explore = sum(1 for r in runs if r.get("run_id", "").startswith("explore_"))
        count_runs_smoke = sum(1 for r in runs if r.get("run_id", "").startswith("smoke_"))
        count_runs_yaml = sum(1 for r in runs if r.get("run_id", "").startswith("yaml_"))

        count_bugs_explore = sum(1 for b in all_bugs if b.get("run_id", "").startswith("explore_"))
        count_bugs_smoke = sum(1 for b in all_bugs if b.get("run_id", "").startswith("smoke_"))
        count_bugs_yaml = sum(1 for b in all_bugs if b.get("run_id", "").startswith("yaml_"))

        # 轻量级投影：仅保留大盘卡片与侧边栏必需元数据，剔除占用高达 70MB+ 的底层 api_summary 与 steps 数据
        summary_runs = []
        for r in runs:
            summary_runs.append({
                "run_id": r.get("run_id"),
                "app": r.get("app"),
                "app_name": r.get("app_name"),
                "rel_path": r.get("rel_path"),
                "duration": r.get("duration", "未知"),
                "start_time": r.get("start_time", "未知"),
                "end_time": r.get("end_time", "未知"),
                "macro_objective": r.get("macro_objective", "常规测试"),
                "kpi": r.get("kpi", {}),
                "report_url": r.get("report_url", "#"),
                "mtime": r.get("mtime", 0)
            })

        runs_json = json.dumps(summary_runs, ensure_ascii=False)
        bugs_json = json.dumps(all_bugs, ensure_ascii=False)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Electron Vision AI · 自动化测试大盘</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg-base: #07090e;
      --bg-surface: #0f1422;
      --bg-card: rgba(18, 24, 38, 0.75);
      --bg-card-hover: rgba(28, 38, 62, 0.9);
      --border-subtle: rgba(255, 255, 255, 0.08);
      --border-focus: rgba(99, 102, 241, 0.45);
      --text-main: #f8fafc;
      --text-muted: #94a3b8;
      --text-dim: #64748b;
      --primary: #6366f1;
      --primary-glow: rgba(99, 102, 241, 0.25);
      --emerald: #10b981;
      --emerald-bg: rgba(16, 185, 129, 0.12);
      --rose: #f43f5e;
      --rose-bg: rgba(244, 63, 94, 0.15);
      --cyan: #06b6d4;
      --cyan-bg: rgba(6, 182, 212, 0.15);
      --amber: #f59e0b;
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
      background-image: 
        radial-gradient(circle at 20% 10%, rgba(99, 102, 241, 0.15) 0%, transparent 45%),
        radial-gradient(circle at 80% 20%, rgba(139, 92, 246, 0.12) 0%, transparent 40%),
        radial-gradient(circle at 50% 90%, rgba(16, 185, 129, 0.07) 0%, transparent 50%);
      background-attachment: fixed;
    }}

    .container {{
      max-width: 1440px;
      margin: 0 auto;
      padding: 36px 24px 80px 24px;
    }}

    /* Hero Header */
    .hero {{
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      border-radius: 24px;
      padding: 36px 40px;
      backdrop-filter: blur(20px);
      box-shadow: 0 24px 48px -15px rgba(0, 0, 0, 0.6);
      margin-bottom: 32px;
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
      margin-bottom: 24px;
    }}

    .hero-title-group h1 {{
      font-size: 28px;
      font-weight: 800;
      letter-spacing: -0.02em;
      display: flex;
      align-items: center;
      gap: 12px;
      color: #fff;
    }}

    .hero-title-group p {{
      color: var(--text-muted);
      font-size: 14px;
      margin-top: 6px;
    }}

    .hero-status-pill {{
      background: rgba(16, 185, 129, 0.12);
      border: 1px solid rgba(16, 185, 129, 0.3);
      color: #34d399;
      padding: 6px 14px;
      border-radius: 999px;
      font-size: 13px;
      font-weight: 600;
      display: flex;
      align-items: center;
      gap: 6px;
    }}

    .pulse-dot {{
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: #10b981;
      box-shadow: 0 0 10px #10b981;
      animation: pulse 2s infinite;
    }}

    @keyframes pulse {{
      0% {{ transform: scale(0.95); opacity: 0.8; }}
      50% {{ transform: scale(1.3); opacity: 1; }}
      100% {{ transform: scale(0.95); opacity: 0.8; }}
    }}

    /* Global KPIs */
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
    }}

    .kpi-card {{
      background: rgba(15, 23, 42, 0.6);
      border: 1px solid var(--border-subtle);
      border-radius: 16px;
      padding: 18px 22px;
      transition: transform 0.2s, border-color 0.2s;
    }}

    .kpi-card:hover {{
      transform: translateY(-2px);
      border-color: var(--border-focus);
    }}

    .kpi-card .label {{
      font-size: 13px;
      color: var(--text-dim);
      font-weight: 500;
      display: flex;
      align-items: center;
      gap: 6px;
      margin-bottom: 6px;
    }}

    .kpi-card .value {{
      font-size: 26px;
      font-weight: 800;
      letter-spacing: -0.02em;
      color: #fff;
    }}

    .kpi-card .value span.sub {{
      font-size: 13px;
      color: var(--text-dim);
      font-weight: 500;
      margin-left: 4px;
    }}

    /* Tabs Bar */
    .tabs-bar {{
      display: flex;
      gap: 12px;
      margin-bottom: 24px;
      border-bottom: 1px solid var(--border-subtle);
      padding-bottom: 14px;
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

    .tab-btn .badge {{
      font-size: 11px;
      padding: 2px 8px;
      border-radius: 999px;
      background: rgba(0, 0, 0, 0.35);
    }}

    .tab-btn.active .badge {{
      background: rgba(255, 255, 255, 0.25);
    }}

    /* Filter & Search Bar */
    .filter-bar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      flex-wrap: wrap;
      margin-bottom: 24px;
    }}

    .filter-pills {{
      display: flex;
      gap: 8px;
    }}

    .filter-pill {{
      background: rgba(15, 23, 42, 0.7);
      border: 1px solid var(--border-subtle);
      color: var(--text-muted);
      padding: 7px 16px;
      border-radius: 999px;
      font-size: 13px;
      font-weight: 500;
      cursor: pointer;
      transition: all 0.2s;
    }}

    .filter-pill:hover {{
      color: #fff;
      border-color: rgba(255, 255, 255, 0.2);
    }}

    .filter-pill.active {{
      background: rgba(99, 102, 241, 0.2);
      border-color: var(--primary);
      color: #a5b4fc;
      font-weight: 600;
    }}

    .search-box {{
      background: rgba(15, 23, 42, 0.7);
      border: 1px solid var(--border-subtle);
      color: #fff;
      padding: 8px 18px;
      border-radius: 10px;
      font-size: 13px;
      width: 280px;
      outline: none;
      transition: border-color 0.2s;
    }}

    .search-box:focus {{
      border-color: var(--primary);
      box-shadow: 0 0 10px var(--primary-glow);
    }}

    .hub-select {{
      background: rgba(15, 23, 42, 0.7);
      border: 1px solid var(--border-subtle);
      color: #e2e8f0;
      padding: 8px 14px;
      border-radius: 10px;
      font-size: 13px;
      outline: none;
      cursor: pointer;
      transition: all 0.2s;
    }}

    .hub-select:focus, .hub-select:hover {{
      border-color: var(--primary);
      box-shadow: 0 0 10px var(--primary-glow);
    }}

    .hub-btn-reset {{
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid var(--border-subtle);
      color: var(--text-muted);
      padding: 8px 16px;
      border-radius: 10px;
      font-size: 13px;
      cursor: pointer;
      transition: all 0.2s;
      white-space: nowrap;
    }}

    .hub-btn-reset:hover {{
      background: rgba(255, 255, 255, 0.1);
      color: #fff;
      border-color: rgba(255, 255, 255, 0.2);
    }}

    /* Runs Cards List */
    .runs-grid {{
      display: flex;
      flex-direction: column;
      gap: 18px;
    }}

    .run-card {{
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      border-radius: 18px;
      padding: 24px 28px;
      backdrop-filter: blur(12px);
      transition: transform 0.2s, border-color 0.2s, box-shadow 0.2s;
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 24px;
      align-items: center;
    }}

    .run-card:hover {{
      transform: translateY(-2px);
      border-color: var(--border-focus);
      box-shadow: 0 16px 36px -10px rgba(0, 0, 0, 0.5);
    }}

    .run-card-main {{
      display: flex;
      flex-direction: column;
      gap: 12px;
    }}

    .run-header {{
      display: flex;
      align-items: center;
      gap: 12px;
      flex-wrap: wrap;
    }}

    .mode-tag {{
      font-size: 12px;
      font-weight: 700;
      padding: 4px 10px;
      border-radius: 6px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}

    .mode-tag.explore {{
      background: rgba(99, 102, 241, 0.2);
      color: #a5b4fc;
      border: 1px solid rgba(99, 102, 241, 0.4);
    }}

    .mode-tag.smoke {{
      background: var(--cyan-bg);
      color: #38bdf8;
      border: 1px solid rgba(6, 182, 212, 0.4);
    }}

    .mode-tag.yaml {{
      background: var(--emerald-bg);
      color: #34d399;
      border: 1px solid rgba(16, 185, 129, 0.4);
    }}

    .run-id-title {{
      font-family: var(--font-mono);
      font-size: 17px;
      font-weight: 700;
      color: #fff;
    }}

    .run-meta-row {{
      display: flex;
      align-items: center;
      gap: 16px;
      font-size: 13px;
      color: var(--text-dim);
    }}

    .run-meta-item {{
      display: flex;
      align-items: center;
      gap: 6px;
    }}

    .run-meta-item strong {{
      color: var(--text-muted);
    }}

    .objective-quote {{
      background: rgba(10, 15, 26, 0.6);
      border-left: 3px solid var(--primary);
      padding: 10px 14px;
      border-radius: 6px;
      font-size: 13px;
      color: #cbd5e1;
      max-width: 900px;
    }}

    .run-badges-row {{
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
    }}

    .metric-badge {{
      background: rgba(15, 23, 42, 0.6);
      border: 1px solid var(--border-subtle);
      padding: 4px 12px;
      border-radius: 8px;
      font-size: 12px;
      font-weight: 600;
      display: flex;
      align-items: center;
      gap: 6px;
      color: var(--text-muted);
    }}

    .metric-badge.bugs {{
      background: var(--rose-bg);
      border-color: rgba(244, 63, 94, 0.3);
      color: #fb7185;
    }}

    .open-report-btn {{
      background: var(--primary);
      color: #fff;
      padding: 12px 24px;
      border-radius: 12px;
      font-size: 14px;
      font-weight: 600;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      transition: all 0.2s;
      white-space: nowrap;
      box-shadow: 0 4px 16px var(--primary-glow);
    }}

    .open-report-btn:hover {{
      background: #4f46e5;
      transform: translateY(-2px);
      box-shadow: 0 8px 24px var(--primary-glow);
    }}

    /* Global Bugs Table */
    .bugs-table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
      background: var(--bg-card);
      border: 1px solid var(--border-subtle);
      border-radius: 16px;
      overflow: hidden;
    }}

    .bugs-table th, .bugs-table td {{
      padding: 14px 18px;
      text-align: left;
      border-bottom: 1px solid var(--border-subtle);
    }}

    .bugs-table th {{
      color: var(--text-dim);
      font-size: 11px;
      text-transform: uppercase;
      font-weight: 700;
      background: rgba(15, 23, 42, 0.5);
    }}

    .bugs-table tr:hover td {{
      background: rgba(255, 255, 255, 0.02);
    }}

    .bug-link {{
      color: #38bdf8;
      text-decoration: none;
      font-weight: 600;
    }}

    .bug-link:hover {{
      text-decoration: underline;
    }}

    .bug-screenshots-duo {{
      display: flex;
      gap: 12px;
      align-items: flex-start;
    }}

    .bug-thumb-box {{
      flex: 1;
      border: 1px solid var(--border-subtle);
      border-radius: 10px;
      overflow: hidden;
      background: #000;
      position: relative;
      cursor: pointer;
      transition: transform 0.2s, border-color 0.2s;
    }}

    .bug-thumb-box:hover {{
      transform: scale(1.02);
      border-color: var(--primary);
    }}

    .bug-thumb-box img {{
      width: 100%;
      height: 260px;
      object-fit: contain;
      display: block;
      background: #000;
    }}

    .bug-thumb-tag {{
      position: absolute;
      top: 6px;
      left: 6px;
      font-size: 11px;
      font-weight: 700;
      padding: 2px 7px;
      border-radius: 4px;
      color: #fff;
      backdrop-filter: blur(4px);
      z-index: 2;
    }}

    .tag-before {{
      background: rgba(16, 185, 129, 0.85);
    }}

    .tag-after {{
      background: rgba(244, 63, 94, 0.85);
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

    @media (max-width: 900px) {{
      .run-card {{
        grid-template-columns: 1fr;
      }}
    }}
  </style>
</head>
<body>

  <div class="container">
    
    <!-- Hero Header -->
    <div class="hero">
      <div class="hero-top">
        <div class="hero-title-group">
          <h1>⚡ Electron Vision AI · 自动化测试大盘</h1>
          <p>多模态大模型端到端巡检全要素大盘 · 所有历史运行轨迹与缺陷汇总</p>
        </div>

        <div class="hero-status-pill">
          <div class="pulse-dot"></div>
          <span>服务常驻就绪 · 实时归档中</span>
        </div>
      </div>

      <!-- Global KPIs -->
      <div class="kpi-grid">
        <div class="kpi-card">
          <div class="label">🚀 累计执行巡检</div>
          <div class="value">{total_runs} <span class="sub">次运行</span></div>
        </div>
        <div class="kpi-card">
          <div class="label">🎯 累计探索步数</div>
          <div class="value">{total_steps} <span class="sub">步轨迹</span></div>
        </div>
        <div class="kpi-card" style="border-color: rgba(244, 63, 94, 0.3);">
          <div class="label">🐞 捕获历史缺陷</div>
          <div class="value" style="color: #fb7185;">{total_bugs} <span class="sub">个已归档</span></div>
        </div>
        <div class="kpi-card">
          <div class="label">⏱️ 最近更新时间</div>
          <div class="value" style="font-size: 16px; font-family: var(--font-mono); margin-top: 6px;">{now_str.split(' ')[1]} <span class="sub">{now_str.split(' ')[0]}</span></div>
        </div>
      </div>
    </div>

    <!-- Navigation Tabs -->
    <div class="tabs-bar">
      <button class="tab-btn active" onclick="switchMainTab('tab-runs', event)">
        🎬 历史巡检记录 <span class="badge">{total_runs}</span>
      </button>
      <button class="tab-btn" onclick="switchMainTab('tab-bugs', event)">
        🐞 全局缺陷知识库 <span class="badge" style="background:#f43f5e;color:#fff;">{total_bugs}</span>
      </button>
    </div>

    <!-- Tab 1: Runs List -->
    <!-- Tab 1: Runs List -->
    <div id="tab-runs" class="tab-pane active">
      <div class="filter-bar">
        <div class="filter-pills">
          <button class="filter-pill active" onclick="filterRuns('all', event)">全部模式 ({total_runs})</button>
          <button class="filter-pill" onclick="filterRuns('explore', event)">自主探索 ({count_runs_explore})</button>
          <button class="filter-pill" onclick="filterRuns('smoke', event)">冒烟测试 ({count_runs_smoke})</button>
          <button class="filter-pill" onclick="filterRuns('yaml', event)">回归测试 ({count_runs_yaml})</button>
        </div>

        <div style="display:flex; align-items:center; gap:8px;">
          <span style="color:var(--text-muted); font-size:13px; font-weight:600;">项目:</span>
          <select id="runAppFilter" class="hub-select" onchange="handleAppFilterChange(this.value)">
            <option value="all">全部被测项目</option>
            <option value="liwutong">🏔️ 里伍铜矿山</option>
            <option value="zhaiwan">⛰️ 寨湾矿山</option>
          </select>
        </div>

        <input type="text" id="runSearch" class="search-box" placeholder="搜索 Run ID、宏观目标或日期..." oninput="handleSearch()">
      </div>

      <div id="runsContainer" class="runs-grid"></div>
      <div id="runsPaginationControls" style="display:flex;justify-content:flex-end;align-items:center;gap:16px;margin-top:16px;padding:8px;"></div>
    </div>

    <!-- Tab 2: Bugs Table -->
    <div id="tab-bugs" class="tab-pane">
      <div class="filter-bar" style="background: rgba(15, 23, 42, 0.5); padding: 14px 20px; border-radius: 14px; border: 1px solid var(--border-subtle); margin-bottom: 20px; display: flex; gap: 16px; align-items: center; flex-wrap: wrap;">
        <!-- 模式筛选 -->
        <div style="display:flex; align-items:center; gap:8px;">
          <span style="color:var(--text-muted); font-size:13px; font-weight:600;">模式:</span>
          <select id="bugModeFilter" class="hub-select" onchange="handleBugFilterChange()">
            <option value="all">全部模式 ({total_bugs})</option>
            <option value="explore">自主探索 ({count_bugs_explore})</option>
            <option value="smoke">冒烟测试 ({count_bugs_smoke})</option>
            <option value="yaml">回归测试 ({count_bugs_yaml})</option>
          </select>
        </div>

        <!-- 状态筛选 -->
        <div style="display:flex; align-items:center; gap:8px;">
          <span style="color:var(--text-muted); font-size:13px; font-weight:600;">状态:</span>
          <select id="bugStatusFilter" class="hub-select" onchange="handleBugFilterChange()">
            <option value="all">全部状态</option>
            <option value="激活">激活</option>
            <option value="已解决">已解决</option>
            <option value="已提单">已提单</option>
            <option value="已关闭">已关闭</option>
            <option value="误报">误报</option>
          </select>
        </div>

        <!-- 搜索栏 -->
        <div style="display:flex; align-items:center; gap:8px; flex:1; min-width:320px;">
          <span style="color:var(--text-muted); font-size:13px; font-weight:600;">搜索:</span>
          <input type="text" id="bugSearch" class="search-box" style="flex:1; width:100%;" placeholder="搜索 缺陷编号、RUN ID、业务路径与目标..." oninput="handleBugSearch()">
        </div>

        <!-- 重置按钮 -->
        <button class="hub-btn-reset" onclick="resetBugFilters()">重置筛选</button>
      </div>
      
      <table class="bugs-table">
        <thead>
          <tr>
            <th style="width: 130px;">缺陷编号</th>
            <th style="width: 75px;">严重度</th>
            <th style="width: 170px;">RUN ID</th>
            <th style="width: 80px;">状态</th>
            <th style="width: 290px;">业务路径与目标</th>
            <th>异常详情</th>
            <th style="width: 180px;">截图凭据 (操作前 vs 案发)</th>
            <th style="width: 100px;">操作</th>
          </tr>
        </thead>
        <tbody id="bugsTbody"></tbody>
      </table>
      <div id="paginationControls" style="display:flex;justify-content:flex-end;align-items:center;gap:16px;margin-top:16px;padding:8px;"></div>
    </div>

  </div>

  <!-- Bug Modal Overlay -->
  <div id="bugModalOverlay" style="display:none;position:fixed;top:0;left:0;width:100vw;height:100vh;background:rgba(0,0,0,0.85);z-index:9998;align-items:center;justify-content:center;backdrop-filter:blur(6px);" onclick="if(event.target===this)this.style.display='none'">
    <div id="bugModalContent" style="background:var(--bg-base);width:85vw;max-width:1050px;max-height:90vh;border-radius:14px;border:1px solid rgba(255,255,255,0.12);display:flex;flex-direction:column;z-index:9999;box-shadow:0 25px 50px -12px rgba(0,0,0,0.85);overflow:hidden;" onclick="event.stopPropagation()">
      <div style="padding:16px 24px;border-bottom:1px solid rgba(255,255,255,0.08);background:var(--bg-surface);display:flex;justify-content:space-between;align-items:center;">
         <div id="modalHeader" style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;">
            <div id="modalBugId" style="font-family:var(--font-mono);font-size:16px;color:#f8fafc;font-weight:700;background:rgba(255,255,255,0.06);padding:6px 12px;border-radius:6px;border:1px solid rgba(255,255,255,0.12);">BUG-XXX</div>
            <div id="modalStatus"></div>
            <div id="modalSeverity"></div>
         </div>
         <button onclick="document.getElementById('bugModalOverlay').style.display='none'" style="background:transparent;border:none;color:#94a3b8;font-size:26px;cursor:pointer;line-height:1;transition:color 0.2s;" onmouseover="this.style.color='#fff'" onmouseout="this.style.color='#94a3b8'">&times;</button>
      </div>
      <div id="modalBody" style="padding:24px;overflow-y:auto;display:flex;flex-direction:column;gap:16px;background:var(--bg-surface);">
        <!-- Metadata Grid -->
        <div style="display:grid;grid-template-columns:repeat(3, 1fr);gap:16px;">
          <div style="background:var(--bg-card);padding:12px;border-radius:8px;border:1px solid rgba(255,255,255,0.05);">
            <div style="color:var(--primary);font-size:11px;font-weight:700;margin-bottom:6px;">▮ 所属运行 (RUN ID)</div>
            <div id="modalRunId" style="color:#f8fafc;font-family:var(--font-mono);font-size:13px;">-</div>
          </div>
          <div style="background:var(--bg-card);padding:12px;border-radius:8px;border:1px solid rgba(255,255,255,0.05);">
            <div style="color:var(--primary);font-size:11px;font-weight:700;margin-bottom:6px;">▮ 发现日期</div>
            <div id="modalDate" style="color:#f8fafc;font-family:var(--font-mono);font-size:13px;">-</div>
          </div>
          <div style="background:var(--bg-card);padding:12px;border-radius:8px;border:1px solid rgba(255,255,255,0.05);">
            <div style="color:var(--primary);font-size:11px;font-weight:700;margin-bottom:6px;">▮ 历史累计复现</div>
            <div id="modalOccurrences" style="color:#f8fafc;font-family:var(--font-mono);font-size:13px;">-</div>
          </div>
          <div style="background:var(--bg-card);padding:12px;border-radius:8px;border:1px solid rgba(255,255,255,0.05);">
            <div style="color:var(--primary);font-size:11px;font-weight:700;margin-bottom:6px;">▮ 最近一次出现</div>
            <div id="modalLastSeen" style="color:#f8fafc;font-family:var(--font-mono);font-size:13px;">-</div>
          </div>
          <div style="background:var(--bg-card);padding:12px;border-radius:8px;border:1px solid rgba(255,255,255,0.05);">
            <div style="color:var(--primary);font-size:11px;font-weight:700;margin-bottom:6px;">▮ 本次对应步骤</div>
            <div id="modalGlobalStep" style="color:#f8fafc;font-family:var(--font-mono);font-size:13px;">-</div>
          </div>
          <div style="background:var(--bg-card);padding:12px;border-radius:8px;border:1px solid rgba(255,255,255,0.05);">
            <div style="color:var(--primary);font-size:11px;font-weight:700;margin-bottom:6px;">▮ 操作类型</div>
            <div id="modalActionType" style="color:#f8fafc;font-family:var(--font-mono);font-size:13px;">-</div>
          </div>
          <div style="background:var(--bg-card);padding:12px;border-radius:8px;border:1px solid rgba(255,255,255,0.05);">
            <div style="color:var(--primary);font-size:11px;font-weight:700;margin-bottom:6px;">▮ 目标元素</div>
            <div id="modalTargetElement" style="color:#f8fafc;font-size:13px;">-</div>
          </div>
          <div style="background:var(--bg-card);padding:12px;border-radius:8px;border:1px solid rgba(255,255,255,0.05);">
            <div style="color:var(--primary);font-size:11px;font-weight:700;margin-bottom:6px;">▮ 缺陷处理人</div>
            <div id="modalAssignee" style="color:#f8fafc;font-size:13px;">-</div>
          </div>
          <div style="background:var(--bg-card);padding:12px;border-radius:8px;border:1px solid rgba(255,255,255,0.05);">
            <div style="color:var(--primary);font-size:11px;font-weight:700;margin-bottom:6px;">▮ 业务标签</div>
            <div id="modalTags" style="color:#f8fafc;font-size:13px;display:flex;flex-wrap:wrap;gap:4px;align-items:center;">-</div>
          </div>
        </div>

        <!-- Full Width Fields -->
        <div style="background:var(--bg-card);padding:16px;border-radius:8px;border:1px solid rgba(255,255,255,0.05);">
          <div style="color:var(--primary);font-size:11px;font-weight:700;margin-bottom:8px;">▮ 缺陷标题 (TITLE)</div>
          <div id="modalTitleText" style="color:#f8fafc;font-size:14px;line-height:1.5;">-</div>
        </div>
        <div style="background:var(--bg-card);padding:16px;border-radius:8px;border:1px solid rgba(255,255,255,0.05);">
          <div style="color:var(--primary);font-size:11px;font-weight:700;margin-bottom:8px;">▮ 业务路径 / 触发步骤</div>
          <div id="modalUiPath" style="color:#cbd5e1;font-size:13px;line-height:1.5;">-</div>
        </div>
        <div style="background:var(--bg-card);padding:16px;border-radius:8px;border:1px solid rgba(255,255,255,0.05);">
          <div style="color:var(--primary);font-size:11px;font-weight:700;margin-bottom:8px;">▮ 异常诊断结果 / 堆栈</div>
          <div id="modalActual" style="color:#fca5a5;font-family:var(--font-mono);font-size:13px;line-height:1.6;white-space:pre-wrap;">-</div>
        </div>
        <div style="background:var(--bg-card);padding:16px;border-radius:8px;border:1px solid rgba(255,255,255,0.05);">
          <div style="color:var(--primary);font-size:11px;font-weight:700;margin-bottom:8px;">▮ 归因分析备注</div>
          <div id="modalAnalysis" style="color:#cbd5e1;font-size:13px;line-height:1.6;white-space:pre-wrap;">-</div>
        </div>
        <div style="background:var(--bg-card);padding:16px;border-radius:8px;border:1px solid rgba(255,255,255,0.05);">
          <div style="color:var(--primary);font-size:11px;font-weight:700;margin-bottom:8px;">▮ 案发现场截图凭据 (操作前 vs 报错现场)</div>
          <div id="modalScreenshot" style="margin-top:8px;">-</div>
        </div>

        <div id="modalActionFooter" style="display:flex;justify-content:flex-end;gap:12px;margin-top:4px;">
        </div>

      </div>
    </div>
  </div>
  <!-- Image Viewer Overlay -->
  <div id="imageViewerOverlay" style="display:none;position:fixed;top:0;left:0;width:100vw;height:100vh;background:rgba(0,0,0,0.9);z-index:10000;align-items:center;justify-content:center;cursor:zoom-out;" onclick="this.style.display='none'">
    <img id="imageViewerImg" src="" style="max-width:90%;max-height:90%;object-fit:contain;border-radius:8px;box-shadow:0 25px 50px -12px rgba(0,0,0,1);">
  </div>

  <script>
    const allRuns = {runs_json};
    const allBugs = {bugs_json};
    let currentFilter = 'all';
    let searchQuery = '';
    let currentRunPage = 1;
    let runsPerPage = 10;

    function switchMainTab(tabId, event) {{
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
      document.getElementById(tabId).classList.add('active');
      event.currentTarget.classList.add('active');
      
      // 切换 Tab 时重置筛选条件到“全部模式”
      if (tabId === 'tab-runs') {{
          currentFilter = 'all';
          currentRunPage = 1;
          searchQuery = '';
          const searchInput = document.getElementById('runSearch');
          if(searchInput) searchInput.value = '';
          
          document.querySelectorAll('#tab-runs .filter-pill').forEach(b => b.classList.remove('active'));
          const firstPill = document.querySelector('#tab-runs .filter-pill');
          if(firstPill) firstPill.classList.add('active');
          renderRuns();
      }} else if (tabId === 'tab-bugs') {{
          currentBugFilter = 'all';
          currentBugStatusFilter = 'all';
          currentBugPage = 1;
          bugSearchQuery = '';
          const modeSel = document.getElementById('bugModeFilter');
          const statusSel = document.getElementById('bugStatusFilter');
          const searchInput = document.getElementById('bugSearch');
          if (modeSel) modeSel.value = 'all';
          if (statusSel) statusSel.value = 'all';
          if (searchInput) searchInput.value = '';
          renderBugs();
      }}
    }}

    function filterRuns(type, event) {{
      currentFilter = type;
      currentRunPage = 1;
      document.querySelectorAll('.filter-pill').forEach(b => b.classList.remove('active'));
      event.currentTarget.classList.add('active');
      renderRuns();
    }}

    let currentAppFilter = 'all';

    function handleAppFilterChange(app) {{
      currentAppFilter = app;
      currentRunPage = 1;
      renderRuns();
    }}

    function handleSearch() {{
      searchQuery = document.getElementById('runSearch').value.toLowerCase().trim();
      currentRunPage = 1;
      renderRuns();
    }}

    function changeRunsPerPage(size) {{
        runsPerPage = parseInt(size);
        currentRunPage = 1;
        renderRuns();
    }}

    function changeRunPage(page) {{
        currentRunPage = page;
        renderRuns();
    }}

    function renderRuns() {{
      const container = document.getElementById('runsContainer');
      const pageControls = document.getElementById('runsPaginationControls');
      const filtered = allRuns.filter(r => {{
        const runId = (r.run_id || '').toLowerCase();
        if (currentFilter === 'explore' && !runId.startsWith('explore_')) return false;
        if (currentFilter === 'smoke' && !runId.startsWith('smoke_')) return false;
        if (currentFilter === 'yaml' && !runId.startsWith('yaml_')) return false;

        if (currentAppFilter !== 'all' && (r.app || 'zhaiwan') !== currentAppFilter) return false;

        if (searchQuery) {{
          const matchId = String(runId).includes(searchQuery);
          const matchObj = String(r.macro_objective || '').toLowerCase().includes(searchQuery);
          const matchStart = String(r.start_time || '').toLowerCase().includes(searchQuery);
          const matchApp = String(r.app_name || '').toLowerCase().includes(searchQuery);
          if (!matchId && !matchObj && !matchStart && !matchApp) return false;
        }}
        return true;
      }});

      if (filtered.length === 0) {{
        container.innerHTML = '<div style="text-align:center;padding:80px;color:var(--text-dim);">没有符合条件的运行记录</div>';
        if (pageControls) pageControls.innerHTML = '';
        return;
      }}

      const totalPages = Math.ceil(filtered.length / runsPerPage) || 1;
      if (currentRunPage > totalPages) currentRunPage = totalPages;
      if (currentRunPage < 1) currentRunPage = 1;

      const startIndex = (currentRunPage - 1) * runsPerPage;
      const paginatedRuns = filtered.slice(startIndex, startIndex + runsPerPage);

      let html = '';
      paginatedRuns.forEach(r => {{
        const runId = r.run_id || '';
        let modeClass = 'explore';
        let modeLabel = '自主探索';
        if (runId.startsWith('smoke_')) {{
          modeClass = 'smoke';
          modeLabel = '冒烟测试';
        }} else if (runId.startsWith('yaml_')) {{
          modeClass = 'yaml';
          modeLabel = '回归测试';
        }}

        const appKey = r.app || 'zhaiwan';
        const isLiwutong = appKey === 'liwutong';
        const appBadgeHtml = `
          <span style="background:${{isLiwutong ? 'rgba(16,185,129,0.15)' : 'rgba(99,102,241,0.15)'}};color:${{isLiwutong ? '#34d399' : '#818cf8'}};border:1px solid ${{isLiwutong ? 'rgba(16,185,129,0.35)' : 'rgba(99,102,241,0.35)'}};font-size:11px;padding:2px 8px;border-radius:9999px;font-weight:700;display:inline-flex;align-items:center;gap:4px;">
            ${{isLiwutong ? '🏔️ 里伍铜' : '⛰️ 寨湾'}}
          </span>
        `;

        const kpi = r.kpi || {{}};
        const totalSteps = kpi.total_steps || 0;
        const bugsCount = kpi.bugs_count || 0;
        const apisCount = kpi.apis_count || 0;
        const pagesCount = kpi.page_scopes_count || 0;
        const totalMenus = kpi.total_menus_count || 33;
        const coverageRate = (kpi.page_coverage_rate !== undefined && kpi.page_coverage_rate !== null) ? kpi.page_coverage_rate : ((pagesCount / totalMenus) * 100).toFixed(1);

        html += `
          <div class="run-card">
            <div class="run-card-main">
              <div class="run-header" style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
                <span class="mode-tag ${{modeClass}}">${{modeLabel}}</span>
                ${{appBadgeHtml}}
                <span class="run-id-title">${{escapeHtml(runId)}}</span>
              </div>

              <div class="run-meta-row">
                <div class="run-meta-item">⏱️ 耗时: <strong>${{escapeHtml(r.duration || '未知')}}</strong></div>
                <div class="run-meta-item">📅 开始: <strong>${{escapeHtml(r.start_time || '未知')}}</strong></div>
                <div class="run-meta-item">🏁 结束: <strong>${{escapeHtml(r.end_time || '未知')}}</strong></div>
              </div>

              <div class="objective-quote">
                <strong>🎯 宏观目标:</strong> ${{escapeHtml(r.macro_objective || '常规测试')}}
              </div>

              <div class="run-badges-row">
                <div class="metric-badge">🎯 ${{totalSteps}} 步轨迹</div>
                <div class="metric-badge ${{bugsCount > 0 ? 'bugs' : ''}}">🐞 ${{bugsCount}} 个缺陷</div>
                <div class="metric-badge">🌐 ${{apisCount}} 个业务接口</div>
                <div class="metric-badge">🗺️ ${{pagesCount}}/${{totalMenus}} 二级页面 (${{coverageRate}}%)</div>
              </div>
            </div>

            <div>
              <a href="${{r.report_url}}" class="open-report-btn">
                <span>👉 测试报告</span>
              </a>
            </div>
          </div>
        `;
      }});

      container.innerHTML = html;

      if (pageControls) {{
         pageControls.innerHTML = `
            <div style="color:var(--text-dim);font-size:12px;">共 ${{filtered.length}} 条记录</div>
            <select style="background:var(--bg-surface);border:1px solid rgba(255,255,255,0.1);color:var(--text-muted);border-radius:4px;padding:4px 8px;font-size:12px;outline:none;cursor:pointer;" onchange="changeRunsPerPage(this.value)">
                <option value="10" ${{runsPerPage===10?'selected':''}}>10 条/页</option>
                <option value="20" ${{runsPerPage===20?'selected':''}}>20 条/页</option>
                <option value="50" ${{runsPerPage===50?'selected':''}}>50 条/页</option>
                <option value="100" ${{runsPerPage===100?'selected':''}}>100 条/页</option>
            </select>
            
            <div style="display:flex;gap:4px;align-items:center;">
                <button onclick="changeRunPage(${{currentRunPage - 1}})" ${{currentRunPage === 1 ? 'disabled' : ''}} style="background:var(--bg-surface);border:1px solid rgba(255,255,255,0.1);color:var(--text-muted);border-radius:4px;padding:4px 8px;cursor:${{currentRunPage === 1 ? 'not-allowed' : 'pointer'}};font-size:12px;opacity:${{currentRunPage === 1 ? '0.5' : '1'}};">上一页</button>
                <span style="color:var(--text-muted);font-size:12px;margin:0 4px;">${{currentRunPage}} / ${{totalPages}}</span>
                <button onclick="changeRunPage(${{currentRunPage + 1}})" ${{currentRunPage === totalPages ? 'disabled' : ''}} style="background:var(--bg-surface);border:1px solid rgba(255,255,255,0.1);color:var(--text-muted);border-radius:4px;padding:4px 8px;cursor:${{currentRunPage === totalPages ? 'not-allowed' : 'pointer'}};font-size:12px;opacity:${{currentRunPage === totalPages ? '0.5' : '1'}};">下一页</button>
            </div>
            
            <div style="display:flex;gap:4px;align-items:center;margin-left:8px;">
                <span style="color:var(--text-dim);font-size:12px;">跳至</span>
                <input type="number" id="runPageJumpInput" min="1" max="${{totalPages}}" style="width:50px;background:var(--bg-surface);border:1px solid rgba(255,255,255,0.1);color:var(--text-muted);border-radius:4px;padding:4px;font-size:12px;text-align:center;outline:none;">
                <span style="color:var(--text-dim);font-size:12px;">页</span>
                <button onclick="const p=parseInt(document.getElementById('runPageJumpInput').value);if(!isNaN(p)&amp;&amp;p&gt;=1&amp;&amp;p&lt;=${{totalPages}})changeRunPage(p);" style="background:var(--bg-surface);border:1px solid var(--primary);color:var(--primary);border-radius:4px;padding:4px 8px;cursor:pointer;font-size:12px;">跳转</button>
            </div>
         `;
      }}
    }}

    let currentBugPage = 1;
    let bugsPerPage = 10;
    let currentBugFilter = 'all';
    let currentBugStatusFilter = 'all';
    let bugSearchQuery = '';

    function handleBugFilterChange() {{
      const modeSel = document.getElementById('bugModeFilter');
      const statusSel = document.getElementById('bugStatusFilter');
      if (modeSel) currentBugFilter = modeSel.value;
      if (statusSel) currentBugStatusFilter = statusSel.value;
      currentBugPage = 1;
      renderBugs();
    }}

    function resetBugFilters() {{
      currentBugFilter = 'all';
      currentBugStatusFilter = 'all';
      bugSearchQuery = '';
      currentBugPage = 1;
      const modeSel = document.getElementById('bugModeFilter');
      const statusSel = document.getElementById('bugStatusFilter');
      const searchInput = document.getElementById('bugSearch');
      if (modeSel) modeSel.value = 'all';
      if (statusSel) statusSel.value = 'all';
      if (searchInput) searchInput.value = '';
      renderBugs();
    }}

    function filterBugs(type, event) {{
      currentBugFilter = type;
      currentBugPage = 1;
      const modeSel = document.getElementById('bugModeFilter');
      if (modeSel) modeSel.value = type;
      renderBugs();
    }}

    function handleBugSearch() {{
      bugSearchQuery = document.getElementById('bugSearch').value.toLowerCase().trim();
      currentBugPage = 1;
      renderBugs();
    }}

    function changeBugsPerPage(size) {{
        bugsPerPage = parseInt(size);
        currentBugPage = 1;
        renderBugs();
    }}

    function changeBugPage(page) {{
        currentBugPage = page;
        renderBugs();
    }}

    function renderBugs() {{
      const tbody = document.getElementById('bugsTbody');
      const pageControls = document.getElementById('paginationControls');
      
      const filtered = allBugs.filter(b => {{
        const runId = (b.run_id || '').toLowerCase();
        // 1. 模式过滤
        if (currentBugFilter === 'explore' && !runId.startsWith('explore_')) return false;
        if (currentBugFilter === 'smoke' && !runId.startsWith('smoke_')) return false;
        if (currentBugFilter === 'yaml' && !runId.startsWith('yaml_')) return false;

        // 2. 状态过滤 (对齐 'Open' 与 '激活')
        if (currentBugStatusFilter !== 'all') {{
          let bStatus = b.status || '激活';
          if (bStatus === 'Open') bStatus = '激活';
          if (bStatus !== currentBugStatusFilter) return false;
        }}

        // 3. 模糊搜索：缺陷编号、RUN ID、业务路径与目标、异常详情
        if (bugSearchQuery) {{
          const matchId = String(b.id || '').toLowerCase().includes(bugSearchQuery);
          const matchRunId = String(b.run_id || '').toLowerCase().includes(bugSearchQuery);
          const matchUiPath = String(b.ui_path || '').toLowerCase().includes(bugSearchQuery);
          const matchTitle = String(b.title || '').toLowerCase().includes(bugSearchQuery);
          const matchStep = String(b.step || '').toLowerCase().includes(bugSearchQuery);
          const matchActual = String(b.actual || '').toLowerCase().includes(bugSearchQuery);
          if (!matchId && !matchRunId && !matchUiPath && !matchTitle && !matchStep && !matchActual) return false;
        }}
        return true;
      }});

      if (filtered.length === 0) {{
        tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:50px;color:var(--text-dim);">🎉 当前筛选条件下无任何缺陷记录</td></tr>';
        if (pageControls) pageControls.innerHTML = '';
        return;
      }}

      // Sort bugs descending by ID (which encodes the time, e.g. BUG-20261001-...)
      filtered.sort((a, b) => b.id.localeCompare(a.id));

      const totalPages = Math.ceil(filtered.length / bugsPerPage) || 1;
      if (currentBugPage > totalPages) currentBugPage = totalPages;
      if (currentBugPage < 1) currentBugPage = 1;

      const startIndex = (currentBugPage - 1) * bugsPerPage;
      const paginatedBugs = filtered.slice(startIndex, startIndex + bugsPerPage);

      let html = '';
      paginatedBugs.forEach(b => {{
        const runPath = b.rel_run_path || b.run_id || '';
        const beforeShotUrl = b.before_screenshot ? (b.before_screenshot.startsWith('../') ? b.before_screenshot.replace('../', './') : `./${{runPath}}/${{b.before_screenshot}}`) : '';
        const relShotUrl = b.rel_screenshot ? (b.rel_screenshot.startsWith('../') ? b.rel_screenshot.replace('../', './') : `./${{runPath}}/${{b.rel_screenshot}}`) : '';

        let imgHtml = '';
        if (beforeShotUrl && relShotUrl) {{
          imgHtml = `
            <div style="display:flex;gap:6px;align-items:center;justify-content:center;">
              <div style="position:relative;display:inline-block;cursor:zoom-in;" title="点击放大操作前截图" onclick="showImageFullscreen('${{beforeShotUrl}}', event)">
                <span style="position:absolute;top:2px;left:2px;font-size:9px;font-weight:700;padding:1px 4px;border-radius:3px;color:#fff;background:rgba(16,185,129,0.85);z-index:2;line-height:1.2;">前</span>
                <img src="${{beforeShotUrl}}" style="width:68px;height:42px;object-fit:cover;border-radius:4px;border:1px solid rgba(16,185,129,0.4);display:block;transition:transform 0.2s;" onmouseover="this.style.transform='scale(1.08)'" onmouseout="this.style.transform='scale(1)'"/>
              </div>
              <div style="position:relative;display:inline-block;cursor:zoom-in;" title="点击放大案发现场截图" onclick="showImageFullscreen('${{relShotUrl}}', event)">
                <span style="position:absolute;top:2px;left:2px;font-size:9px;font-weight:700;padding:1px 4px;border-radius:3px;color:#fff;background:rgba(244,63,94,0.85);z-index:2;line-height:1.2;">案发</span>
                <img src="${{relShotUrl}}" style="width:68px;height:42px;object-fit:cover;border-radius:4px;border:1px solid rgba(244,63,94,0.4);display:block;transition:transform 0.2s;" onmouseover="this.style.transform='scale(1.08)'" onmouseout="this.style.transform='scale(1)'"/>
              </div>
            </div>`;
        }} else if (relShotUrl) {{
          imgHtml = `
            <div style="display:flex;justify-content:center;">
              <div style="position:relative;display:inline-block;cursor:zoom-in;" title="点击放大案发现场截图" onclick="showImageFullscreen('${{relShotUrl}}', event)">
                <span style="position:absolute;top:2px;left:2px;font-size:9px;font-weight:700;padding:1px 4px;border-radius:3px;color:#fff;background:rgba(244,63,94,0.85);z-index:2;line-height:1.2;">案发</span>
                <img src="${{relShotUrl}}" style="width:78px;height:46px;object-fit:cover;border-radius:4px;border:1px solid rgba(255,255,255,0.15);display:block;transition:transform 0.2s;" onmouseover="this.style.transform='scale(1.08)'" onmouseout="this.style.transform='scale(1)'"/>
              </div>
            </div>`;
        }} else {{
          imgHtml = '<span style="color:#64748b;font-size:12px;">无截图</span>';
        }}
        const optionsConfig = [
          {{ value: '激活', label: '激活', color: '#f43f5e' }},
          {{ value: '已解决', label: '已解决', color: '#10b981' }},
          {{ value: '已提单', label: '已提单', color: '#3b82f6' }},
          {{ value: '已关闭', label: '已关闭', color: '#64748b' }},
          {{ value: '误报', label: '误报', color: '#64748b' }}
        ];
        let curStatus = b.status;
        if (curStatus === 'Open') curStatus = '激活';
        if (!curStatus) curStatus = '激活';

        let optionsHtml = '';
        optionsConfig.forEach(opt => {{
            const selected = (curStatus === opt.value) ? 'selected' : '';
            optionsHtml += `<option value="${{opt.value}}" ${{selected}} style="background:#0f172a;color:${{opt.color}};font-weight:600;">${{opt.label}}</option>`;
        }});
        
        const matched = optionsConfig.find(o => o.value === curStatus);
        const selectColor = matched ? matched.color : '#94a3b8';

        const statusBadge = `<select onchange="changeBugStatus('${{escapeHtml(b.id)}}', this)" style="background:rgba(255,255,255,0.06);color:${{selectColor}};padding:3px 10px;border-radius:6px;font-size:12px;font-weight:700;border:1px solid rgba(255,255,255,0.18);outline:none;cursor:pointer;text-align:center;transition:all 0.2s;">
            ${{optionsHtml}}
        </select>`;

        const sevLevel = parseInt(b.severity) || 3;
        const sevBadgeConfig = {{
          1: {{ label: '1 致命', color: '#ef4444', bg: 'rgba(239,68,68,0.15)', border: 'rgba(239,68,68,0.3)' }},
          2: {{ label: '2 严重', color: '#f97316', bg: 'rgba(249,115,22,0.15)', border: 'rgba(249,115,22,0.3)' }},
          3: {{ label: '3 一般', color: '#eab308', bg: 'rgba(234,179,8,0.15)', border: 'rgba(234,179,8,0.3)' }},
          4: {{ label: '4 轻微', color: '#94a3b8', bg: 'rgba(148,163,184,0.15)', border: 'rgba(148,163,184,0.3)' }}
        }};
        const sb = sevBadgeConfig[sevLevel] || sevBadgeConfig[3];
        const sevBadge = `<span style="background:${{sb.bg}};color:${{sb.color}};border:1px solid ${{sb.border}};padding:2px 8px;border-radius:4px;font-size:11px;font-weight:700;white-space:nowrap;">${{sb.label}}</span>`;

        html += `
          <tr>
            <td><span style="font-family:var(--font-mono);font-weight:700;color:#fb7185;font-size:12px;">${{escapeHtml(b.id)}}</span></td>
            <td>${{sevBadge}}</td>
            <td><span style="font-family:var(--font-mono);color:var(--text-muted);font-size:11px;">${{escapeHtml(b.run_id)}}</span></td>
            <td>${{statusBadge}}</td>
            <td style="color:#cbd5e1;font-size:13px;line-height:1.4;">
                <div style="color:#38bdf8;font-size:11px;font-weight:600;margin-bottom:4px;">📍 ${{escapeHtml(b.ui_path || '首页')}}</div>
                <div style="font-weight:600;margin-bottom:4px;color:#f8fafc;">${{escapeHtml(b.title)}}</div>
                ${{(() => {{
                    const stepStr = String(b.step || '').trim();
                    const uiPathStr = String(b.ui_path || '').trim();
                    if (!stepStr || stepStr === uiPathStr) return '';
                    const stepPrefix = b.step_num ? `<span style="color:#a5b4fc;font-weight:600;">[Step ${{b.step_num}}]</span> ` : '';
                    return `<div style="color:#94a3b8;font-family:var(--font-mono);font-size:11px;margin-top:2px;line-height:1.4;">${{stepPrefix}}${{escapeHtml(stepStr)}}</div>`;
                }})()}}
            </td>
            <td><div style="font-family:var(--font-mono);font-size:11px;color:#fca5a5;max-height:80px;overflow-y:auto;line-height:1.4;word-break:break-all;padding-right:8px;">${{escapeHtml(b.actual || '')}}</div></td>
            <td style="text-align:center;vertical-align:middle;">${{imgHtml}}</td>
            <td>
              <div style="display:flex;flex-direction:column;gap:6px;">
                <a href="${{b.report_link}}" style="background:transparent;border:1px solid rgba(255,255,255,0.1);color:#94a3b8;border-radius:4px;padding:4px 8px;font-size:11px;text-align:center;text-decoration:none;cursor:pointer;transition:all 0.2s;" onmouseover="this.style.color='#fff';this.style.borderColor='var(--primary)'" onmouseout="this.style.color='#94a3b8';this.style.borderColor='rgba(255,255,255,0.1)'">报告详情</a>
                <button onclick="showBugModal('${{escapeHtml(b.id)}}')" style="background:rgba(99,102,241,0.1);border:1px solid var(--primary);color:var(--primary);border-radius:4px;padding:4px 8px;font-size:11px;text-align:center;text-decoration:none;transition:all 0.2s;cursor:pointer;" onmouseover="this.style.background='var(--primary)';this.style.color='#fff'" onmouseout="this.style.background='rgba(99,102,241,0.1)';this.style.color='var(--primary)'">Bug 详情</button>
              </div>
            </td>
          </tr>
        `;
      }});
      tbody.innerHTML = html;

      if (pageControls) {{
         pageControls.innerHTML = `
            <div style="color:var(--text-dim);font-size:12px;">共 ${{filtered.length}} 条记录</div>
            <select style="background:var(--bg-surface);border:1px solid rgba(255,255,255,0.1);color:var(--text-muted);border-radius:4px;padding:4px 8px;font-size:12px;outline:none;cursor:pointer;" onchange="changeBugsPerPage(this.value)">
                <option value="10" ${{bugsPerPage===10?'selected':''}}>10 条/页</option>
                <option value="20" ${{bugsPerPage===20?'selected':''}}>20 条/页</option>
                <option value="50" ${{bugsPerPage===50?'selected':''}}>50 条/页</option>
                <option value="100" ${{bugsPerPage===100?'selected':''}}>100 条/页</option>
            </select>
            
            <div style="display:flex;gap:4px;align-items:center;">
                <button onclick="changeBugPage(${{currentBugPage - 1}})" ${{currentBugPage === 1 ? 'disabled' : ''}} style="background:var(--bg-surface);border:1px solid rgba(255,255,255,0.1);color:var(--text-muted);border-radius:4px;padding:4px 8px;cursor:${{currentBugPage === 1 ? 'not-allowed' : 'pointer'}};font-size:12px;opacity:${{currentBugPage === 1 ? '0.5' : '1'}};">上一页</button>
                <span style="color:var(--text-muted);font-size:12px;margin:0 4px;">${{currentBugPage}} / ${{totalPages}}</span>
                <button onclick="changeBugPage(${{currentBugPage + 1}})" ${{currentBugPage === totalPages ? 'disabled' : ''}} style="background:var(--bg-surface);border:1px solid rgba(255,255,255,0.1);color:var(--text-muted);border-radius:4px;padding:4px 8px;cursor:${{currentBugPage === totalPages ? 'not-allowed' : 'pointer'}};font-size:12px;opacity:${{currentBugPage === totalPages ? '0.5' : '1'}};">下一页</button>
            </div>
            
            <div style="display:flex;gap:4px;align-items:center;margin-left:8px;">
                <span style="color:var(--text-dim);font-size:12px;">跳至</span>
                <input type="number" id="pageJumpInput" min="1" max="${{totalPages}}" style="width:50px;background:var(--bg-surface);border:1px solid rgba(255,255,255,0.1);color:var(--text-muted);border-radius:4px;padding:4px;font-size:12px;text-align:center;outline:none;">
                <span style="color:var(--text-dim);font-size:12px;">页</span>
                <button onclick="const p=parseInt(document.getElementById('pageJumpInput').value);if(!isNaN(p)&amp;&amp;p&gt;=1&amp;&amp;p&lt;=${{totalPages}})changeBugPage(p);" style="background:var(--bg-surface);border:1px solid var(--primary);color:var(--primary);border-radius:4px;padding:4px 8px;cursor:pointer;font-size:12px;">跳转</button>
            </div>
         `;
      }}
    }}

    function showBugModal(bugId) {{
      const b = allBugs.find(x => x.id === bugId);
      if (!b) return;
      
      // 1. 修复 BUG 单号显示
      document.getElementById('modalBugId').innerText = b.id;
      
      const statusMeta = {{
        '激活': {{ bg: 'rgba(244,63,94,0.15)', color: '#f43f5e', border: 'rgba(244,63,94,0.3)' }},
        'Open': {{ bg: 'rgba(244,63,94,0.15)', color: '#f43f5e', border: 'rgba(244,63,94,0.3)' }},
        '已解决': {{ bg: 'rgba(16,185,129,0.15)', color: '#10b981', border: 'rgba(16,185,129,0.3)' }},
        '已提单': {{ bg: 'rgba(59,130,246,0.15)', color: '#3b82f6', border: 'rgba(59,130,246,0.3)' }},
        '已关闭': {{ bg: 'rgba(100,116,139,0.15)', color: '#94a3b8', border: 'rgba(100,116,139,0.3)' }},
        '误报': {{ bg: 'rgba(100,116,139,0.15)', color: '#94a3b8', border: 'rgba(100,116,139,0.3)' }}
      }};
      const sm = statusMeta[b.status] || {{ bg: 'rgba(100,116,139,0.15)', color: '#94a3b8', border: 'rgba(100,116,139,0.3)' }};
      const statusText = (b.status === 'Open') ? '激活' : (b.status || '激活');
      document.getElementById('modalStatus').innerHTML = `<div style="background:${{sm.bg}};color:${{sm.color}};padding:6px 12px;border-radius:6px;font-size:14px;font-weight:700;border:1px solid ${{sm.border}}">${{statusText}}</div>`;
      
      // 2. 禅道严重度枚举映射 (1致命, 2严重, 3一般, 4轻微)
      const sevLevel = parseInt(b.severity) || 3;
      const sevMeta = {{
        1: {{ label: '🔥 1 致命', color: '#ef4444', bg: 'rgba(239,68,68,0.15)', border: 'rgba(239,68,68,0.3)' }},
        2: {{ label: '⚡ 2 严重', color: '#f97316', bg: 'rgba(249,115,22,0.15)', border: 'rgba(249,115,22,0.3)' }},
        3: {{ label: '⚠️ 3 一般', color: '#eab308', bg: 'rgba(234,179,8,0.15)', border: 'rgba(234,179,8,0.3)' }},
        4: {{ label: 'ℹ️ 4 轻微', color: '#94a3b8', bg: 'rgba(148,163,184,0.15)', border: 'rgba(148,163,184,0.3)' }}
      }};
      const curSev = sevMeta[sevLevel] || sevMeta[3];
      document.getElementById('modalSeverity').innerHTML = `<div style="background:${{curSev.bg}};color:${{curSev.color}};padding:6px 12px;border-radius:6px;font-weight:700;border:1px solid ${{curSev.border}};font-size:13px;">${{curSev.label}}</div>`;
      
      document.getElementById('modalRunId').innerText = b.run_id || '无';
      document.getElementById('modalDate').innerText = b.date || '无';
      document.getElementById('modalOccurrences').innerText = (b.occurrences !== undefined && b.occurrences !== null) ? `${{b.occurrences}} 次` : '1 次';
      document.getElementById('modalLastSeen').innerText = b.last_seen || '无';
      document.getElementById('modalGlobalStep').innerText = b.step_num ? `Step ${{b.step_num}}` : (b.global_step ? `全局 Step ${{b.global_step}}` : '无对应步骤');
      document.getElementById('modalActionType').innerText = b.action_type || '无';
      document.getElementById('modalTargetElement').innerText = b.target_element || '无';
      document.getElementById('modalAssignee').innerHTML = `<span style="color:#f8fafc;">${{escapeHtml(b.assignee || 'Unassigned')}}</span>`;
      
      const tagsList = Array.isArray(b.tags) ? b.tags : (b.tags && b.tags !== '无' ? String(b.tags).split(',').map(s => s.trim()) : []);
      if (tagsList.length > 0) {{
        document.getElementById('modalTags').innerHTML = tagsList.map(t => `<span style="background:rgba(99,102,241,0.15);color:#a5b4fc;border:1px solid rgba(99,102,241,0.3);padding:2px 8px;border-radius:4px;font-size:11px;font-weight:600;margin-right:4px;">${{escapeHtml(t)}}</span>`).join('');
      }} else {{
        document.getElementById('modalTags').innerHTML = '<span style="color:#64748b;">无</span>';
      }}
      
      document.getElementById('modalTitleText').innerText = b.title || '无标题';
      document.getElementById('modalUiPath').innerHTML = `<span style="color:#38bdf8;font-weight:600;">📍 ${{escapeHtml(b.ui_path || '首页')}}</span>`;
      document.getElementById('modalActual').innerText = b.actual || '无详情';
      document.getElementById('modalAnalysis').innerHTML = `<div style="color:#cbd5e1;white-space:pre-wrap;line-height:1.6;">${{escapeHtml(b.analysis_notes || '暂无归因分析备注')}}</div>`;
      
      const runPath = b.rel_run_path || b.run_id || '';
      const beforeShotUrl = b.before_screenshot ? (b.before_screenshot.startsWith('../') ? b.before_screenshot.replace('../', './') : `./${{runPath}}/${{b.before_screenshot}}`) : '';
      const relShotUrl = b.rel_screenshot ? (b.rel_screenshot.startsWith('../') ? b.rel_screenshot.replace('../', './') : `./${{runPath}}/${{b.rel_screenshot}}`) : '';

      if (beforeShotUrl && relShotUrl) {{
          document.getElementById('modalScreenshot').innerHTML = `
            <div class="bug-screenshots-duo">
              <div class="bug-thumb-box" onclick="showImageFullscreen('${{beforeShotUrl}}', event)" title="点击放大操作前截图">
                <span class="bug-thumb-tag tag-before">操作前 (目标位置)</span>
                <img src="${{beforeShotUrl}}" alt="Before" loading="lazy">
                <div class="zoom-hint">🔍 点击放大</div>
              </div>
              <div class="bug-thumb-box" onclick="showImageFullscreen('${{relShotUrl}}', event)" title="点击放大案发现场截图">
                <span class="bug-thumb-tag tag-after">案发现场 (报错)</span>
                <img src="${{relShotUrl}}" alt="Crash" loading="lazy">
                <div class="zoom-hint">🔍 点击放大</div>
              </div>
            </div>`;
      }} else if (relShotUrl) {{
          document.getElementById('modalScreenshot').innerHTML = `
            <div class="bug-thumb-box" style="max-width:550px;" onclick="showImageFullscreen('${{relShotUrl}}', event)" title="点击放大案发现场截图">
              <span class="bug-thumb-tag tag-after">案发现场 (报错)</span>
              <img src="${{relShotUrl}}" alt="Crash Screenshot" loading="lazy">
              <div class="zoom-hint">🔍 点击放大核验</div>
            </div>`;
      }} else {{
          document.getElementById('modalScreenshot').innerHTML = '<span style="color:#64748b;">无截图数据</span>';
      }}
      
      let footerHtml = '';
      if (b.report_link && b.report_link !== '#') {{
        footerHtml += `<a href="${{b.report_link}}" target="_blank" style="background:var(--primary);color:#fff;text-decoration:none;font-size:12px;font-weight:600;padding:8px 16px;border-radius:6px;display:inline-flex;align-items:center;gap:6px;transition:all 0.2s;" onmouseover="this.style.background='#4f46e5'" onmouseout="this.style.background='var(--primary)'">🔗 打开对应完整测试报告 ➔</a>`;
      }}
      footerHtml += `<button style="background:rgba(99,102,241,0.18);border:1px solid var(--primary);color:#a5b4fc;font-size:12px;font-weight:600;padding:8px 16px;border-radius:6px;cursor:pointer;display:inline-flex;align-items:center;gap:6px;transition:all 0.2s;" onclick="enterBugEditMode('${{escapeHtml(b.id)}}')">✏️ 编辑 Bug 详情</button>`;
      footerHtml += `<button style="background:var(--bg-card);border:1px solid rgba(255,255,255,0.1);color:var(--text-muted);font-size:12px;padding:8px 16px;border-radius:6px;cursor:pointer;" onclick="document.getElementById('bugModalOverlay').style.display='none'">关闭</button>`;
      document.getElementById('modalActionFooter').innerHTML = footerHtml;

      document.getElementById('bugModalOverlay').style.display = 'flex';
    }}

    function enterBugEditMode(bugId) {{
      const b = allBugs.find(x => x.id === bugId);
      if (!b) return;

      const curStatus = (b.status === 'Open' || !b.status) ? '激活' : b.status;
      const curSev = parseInt(b.severity) || 3;

      // 1. 状态变为下拉选择
      document.getElementById('modalStatus').innerHTML = `
        <select id="editBugStatus" style="background:#0f172a;color:#38bdf8;border:1px solid var(--primary);padding:6px 10px;border-radius:6px;font-size:13px;font-weight:700;outline:none;">
          <option value="激活" ${{curStatus==='激活'?'selected':''}}>🔴 激活</option>
          <option value="已解决" ${{curStatus==='已解决'?'selected':''}}>🟢 已解决</option>
          <option value="已提单" ${{curStatus==='已提单'?'selected':''}}>🔵 已提单</option>
          <option value="已关闭" ${{curStatus==='已关闭'?'selected':''}}>⚪ 已关闭</option>
          <option value="误报" ${{curStatus==='误报'?'selected':''}}>🛡️ 误报</option>
        </select>
      `;

      // 2. 严重度变为下拉选择
      document.getElementById('modalSeverity').innerHTML = `
        <select id="editBugSeverity" style="background:#0f172a;color:#f59e0b;border:1px solid #f59e0b;padding:6px 10px;border-radius:6px;font-size:13px;font-weight:700;outline:none;">
          <option value="1" ${{curSev===1?'selected':''}}>🔥 1 致命</option>
          <option value="2" ${{curSev===2?'selected':''}}>⚡ 2 严重</option>
          <option value="3" ${{curSev===3?'selected':''}}>⚠️ 3 一般 (默认)</option>
          <option value="4" ${{curSev===4?'selected':''}}>ℹ️ 4 轻微</option>
        </select>
      `;

      // 3. 处理人变为输入框
      document.getElementById('modalAssignee').innerHTML = `
        <input type="text" id="editBugAssignee" value="${{escapeHtml(b.assignee || 'Unassigned')}}" style="width:100%;background:#0f172a;border:1px solid rgba(255,255,255,0.2);color:#fff;padding:6px 8px;border-radius:4px;font-size:12px;outline:none;">
      `;

      // 4. 业务路径变为输入框
      document.getElementById('modalUiPath').innerHTML = `
        <input type="text" id="editBugUiPath" value="${{escapeHtml(b.ui_path || '首页')}}" style="width:100%;background:#0f172a;border:1px solid rgba(255,255,255,0.2);color:#38bdf8;padding:8px 10px;border-radius:6px;font-size:13px;font-weight:600;outline:none;">
      `;

      // 5. 分析备注变为多行文本输入框
      document.getElementById('modalAnalysis').innerHTML = `
        <textarea id="editBugAnalysis" rows="4" style="width:100%;background:#0f172a;border:1px solid var(--primary);color:#f8fafc;padding:10px;border-radius:6px;font-size:13px;line-height:1.5;outline:none;resize:vertical;" placeholder="在此输入原因分析、关闭理由、误报归因或复盘结论...">${{escapeHtml(b.analysis_notes || '')}}</textarea>
      `;

      // 6. 底部切换保存与取消按钮
      document.getElementById('modalActionFooter').innerHTML = `
        <button onclick="saveBugDetail('${{escapeHtml(b.id)}}')" style="background:#10b981;color:#fff;border:none;font-size:13px;font-weight:700;padding:8px 20px;border-radius:6px;cursor:pointer;display:inline-flex;align-items:center;gap:6px;box-shadow:0 4px 12px rgba(16,185,129,0.3);">💾 保存修改</button>
        <button onclick="showBugModal('${{escapeHtml(b.id)}}')" style="background:var(--bg-card);border:1px solid rgba(255,255,255,0.15);color:var(--text-muted);font-size:13px;padding:8px 16px;border-radius:6px;cursor:pointer;">取消</button>
      `;
    }}

    function saveBugDetail(bugId) {{
      const b = allBugs.find(x => x.id === bugId);
      if (!b) return;

      const newStatus = document.getElementById('editBugStatus').value;
      const newSeverity = parseInt(document.getElementById('editBugSeverity').value) || 3;
      const newAssignee = document.getElementById('editBugAssignee').value.trim() || 'Unassigned';
      const newUiPath = document.getElementById('editBugUiPath').value.trim() || '首页';
      const newAnalysis = document.getElementById('editBugAnalysis').value.trim();

      let apiBase = '';
      if (location.protocol === 'file:') {{
          apiBase = 'http://localhost:8080';
      }} else if (location.port !== '8080') {{
          apiBase = `${{location.protocol}}//${{location.hostname}}:8080`;
      }}
      const apiUrl = `${{apiBase}}/api/update_bug_detail`;

      fetch(apiUrl, {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{
              bug_id: bugId,
              status: newStatus,
              severity: newSeverity,
              assignee: newAssignee,
              ui_path: newUiPath,
              analysis_notes: newAnalysis
          }})
      }}).then(async res => {{
          if (!res.ok) {{
              throw new Error(`HTTP ${{res.status}} 响应异常`);
          }}
          return res.json();
      }}).then(data => {{
          if (data.success) {{
              b.status = newStatus;
              b.severity = newSeverity;
              b.assignee = newAssignee;
              b.ui_path = newUiPath;
              b.analysis_notes = newAnalysis;

              // 退出编辑模式并重新渲染大盘
              showBugModal(bugId);
              renderBugs();
          }} else {{
              alert('保存失败: ' + (data.error || '未知错误'));
          }}
      }}).catch(err => {{
          alert('保存失败: ' + (err.message || err) + '\\n\\n请确认同主机的 8080 Python 服务已启动: python utils/report_hub.py --serve');
      }});
    }}

    document.addEventListener('keydown', (e) => {{
      if (e.key === 'Escape') {{
        document.getElementById('bugModalOverlay').style.display = 'none';
        document.getElementById('imageViewerOverlay').style.display = 'none';
      }}
    }});

    function escapeHtml(str) {{
      if (!str) return '';
      return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
    }}

    function showImageFullscreen(src, event) {{
        if(event) event.stopPropagation();
        document.getElementById('imageViewerImg').src = src;
        document.getElementById('imageViewerOverlay').style.display = 'flex';
    }}

    function changeBugStatus(bugId, selectEl) {{
        const newStatus = selectEl.value;
        let apiBase = '';
        if (location.protocol === 'file:') {{
            apiBase = 'http://localhost:8080';
        }} else if (location.port !== '8080') {{
            // 兼容 IIS (80端口) 或其他反向代理：自动定向到同台主机的 8080 Python 服务
            apiBase = `${{location.protocol}}//${{location.hostname}}:8080`;
        }}
        const apiUrl = `${{apiBase}}/api/update_bug_status`;
        
        fetch(apiUrl, {{
            method: 'POST',
            headers: {{ 'Content-Type': 'application/json' }},
            body: JSON.stringify({{ bug_id: bugId, status: newStatus }})
        }}).then(async res => {{
            if (!res.ok) {{
                throw new Error(`HTTP ${{res.status}} 响应异常`);
            }}
            return res.json();
        }}).then(data => {{
            if (data.success) {{
                const bug = allBugs.find(b => b.id === bugId);
                if(bug) bug.status = newStatus;
                
                selectEl.style.borderColor = '#10b981';
                setTimeout(() => {{
                    renderBugs(); // re-render to update color
                }}, 500);
            }} else {{
                alert('更新失败: ' + (data.error || '未知错误'));
            }}
        }}).catch(err => {{
            alert('更新状态失败: ' + (err.message || err) + '\\n\\n请确认同主机的 8080 Python 服务已启动: python utils/report_hub.py --serve');
        }});
    }}

    document.addEventListener('DOMContentLoaded', () => {{
      renderRuns();
      renderBugs();
    }});
  </script>
</body>
</html>
"""
        out_file.write_text(html_content, encoding="utf-8")
        logger.info(f"🎉 统一巡检门户大盘已生成: {out_file}")
        
        # 同时生成一份独立的 runs_data.js 供各个子报告的左侧边栏使用（轻量化数据源）
        js_content = f"window.GLOBAL_RUNS_LIST = {runs_json};\n"
        js_file = self.runs_dir / "runs_data.js"
        js_file.write_text(js_content, encoding="utf-8")
        logger.info(f"✅ 生成全局数据源: {js_file}")
        
        return out_file

    def serve(self, port: int = 8080):
        """启动轻量本地/局域网 Web 门户服务"""
        import http.server
        import socketserver
        import json
        from pathlib import Path

        self.build_index_html()
        os.chdir(self.runs_dir)

        hub_instance = self

        class APIHandler(http.server.SimpleHTTPRequestHandler):
            def end_headers(self):
                self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                self.send_header('Pragma', 'no-cache')
                self.send_header('Expires', '0')
                super().end_headers()

            def do_OPTIONS(self):
                self.send_response(200)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Access-Control-Allow-Methods', 'POST, GET, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', 'Content-Type')
                self.end_headers()

            def do_POST(self):
                if self.path in ("/api/update_bug_status", "/api/update_bug_detail"):
                    try:
                        content_length = int(self.headers.get('Content-Length', 0))
                        post_data = self.rfile.read(content_length)
                        raw_str = post_data.decode('utf-8', errors='ignore')
                        data = json.loads(raw_str, strict=False)
                        
                        bug_id = data.get('bug_id')
                        if not bug_id:
                            raise ValueError("缺少必要的 bug_id 参数")

                        new_status = data.get('status')
                        new_severity = normalize_severity(data.get('severity')) if "severity" in data else None
                        new_assignee = data.get('assignee')
                        new_ui_path = data.get('ui_path')
                        new_analysis = data.get('analysis_notes')

                        success = False
                        updated_targets = []

                        def update_bug_dict(b_dict: dict):
                            if new_status:
                                b_dict['status'] = new_status
                            if new_severity is not None:
                                b_dict['severity'] = new_severity
                            if new_assignee is not None:
                                b_dict['assignee'] = new_assignee
                            if new_ui_path is not None:
                                b_dict['ui_path'] = new_ui_path
                            if new_analysis is not None:
                                b_dict['analysis_notes'] = new_analysis

                        # 1. 在全局缺陷知识库 (artifacts/bugs/global_bugs*.json) 中查找并更新
                        if GLOBAL_BUGS_DIR.exists():
                            for bug_file in GLOBAL_BUGS_DIR.glob("global_bugs*.json"):
                                try:
                                    with open(bug_file, 'r', encoding='utf-8') as f:
                                        bugs = json.load(f)
                                    file_changed = False
                                    for b in bugs:
                                        if b.get('id') == bug_id:
                                            update_bug_dict(b)
                                            success = True
                                            file_changed = True
                                            updated_targets.append(bug_file.name)
                                            break
                                    if file_changed:
                                        with open(bug_file, 'w', encoding='utf-8') as f:
                                            json.dump(bugs, f, ensure_ascii=False, indent=2)
                                except Exception as ge:
                                    logger.warning(f"更新 {bug_file.name} 异常: {ge}")

                        # 2. 在各个单次运行目录 (reports/runs/<app>/<run_id>/bugs/<bug_id>.json) 中查找并更新
                        for run_dir in get_all_run_folders():
                            run_bug_file = run_dir / "bugs" / f"{bug_id}.json"
                            if run_bug_file.exists():
                                try:
                                    with open(run_bug_file, 'r', encoding='utf-8') as rf:
                                        b_data = json.load(rf)
                                    update_bug_dict(b_data)
                                    with open(run_bug_file, 'w', encoding='utf-8') as rf:
                                        json.dump(b_data, rf, ensure_ascii=False, indent=2)
                                    success = True
                                    updated_targets.append(f"{run_dir.name}/bugs/{bug_id}.json")
                                except Exception as re_err:
                                    logger.warning(f"更新运行目录 Bug 文件异常 ({run_bug_file}): {re_err}")

                        if success:
                            # 同步重构静态大盘与 runs_data.js，保持数据双向实时一致
                            try:
                                hub_instance.build_index_html()
                            except Exception as be:
                                logger.warning(f"Rebuilding index.html after bug update warning: {be}")
                            resp_data = {"success": True, "bug_id": bug_id, "updated": updated_targets}
                        else:
                            resp_data = {"success": False, "bug_id": bug_id, "error": f"在全局库及各运行目录中均未找到编号为 '{bug_id}' 的缺陷记录"}

                        resp_bytes = json.dumps(resp_data, ensure_ascii=False).encode('utf-8')
                        self.send_response(200)
                        self.send_header('Content-Type', 'application/json; charset=utf-8')
                        self.send_header('Content-Length', str(len(resp_bytes)))
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(resp_bytes)
                    except Exception as err:
                        err_bytes = json.dumps({"success": False, "error": str(err)}, ensure_ascii=False).encode('utf-8')
                        self.send_response(500)
                        self.send_header('Content-Type', 'application/json; charset=utf-8')
                        self.send_header('Content-Length', str(len(err_bytes)))
                        self.send_header('Access-Control-Allow-Origin', '*')
                        self.end_headers()
                        self.wfile.write(err_bytes)
                else:
                    self.send_error(404, "Not Found")

        Handler = APIHandler
        # 支持端口复用
        socketserver.TCPServer.allow_reuse_address = True

        with socketserver.TCPServer(("", port), Handler) as httpd:
            print("\n" + "=" * 65)
            print(f"🚀 Electron Vision AI 全量巡检大盘门户已启动！")
            print(f"👉 本地访问地址: http://localhost:{port}/")
            print(f"👉 局域网访问:   http://0.0.0.0:{port}/ (或使用你的内网 IP)")
            print(f"📁 根目录指向:   {self.runs_dir}")
            print("=" * 65 + "\n")
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                print("\n🛑 服务已停止。")

    def refresh_all_reports(self) -> int:
        """强制重新生成所有子运行目录中的 report.html，并更新统一大盘"""
        from utils.report_generator import ReportGenerator

        subdirs = sorted([d for d in self.runs_dir.iterdir() if d.is_dir() and not d.name.startswith((".", "__"))], key=lambda p: p.stat().st_mtime, reverse=True)
        count = 0
        logger.info(f"🔄 开始强制全量刷新 {len(subdirs)} 个运行目录的 report.html...")
        for idx, d in enumerate(subdirs, 1):
            try:
                gen = ReportGenerator(d)
                gen.generate_html()
                count += 1
                logger.info(f"[{idx}/{len(subdirs)}] ✅ 成功刷新: {d.name}/report.html")
            except Exception as e:
                logger.error(f"[{idx}/{len(subdirs)}] ❌ 刷新 {d.name} 失败: {e}")
        
        self.build_index_html()
        logger.info(f"🎉 全部 {count} 份独立报告及统一巡检门户已全量刷新完成！")
        return count


def main():
    parser = argparse.ArgumentParser(description="Electron Vision AI 统一巡检门户引擎")
    parser.add_argument("--build", action="store_true", help="仅重新生成 reports/runs/index.html")
    parser.add_argument("--refresh-all", action="store_true", help="强制重新生成所有子运行目录下的 report.html 并更新大盘")
    parser.add_argument("--serve", action="store_true", help="启动常驻 Web 服务")
    parser.add_argument("--port", type=int, default=8080, help="Web 服务端口 (默认 8080)")
    args = parser.parse_args()

    hub = ReportHub()

    if args.refresh_all:
        hub.refresh_all_reports()
    elif args.serve:
        hub.serve(port=args.port)
    else:
        out = hub.build_index_html()
        print(f"✅ 门户已生成：file:///{out.as_posix()}\n如果需要在线浏览，请运行: python utils/report_hub.py --serve --port {args.port}")


if __name__ == "__main__":
    main()
