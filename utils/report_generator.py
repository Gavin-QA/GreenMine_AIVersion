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

from utils.paths import RUNS_DIR, find_run_dir, get_all_run_folders
from utils.bug_enricher import enrich_bug_metadata

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

        # 2. 解析缺陷库 bugs/ 并关联对应执行树步骤
        bug_json_to_step = {}
        for s in data["steps"]:
            if s.get("bug_card_id"):
                bug_json_to_step[f"{s['bug_card_id']}.json"] = s["step"]

        # 读取全局缺陷库 global_bugs.json 用于补充复现次数、最后出现、归因分析等元数据
        global_bugs_map = {}
        bugs_base = Path(__file__).resolve().parent.parent / "artifacts" / "bugs"
        active_app = None
        for p in self.run_dir.parts:
            if p in ["zhaiwan", "tianrui", "liwutong"]:
                active_app = p
                break
        if not active_app:
            from config.settings import settings
            active_app = getattr(settings, "active_app", "default")
        global_bugs_path = bugs_base / f"global_bugs_{active_app}.json"
        if global_bugs_path.exists():
            try:
                with open(global_bugs_path, "r", encoding="utf-8") as f:
                    gb_list = json.load(f)
                    if isinstance(gb_list, list):
                        for gb in gb_list:
                            if "id" in gb:
                                global_bugs_map[gb["id"]] = gb
            except Exception as e:
                logger.debug(f"加载应用缺陷库 {global_bugs_path.name} 失败: {e}")

        # DB-First 自愈兜底：若本地文件丢失，从数据库提取全量缺陷字典并自动恢复
        if not global_bugs_map:
            try:
                from utils.bug_db_sync import get_bugs_from_db, restore_global_bugs_file
                db_all_bugs = get_bugs_from_db(app_name=active_app)
                for gb in db_all_bugs:
                    if "id" in gb:
                        global_bugs_map[gb["id"]] = gb
                if not global_bugs_path.exists() and db_all_bugs:
                    restore_global_bugs_file(active_app)
            except Exception as dbe:
                logger.debug(f"从数据库补全全局缺陷大盘跳过: {dbe}")

        shots_dir = self.run_dir / "screenshots"
        bugs_dir = self.run_dir / "bugs"
        raw_bugs_list = []

        # DB-First 自愈兜底：若本地 bugs 目录不存在或无 JSON 文件，自动从数据库恢复
        if not bugs_dir.exists() or not list(bugs_dir.glob("*.json")):
            try:
                from utils.bug_db_sync import restore_run_bugs
                restore_run_bugs(self.run_id, app_name=active_app)
            except Exception as re_err:
                logger.debug(f"自愈批次 Bug 文件跳过: {re_err}")

        if bugs_dir.exists():
            for bug_json in sorted(bugs_dir.glob("*.json")):
                try:
                    with open(bug_json, "r", encoding="utf-8") as f:
                        b_info = json.load(f)

                    # 匹配截图相对路径
                    bug_id = b_info.get("id", bug_json.stem)
                    img_cand = bugs_dir / f"{bug_json.stem}.png"
                    if not img_cand.exists():
                        img_cand = bugs_dir / f"{bug_id}.png"
                    if not img_cand.exists():
                        img_cands = list(bugs_dir.glob(f"{bug_id}*.png"))
                        if img_cands:
                            img_cand = img_cands[0]

                    b_info["rel_screenshot"] = f"bugs/{img_cand.name}" if img_cand.exists() else None
                    b_info["card_id"] = bug_json.stem
                    b_info.setdefault("run_id", data["run_id"])
                    b_info.setdefault("date", b_info.get("creation_date", data.get("start_time", "").split(" ")[0] if data.get("start_time") else ""))

                    # 关联执行树步骤与执行前截图
                    matched_step = bug_json_to_step.get(bug_json.name)
                    if not matched_step:
                        matched_step = bug_json_to_step.get(f"{b_info['card_id']}.json")
                    if matched_step:
                        b_info["step_num"] = matched_step
                        before_file = f"explore_step_{matched_step}.png"
                        if (shots_dir / before_file).exists():
                            b_info["before_screenshot"] = f"screenshots/{before_file}"

                    # 注入全局缺陷库权威元数据 (status, occurrences, last_seen, assignee, tags, analysis_notes, etc.)
                    if bug_id in global_bugs_map:
                        gb = global_bugs_map[bug_id]
                        for k in ["occurrences", "last_seen", "status", "severity", "action_type", "ui_path", "target_element", "assignee", "tags", "analysis_notes", "remark", "date", "zentao_id"]:
                            if k in gb:
                                if k in ["status", "severity", "assignee", "tags", "analysis_notes", "remark", "occurrences", "last_seen", "zentao_id"] or k not in b_info or not b_info[k] or b_info[k] == "Medium":
                                    b_info[k] = gb[k]

                    # 智能元数据增强：单一源头统一推导缺失的 action_type, target_element, ui_path, tags
                    enrich_bug_metadata(b_info, shots_dir=shots_dir, matched_step=matched_step)

                    raw_bugs_list.append(b_info)
                except Exception as e:
                    logger.warning(f"读取 Bug 文件 {bug_json.name} 失败: {e}")

        # 智能同类缺陷聚合折叠：按 bug_id 聚合，保留全部复现轨迹与现场
        from collections import OrderedDict
        grouped_bugs = OrderedDict()
        for b in raw_bugs_list:
            b_id = b.get("id") or b.get("card_id") or "BUG"
            if b_id not in grouped_bugs:
                # 以主编号文件（非带时间戳的）或第一个条目为主卡片
                main_bug = dict(b)
                main_bug["recurrences"] = []
                grouped_bugs[b_id] = main_bug
            elif b.get("card_id") == b_id:
                # 遇到原生主单据，补全主信息
                for k, v in b.items():
                    if v and not grouped_bugs[b_id].get(k):
                        grouped_bugs[b_id][k] = v

            details = b.get("details") if isinstance(b.get("details"), dict) else {}
            rec_item = {
                "card_id": b.get("card_id", b_id),
                "step_num": b.get("step_num"),
                "step": details.get("step") or b.get("step", ""),
                "actual": details.get("actual") or b.get("actual", ""),
                "target_element": b.get("target_element", ""),
                "ui_path": b.get("ui_path", ""),
                "rel_screenshot": b.get("rel_screenshot"),
                "before_screenshot": b.get("before_screenshot"),
                "date": b.get("creation_date") or b.get("date", "")
            }
            grouped_bugs[b_id]["recurrences"].append(rec_item)

        for b_id, main_bug in grouped_bugs.items():
            main_bug["run_occurrences_count"] = len(main_bug["recurrences"])
            # 如果主卡片自身缺失截图或步骤，用第一个有效复现条目补充
            if not main_bug.get("rel_screenshot"):
                for r in main_bug["recurrences"]:
                    if r.get("rel_screenshot"):
                        main_bug["rel_screenshot"] = r["rel_screenshot"]
                        break
            data["bugs"].append(main_bug)

        data["kpi"]["bugs_count"] = len(data["bugs"])
        data["kpi"]["total_bug_hits"] = len(raw_bugs_list)

        # 统计缺陷各状态分布 (激活 / 误报 / 已提单 / 已关闭 / 已解决)
        status_counts = {"激活": 0, "已提单": 0, "误报": 0, "已关闭": 0, "已解决": 0}
        for b in data["bugs"]:
            st = b.get("status") or "激活"
            if st == "Open":
                st = "激活"
            status_counts[st] = status_counts.get(st, 0) + 1
        data["kpi"]["bug_status_counts"] = status_counts
        data["kpi"]["active_bugs_count"] = status_counts.get("激活", 0)

        # 3. 解析页面拓扑树 (checkpoint/page_tree.json 或根目录 page_tree.json 或全局拓扑单一真理源)
        tree_cand = self.run_dir / "checkpoint" / "page_tree.json"
        if not tree_cand.exists():
            tree_cand = self.run_dir / "page_tree.json"
        if not tree_cand.exists():
            from utils.paths import TOPOLOGY_DIR
            tree_cand = TOPOLOGY_DIR / f"global_page_tree_{active_app}.json"
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
                    data["generated_yaml_filename"] = y_file.name
                    # 统计 steps
                    step_matches = re.findall(r'-\s+type:\s+', content)
                    data["kpi"]["yaml_steps_count"] = len(step_matches)
                    break
                except Exception as e:
                    logger.warning(f"读取生成的用例失败: {e}")

        # 5. 解析接口大盘与业务页面覆盖度
        api_file = self.run_dir / "screenshots" / "api_registry.json"
        if not api_file.exists():
            api_file = self.run_dir / "api_registry.json"
        raw_scopes = set()
        if api_file.exists():
            try:
                with open(api_file, "r", encoding="utf-8") as f:
                    api_data = json.load(f)
                data["api_summary"] = api_data
                summary_meta = api_data.get("summary", {})
                if "total_unique_endpoints" in summary_meta:
                    data["kpi"]["apis_count"] = summary_meta["total_unique_endpoints"]
                elif "global_flat_apis" in api_data:
                    data["kpi"]["apis_count"] = len(api_data["global_flat_apis"])
                else:
                    data["kpi"]["apis_count"] = len([k for k in api_data.keys() if k not in ["summary", "page_scopes"]])
                raw_scopes.update(api_data.get("page_scopes", {}).keys())
            except Exception as e:
                logger.warning(f"读取 api_registry 失败: {e}")

        # 结合 steps 中的 ui_path 补充页面触达记录
        for s in data["steps"]:
            p = s.get("ui_path")
            if p and p not in ["YAML 用例脚本", "无"]:
                raw_scopes.add(p)

        # 执行权威基准归一化 (以 docs/explore_rules.md 实时解析为真值 SSOT)
        try:
            from core.explorer_agent.page_map_builder import PageMapBuilder
            norm_result = PageMapBuilder.normalize_page_scopes(raw_scopes)
            data["kpi"]["page_scopes_count"] = norm_result["visited_canonical_count"]
            data["kpi"]["total_menus_count"] = norm_result["total_canonical_menus"]
            data["kpi"]["sub_components_count"] = norm_result["sub_components_count"]
            data["kpi"]["page_coverage_rate"] = norm_result["coverage_rate"]
            data["visited_menus"] = norm_result["visited_canonical_menus"]
        except Exception as e:
            logger.warning(f"页面作用域归一化失败: {e}")
            data["kpi"]["page_scopes_count"] = len(raw_scopes)
            data["kpi"]["total_menus_count"] = len(raw_scopes) if len(raw_scopes) > 0 else 1
            data["kpi"]["page_coverage_rate"] = 0.0

        # 加载 Launcher 客户端环境快照 (env_info.json)
        env_file = self.run_dir / "env_info.json"
        if env_file.exists():
            try:
                data["env_info"] = json.loads(env_file.read_text(encoding="utf-8"))
            except Exception:
                data["env_info"] = {}
        else:
            data["env_info"] = {}

        return data

    def _parse_log_file(self, log_path: Path, data: Dict[str, Any]):
        """高精度分块提取 1000 步的 Worker 动作、思维链与截图关联"""
        try:
            text = log_path.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            logger.error(f"读取日志文件失败: {e}")
            return

        # 首先尝试提取逻辑层明确打印的执行统计 (新版逻辑)
        stats_match = re.search(r"⏳ 任务执行统计 \| 起始时间: (.*?) \| 结束时间: (.*?) \| 实际耗时: (.*?)(?=\s*\||\n|\Z)", text)
        if stats_match:
            data["start_time"] = stats_match.group(1).strip()
            data["end_time"] = stats_match.group(2).strip()
            data["duration"] = stats_match.group(3).strip()
        else:
            # 兼容老版本报告的兜底逻辑
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

        # 宏观目标提取 (高兼容性容错匹配)
        macro_match = re.search(r"🚀\s*(?:\[ExplorerAgent\])?\s*启动自主探索[，,]\s*目标[:：]\s*['\"]?(.*?)['\"]?(?:[，,]\s*最大步数|\n|\Z)", text)
        if not macro_match:
            macro_match = re.search(r"🚀 开启自主探索模式 \| 目标:\s*['\"]?(.*?)['\"]?(?=\n|\Z)", text)
        if not macro_match:
            macro_match = re.search(r"🕵️‍♂️ \[Planner\] 思考宏观目标:\s*['\"]?(.*?)['\"]?(?=\n|\Z)", text)
        if not macro_match:
            macro_match = re.search(r"探题目[:：]\s*(.*?)(?=\n|\Z)", text)
        if not macro_match:
            macro_match = re.search(r"▶️ 开始执行巡检用例:\s*(.*?)(?=\n|\Z)", text)

        if macro_match:
            data["macro_objective"] = macro_match.group(1).strip().strip("'\"")
        else:
            smoke_match = re.search(r"🚀 启动【(.*?)全量冒烟巡检模式】", text)
            if smoke_match:
                data["macro_objective"] = "全量二级业务菜单冒烟巡检"

        # 统计 Planner 次数
        data["kpi"]["planner_phases"] = len(re.findall(r"🧠 \[Planner Phase(?:\s+\d+)?\]", text))

        # 提取 Planner 和 Worker 单步
        shots_dir = self.run_dir / "screenshots"

        # 按 Planner Phase 切分
        planner_blocks = re.split(r"🧠 \[Planner Phase(?:\s+\d+)?\] 开始(?:宏观)?规划", text)
        if len(planner_blocks) > 1:
            for p_idx, p_block in enumerate(planner_blocks[1:]):
                planner_phase_num = p_idx + 1

                # 解析 Planner 信息
                ts_m = re.search(r"^，当前.*?进度.*?\n(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", p_block) or re.search(r"\n(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", p_block)
                ts = ts_m.group(1) if ts_m else ""

                prog_m = re.search(r"^，当前(?:总步数)?进度[：:]\s*(.*?)(?=\n)", p_block)
                global_prog = prog_m.group(1).strip() if prog_m else ""

                plan_shot_m = re.search(r"截图已保存至: .*?screenshots[\\/](plan_step_\d+\.png)", p_block)
                plan_shot_path = f"screenshots/{plan_shot_m.group(1)}" if plan_shot_m else None

                th_m = re.search(r"💡 \[Planner\] 思考链: (.*?)(?=\n\d{4}|\n💡|\Z)", p_block, re.DOTALL)
                thought = th_m.group(1).strip() if th_m else ""

                target_m = re.search(r"🎯 \[Planner\] 下达新任务: ['\"](.*?)['\"]", p_block)
                if not target_m:
                    target_m = re.search(r"🎯 最终状态: (.*?)(?=\n|\Z)", p_block)
                target = target_m.group(1).strip() if target_m else "未解析到明确目标"

                budget_m = re.search(r"预算步数[:：]\s*(\d+)", p_block)
                budget = int(budget_m.group(1)) if budget_m else 0

                data["steps"].append({
                    "type": "planner",
                    "step": planner_phase_num,
                    "timestamp": ts,
                    "global_prog": global_prog,
                    "budget": budget,
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
                    act_m = re.search(r"🤖 \[Worker\] 决定: \[(\w+)\](?: -> 目标: (.*?))?(?=\n|\Z)", block)
                    if act_m:
                        w_action = act_m.group(1).upper()
                        w_target = (act_m.group(2) or "").strip()
                    elif "判定当前子任务已圆满达成" in block or "交还控制权给 Planner" in block:
                        w_action = "FINISH"
                        w_target = "子任务达成"
                    elif "wait 操作" in block.lower() or "执行 wait" in block or "等待页面" in block:
                        w_action = "WAIT"
                        w_target = "等待页面响应"
                    elif "hover" in block.lower():
                        w_action = "HOVER"
                        w_target = ""
                    elif "click" in block.lower():
                        w_action = "CLICK"
                        w_target = ""
                    else:
                        w_action = "FINISH"
                        w_target = "完成"
                    path_m = re.search(r"📍 \[Worker\] 当前推断路径: (\[.*?\])", block)
                    ui_path = path_m.group(1) if path_m else "[]"
                    has_bug = "🚨 [" in block
                    bug_report_m = re.search(r"缺陷报告固化完毕:.*?bugs[\\/](.*?\.json)", block)
                    bug_card_id = Path(bug_report_m.group(1)).stem if bug_report_m else None

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
                        "bug_card_id": bug_card_id,
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

        if len(data["steps"]) == 0:
            # 尝试提取 Smoke 单步
            smoke_pattern = re.compile(
                r"🎯 \[Smoke Tour \((\d+)/\d+\)\] 正在巡检模块: 【(.*?)】\n"
                r"(.*?)(?=(?:🎯 \[Smoke Tour |\Z))",
                re.DOTALL
            )
            for m in smoke_pattern.finditer(text):
                step_num = int(m.group(1))
                module_name = m.group(2)
                block = m.group(3)

                has_bug = "❌ [Smoke Jump]" in block or "🐞 捕获到缺陷异常" in block or "⚠️ [Smoke Planner]" in block

                sub = f"冒烟巡检: {module_name}"

                th_m = re.search(r"💡 \[Smoke Planner\] 页面诊断与思考: (.*?)(?=\n)", block)
                thought = th_m.group(1).strip() if th_m else "尚未完成规划或遭遇跳转失败"

                shot_path = None
                hover_path = None

                if shots_dir.exists():
                    jump_imgs = list(shots_dir.glob(f"smoke_jump_{step_num}_click.png"))
                    if not jump_imgs:
                        jump_imgs = list(shots_dir.glob(f"smoke_jump_{step_num}_hover.png"))
                    if jump_imgs:
                        shot_path = f"screenshots/{jump_imgs[0].name}"

                    plan_imgs = list(shots_dir.glob(f"smoke_page_{step_num}_plan.png"))
                    if plan_imgs:
                        hover_path = f"screenshots/{plan_imgs[0].name}"

                # 寻找时间戳
                ts_m = re.search(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", block)
                ts = ts_m.group(1) if ts_m else ""

                data["steps"].append({
                    "step": step_num,
                    "worker_step": step_num,
                    "budget": 0,
                    "timestamp": ts,
                    "sub_objective": sub,
                    "thought": thought,
                    "action": "SMOKE_TOUR",
                    "target": module_name,
                    "ui_path": module_name,
                    "element_type": "",
                    "container": "",
                    "has_bug": has_bug,
                    "screenshot": shot_path,
                    "hover_screenshot": hover_path,
                    "after_screenshot": None,
                })


        data["kpi"]["total_steps"] = len(data["steps"])

    def generate_html(self, output_path: Optional[Path | str] = None, disable_push: bool = False, update_hub: bool = True) -> Path:
        """组装并导出美观的前端独立交互式报告"""
        data = self.parse_run_data()
        out = Path(output_path).resolve() if output_path else (self.run_dir / "report.html")

        # 序列化供前端 JS 消费的纯数据
        steps_json = json.dumps(data["steps"], ensure_ascii=False)
        bugs_json = json.dumps(data["bugs"], ensure_ascii=False)
        # 接口数据瘦身：表格中已通过 api_rows_html 预渲染展示端点名称；
        # 避免将几十兆包含 Base64 各种大图的原始响应报文注入 HTML，下载直接走静态文件
        apis_json = "{}"
        mermaid_raw = data["mermaid_str"]

        # 计算当前 report 相对于 reports/runs 根目录的深度与相对前缀 (自适应 1 层或 2 层架构)
        try:
            rel_parts = self.run_dir.resolve().relative_to(RUNS_DIR.resolve()).parts
            depth = len(rel_parts)
            hub_root_rel = "../" * depth if depth > 0 else "./"
        except Exception:
            hub_root_rel = "../../" if "/" in str(self.run_dir).replace("\\", "/") else "../"

        # 缺陷卡片改为前端 JS 基于 allBugs 动态分页渲染，支持双图对比与双向跳转定位

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
        hero_title = "⚡ Electron Vision AI · 自动化回归测试报告" if is_yaml_mode else "⚡ Electron Vision AI · 自主探索测试报告"
        badge_text = "YAML 强校验模式" if is_yaml_mode else "自主探索驱动"

        planner_kpi_style_attr = 'style="display:none;"' if is_yaml_mode else ''
        pass_rate_kpi_style_attr = '' if is_yaml_mode else 'style="display:none;"'

        pass_count = data['kpi']['total_steps'] - data['kpi']['bugs_count']
        pass_rate = f"{int(pass_count / data['kpi']['total_steps'] * 100)}%" if data['kpi']['total_steps'] > 0 else "100%"

        tab_topology_style = "display:none;" if is_yaml_mode else ""
        tab_yaml_style = "display:none;" if is_yaml_mode else ""
        hero_meta_style = 'style="display:none;"' if is_yaml_mode else ''
        timeline_tab_name = "🎬 用例执行链路" if is_yaml_mode else "🎬 Planner-Worker 执行树"

        # 安全处理时间字符串
        start_t = data.get('start_time', '未知')
        end_t = data.get('end_time', '未知')
        if " " in start_t and " " in end_t:
            start_date, start_hour = start_t.split(" ", 1)
            _, end_hour = end_t.split(" ", 1)
            time_display_html = f"{start_hour} - {end_hour} <span style='color:var(--text-dim);font-weight:normal;font-size:12px;margin-left:4px;'>({start_date})</span>"
        else:
            time_display_html = f"{start_t} - {end_t}"

        # 客户端环境信息挂件
        env_info = data.get("env_info", {})
        if env_info and env_info.get("env_name"):
            env_name = env_info.get("env_name", "未知环境")
            env_color = "#34d399" if env_info.get("env_key") == "prod" else "#38bdf8"
            env_dist = env_info.get("big_screen_dist", "")
            dist_tag = f" <span style='color:var(--text-dim);font-size:11px;font-weight:normal;'>({Path(env_dist).name})</span>" if env_dist else ""
            tooltip_txt = f"后端: {env_info.get('nplusone_url', '')} | 前端: {env_dist} | UE: {env_info.get('ue_dist', '')}"
            env_pill_html = f"""
            <div class="run-id-pill" title="{html.escape(tooltip_txt)}" style="cursor:help;">
              <span>🌐 被测环境:</span> <strong style="color: {env_color};">{html.escape(env_name)}</strong>{dist_tag}
            </div>"""
        else:
            env_pill_html = ""
        # ==========================

        from jinja2 import Environment, FileSystemLoader
        web_tpl_dir = PROJECT_ROOT / "web" / "templates"
        templates_dir = web_tpl_dir if web_tpl_dir.exists() else Path(__file__).parent / "templates"
        jinja_env = Environment(loader=FileSystemLoader(str(templates_dir)), autoescape=False)
        template = jinja_env.get_template("report.html")

        macro_objective_escaped = html.escape(data.get("macro_objective", ""))
        generated_yaml_str = data.get("generated_yaml", "") or "# 暂无自动生成的用例"
        generated_yaml_escaped = html.escape(generated_yaml_str)
        generated_yaml_json = json.dumps(data.get("generated_yaml", ""))
        mermaid_escaped = html.escape(mermaid_raw) if mermaid_raw else "未检测到拓扑数据"
        page_coverage_rate_str = f"{data['kpi'].get('page_coverage_rate', 0):.1f}"

        html_content = template.render(
            data=data,
            steps_json=steps_json,
            bugs_json=bugs_json,
            apis_json=apis_json,
            hub_root_rel=hub_root_rel,
            api_rows_html=api_rows_html,
            hero_title=hero_title,
            badge_text=badge_text,
            planner_kpi_style_attr=planner_kpi_style_attr,
            pass_rate_kpi_style_attr=pass_rate_kpi_style_attr,
            pass_rate=pass_rate,
            tab_topology_style=tab_topology_style,
            tab_yaml_style=tab_yaml_style,
            hero_meta_style=hero_meta_style,
            timeline_tab_name=timeline_tab_name,
            time_display_html=time_display_html,
            env_pill_html=env_pill_html,
            macro_objective_escaped=macro_objective_escaped,
            generated_yaml_escaped=generated_yaml_escaped,
            generated_yaml_json=generated_yaml_json,
            mermaid_escaped=mermaid_escaped,
            page_coverage_rate_str=page_coverage_rate_str,
        )
        out.write_text(html_content, encoding="utf-8")
        logger.info(f"🎉 高颜值离线交互式报告已生成: {out}")

        # 自动同步刷新全局门户首页 reports/runs/index.html
        if update_hub:
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
                            "content": f"**🏷️ Run ID:** {data.get('run_id')}\n**🎯 宏观目标:** {data.get('macro_objective')}\n\n**📉 预期步数:** {data['kpi'].get('max_steps', '-')} | **预期耗时:** {data['kpi'].get('max_time', '-')}\n**🧠 规划决策:** {data['kpi'].get('planner_phases', 0)} 轮 | **📈 实际执行:** {data['kpi'].get('total_steps')} 步 | **实际耗时:** {data.get('duration')}\n\n**🐞 捕获严重缺陷:** {bugs_count} 个\n**🗺️ 触达二级页面:** {data['kpi'].get('page_scopes_count', 0)}/{data['kpi'].get('total_menus_count', 33)} 个 (覆盖率 {data['kpi'].get('page_coverage_rate', 0):.1f}%)"
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
        target_dir = find_run_dir(args.run)
    elif args.latest:
        runs = get_all_run_folders()
        if runs:
            target_dir = runs[0]

    if not target_dir:
        print("💡 未显式指定运行目录，自动寻找最近一次的测试产物目录...")
        runs = [p for p in get_all_run_folders() if (p.name.startswith("explore_") or p.name.startswith("smoke_"))]
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
