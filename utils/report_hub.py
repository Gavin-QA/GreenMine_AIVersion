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
import threading
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
    "liwutong": "里伍铜矿山",
    "tianrui": "四川天瑞"
}


from utils.bug_enricher import extract_ui_path_from_step, normalize_severity, enrich_bug_metadata


class ReportHub:
    def __init__(self, runs_dir: Optional[Path | str] = None):
        self.runs_dir = Path(runs_dir).resolve() if runs_dir else RUNS_DIR.resolve()
        self._rebuild_timer: Optional[threading.Timer] = None
        self._rebuild_lock = threading.Lock()

    def trigger_async_rebuild(self, delay: float = 1.0):
        """异步防抖重构静态大盘与 runs_data.js，避免高频写入引起磁盘 I/O 拥堵"""
        with self._rebuild_lock:
            if self._rebuild_timer is not None:
                self._rebuild_timer.cancel()

            def _rebuild():
                try:
                    logger.info("🔄 [后台异步] 触发大盘数据静态重构...")
                    self.build_index_html()
                    logger.info("🎉 [后台异步] 大盘数据静态重构完成！")
                except Exception as be:
                    logger.warning(f"Background rebuilding index.html warning: {be}")

            self._rebuild_timer = threading.Timer(delay, _rebuild)
            self._rebuild_timer.daemon = True
            self._rebuild_timer.start()

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
            should_rebuild = not report_file.exists()
            if not should_rebuild:
                try:
                    rep_mtime = report_file.stat().st_mtime
                    # 检查该 run 目录下的 bugs/*.json 是否有更新
                    bugs_dir = d / "bugs"
                    if bugs_dir.exists():
                        for bf in bugs_dir.glob("*.json"):
                            if bf.stat().st_mtime > rep_mtime:
                                should_rebuild = True
                                break
                except Exception:
                    pass

            if should_rebuild:
                try:
                    generator.generate_html(disable_push=True, update_hub=False)
                except Exception as e:
                    logger.warning(f"为 {d.name} 渲染 report.html 失败: {e}")

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

        # 按执行时间倒序排列，优先采用最新批次的运行数据
        runs_data.sort(key=lambda x: x.get("mtime", 0), reverse=True)
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

        run_app_map = {r.get("run_id"): r.get("app", "zhaiwan") for r in runs if r.get("run_id")}

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

            b_app = run_app_map.get(r_id)
            if not b_app:
                if target_run_dir and "liwutong" in target_run_dir.parts:
                    b_app = "liwutong"
                else:
                    b_app = "zhaiwan"

            all_bugs_dict[b_id] = {
                "id": b_id,
                "title": gb.get("title", ""),
                "run_id": r_id,
                "app": b_app,
                "app_name": APP_NAME_MAP.get(b_app, "寨湾矿山"),
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
                "analysis_notes": raw_analysis,
                "remark": gb.get("remark", ""),
                "zentao_id": gb.get("zentao_id", "")
            }
            enrich_bug_metadata(all_bugs_dict[b_id])

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
                    # 严格校验当前批次截图真实存在性，并以原子元组方式更新，严禁跨批次状态污染
                    valid_rel_shot = rel_shot if (rel_shot and target_run_dir and (target_run_dir / rel_shot).exists()) else ""
                    valid_before_shot = before_shot if (before_shot and target_run_dir and (target_run_dir / before_shot).exists()) else ""

                    is_auth_run = (r_id == all_bugs_dict[b_id].get("run_id"))
                    curr_has_shots = bool(all_bugs_dict[b_id].get("rel_screenshot") or all_bugs_dict[b_id].get("before_screenshot"))
                    cand_has_shots = bool(valid_rel_shot or valid_before_shot)

                    # 决定是否采用当前批次作为现场呈现批次：
                    # 1) 是该 Bug 绑定的权威 run；或
                    # 2) 现存条目完全没有现场截图，而当前候选 run 拥有真实截图；或
                    # 3) 当前条目并非权威 run，且当前候选 run 拥有更完整的双快照
                    should_adopt_run = is_auth_run or (not curr_has_shots and cand_has_shots) or (valid_rel_shot and valid_before_shot and not all_bugs_dict[b_id].get("before_screenshot"))

                    if should_adopt_run:
                        all_bugs_dict[b_id]["rel_run_path"] = r_rel
                        all_bugs_dict[b_id]["report_link"] = r_link
                        all_bugs_dict[b_id]["rel_screenshot"] = valid_rel_shot
                        all_bugs_dict[b_id]["before_screenshot"] = valid_before_shot
                        if step_num is not None:
                            all_bugs_dict[b_id]["step_num"] = step_num

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
                    if not all_bugs_dict[b_id].get("zentao_id") and b.get("zentao_id"):
                        all_bugs_dict[b_id]["zentao_id"] = b.get("zentao_id")
                    if not all_bugs_dict[b_id].get("remark") and b.get("remark"):
                        all_bugs_dict[b_id]["remark"] = b.get("remark")
                    enrich_bug_metadata(all_bugs_dict[b_id])
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

                    b_app = r.get("app") or run_app_map.get(r_id, "zhaiwan")
                    all_bugs_dict[b_id] = {
                        "id": b_id,
                        "title": b.get("title", ""),
                        "app": b_app,
                        "app_name": APP_NAME_MAP.get(b_app, "寨湾矿山"),
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
                        "analysis_notes": run_analysis,
                        "remark": b.get("remark", ""),
                        "zentao_id": b.get("zentao_id", "")
                    }
                    enrich_bug_metadata(all_bugs_dict[b_id])

        # 3. 最终健全性巡检：严格核验所有 Bug 快照在其绑定的 rel_run_path 下真实存在，杜绝悬挂路径与 404
        for b_entry in all_bugs_dict.values():
            run_p = b_entry.get("rel_run_path") or b_entry.get("run_id", "")
            r_dir = find_run_dir(run_p)
            if r_dir:
                if b_entry.get("rel_screenshot") and not (r_dir / b_entry["rel_screenshot"]).exists():
                    b_entry["rel_screenshot"] = ""
                if b_entry.get("before_screenshot") and not (r_dir / b_entry["before_screenshot"]).exists():
                    b_entry["before_screenshot"] = ""
            else:
                b_entry["rel_screenshot"] = ""
                b_entry["before_screenshot"] = ""

        # 4. 生成 all_bugs 并修正总数
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

        # 计算项目维度全景指标
        zhaiwan_runs = sum(1 for r in summary_runs if r.get("app") == "zhaiwan")
        zhaiwan_steps = sum(r.get("kpi", {}).get("total_steps", 0) for r in summary_runs if r.get("app") == "zhaiwan")
        zhaiwan_bugs = sum(1 for b in all_bugs if b.get("app") == "zhaiwan")

        liwutong_runs = sum(1 for r in summary_runs if r.get("app") == "liwutong")
        liwutong_steps = sum(r.get("kpi", {}).get("total_steps", 0) for r in summary_runs if r.get("app") == "liwutong")
        liwutong_bugs = sum(1 for b in all_bugs if b.get("app") == "liwutong")

        runs_json = json.dumps(summary_runs, ensure_ascii=False)
        bugs_json = json.dumps(all_bugs, ensure_ascii=False)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        from jinja2 import Environment, FileSystemLoader
        web_tpl_dir = PROJECT_ROOT / "web" / "templates"
        templates_dir = web_tpl_dir if web_tpl_dir.exists() else Path(__file__).parent / "templates"
        jinja_env = Environment(loader=FileSystemLoader(str(templates_dir)), autoescape=False)
        template = jinja_env.get_template("hub.html")
        html_content = template.render(
            total_runs=total_runs,
            total_steps=total_steps,
            total_bugs=total_bugs,
            zhaiwan_runs=zhaiwan_runs,
            zhaiwan_steps=zhaiwan_steps,
            zhaiwan_bugs=zhaiwan_bugs,
            liwutong_runs=liwutong_runs,
            liwutong_steps=liwutong_steps,
            liwutong_bugs=liwutong_bugs,
            count_runs_explore=count_runs_explore,
            count_runs_smoke=count_runs_smoke,
            count_runs_yaml=count_runs_yaml,
            count_bugs_explore=count_bugs_explore,
            count_bugs_smoke=count_bugs_smoke,
            count_bugs_yaml=count_bugs_yaml,
            runs_json=runs_json,
            bugs_json=bugs_json,
            now_str=now_str,
        )
        out_file.write_text(html_content, encoding="utf-8")
        logger.info(f"🎉 统一巡检门户大盘已生成: {out_file}")

        # 同时生成一份独立的 runs_data.js 供各个子报告的左侧边栏使用（轻量化数据源）
        js_content = f"window.GLOBAL_RUNS_LIST = {runs_json};\n"
        js_file = self.runs_dir / "runs_data.js"
        js_file.write_text(js_content, encoding="utf-8")
        logger.info(f"✅ 生成全局数据源: {js_file}")

        return out_file

    def serve(self, port: int = 8000):
        """启动轻量本地/局域网 Web 门户服务 (统一端口 8000)"""
        import http.server
        import socketserver
        import json
        from pathlib import Path
        from utils.bug_updater import update_bug_record

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

                        # 使用统一缺陷更新核心引擎
                        resp_data = update_bug_record(data)

                        if resp_data.get("success"):
                            bug_id = data.get("bug_id")
                            # 自动刷新受影响运行目录的 report.html
                            for run_dir in get_all_run_folders():
                                run_bug_file = run_dir / "bugs" / f"{bug_id}.json"
                                if run_bug_file.exists():
                                    try:
                                        ReportGenerator(run_dir).generate_html(disable_push=True, update_hub=False)
                                    except Exception as ge:
                                        logger.warning(f"刷新 {run_dir.name}/report.html 异常: {ge}")

                            # 异步防抖重构静态大盘与 runs_data.js，立即返回 HTTP 响应，毫秒级响应
                            hub_instance.trigger_async_rebuild(delay=1.0)
                        else:
                            resp_data = {"success": False, "bug_id": data.get("bug_id"), "error": resp_data.get("error", "更新失败")}

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

        class ThreadedHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
            daemon_threads = True
            allow_reuse_address = True

        with ThreadedHTTPServer(("", port), Handler) as httpd:
            print("\n" + "=" * 65)
            print(f"🚀 Electron Vision AI 全量巡检大盘门户已启动 (多线程并发并发引擎)！")
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

        subdirs = get_all_run_folders()
        count = 0
        logger.info(f"🔄 开始强制全量刷新 {len(subdirs)} 个运行目录的 report.html...")
        for idx, d in enumerate(subdirs, 1):
            try:
                gen = ReportGenerator(d)
                gen.generate_html(disable_push=True, update_hub=False)
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
    parser.add_argument("--port", type=int, default=8000, help="Web 服务端口 (统一默认 8000)")
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
