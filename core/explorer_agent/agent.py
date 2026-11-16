"""
core/explorer_agent/agent.py —— 自主探索总司令部 (ExplorerAgent Orchestrator)
==============================================================================
职责：
1. 作为顶层调度中枢，协调 Planner 战略统帅 与 Worker 战术执行单兵；
2. 管理全局探索生命周期：检查点加载与持久化、执行超时监控、优雅收尾归档；
3. 驱动测试闭环：调用 TrajectoryExporter 导出确定性 YAML 用例，调用 ReportGenerator 生成全景大盘报告。
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.browser.driver import ElectronDriver
from core.bug_reporter import BugReporter
from core.vision.agent import VisionAgent
from utils.paths import (
    report_run_id,
    get_run_dir,
    get_run_screenshots_dir,
    get_run_checkpoint_dir,
    get_run_bugs_dir,
    get_run_generated_cases_dir,
    RUNS_DIR,
    find_run_dir,
)
from .page_map_builder import PageMapBuilder
from .trajectory_exporter import TrajectoryExporter
from .planner import ExplorerPlanner
from .worker import ExplorerWorker

logger = logging.getLogger("explorer_agent")


class ExplorerAgent:
    """自主探索总调度中枢"""

    def __init__(self, driver: ElectronDriver, vision: VisionAgent):
        self.driver = driver
        self.vision = vision
        self.bug_reporter = BugReporter(vision_agent=self.vision)
        self.run_id = report_run_id()

        # 工作目录划分
        self.run_dir = get_run_dir(self.run_id)
        self.log_dir = self.run_dir
        self.checkpoint_dir = get_run_checkpoint_dir(self.run_id)
        self.explore_dir = get_run_screenshots_dir(self.run_id)
        self.bugs_dir = get_run_bugs_dir(self.run_id)
        self.generated_cases_dir = get_run_generated_cases_dir(self.run_id)

        # 核心拓扑架构底座
        self.page_tree: Dict[str, Any] = PageMapBuilder.load_global_tree()
        self.failed_counts: Dict[str, int] = {}
        self.current_path: List[str] = ["首页"]

        # 状态机实时追踪
        self.container_stack: List[str] = []
        self.active_tab: Optional[str] = None
        self.is_panel_hidden: bool = False
        self.mailing_dialog_open: bool = False
        self.last_l2_route: Optional[Tuple[str, str]] = None

        # 实例化统帅与单兵
        self.planner = ExplorerPlanner(
            driver=self.driver,
            vision=self.vision,
            bug_reporter=self.bug_reporter,
            explore_dir=self.explore_dir,
            run_id=self.run_id
        )
        self.worker = ExplorerWorker(
            driver=self.driver,
            vision=self.vision,
            bug_reporter=self.bug_reporter,
            explore_dir=self.explore_dir,
            log_dir=self.log_dir,
            checkpoint_dir=self.checkpoint_dir,
            run_id=self.run_id
        )

    def explore(
        self,
        objective: str = "像黑客一样深度遍历大屏所有模块，寻找崩溃",
        max_steps: int = 50,
        max_time_mins: int = 15,
        resume_from: Optional[str] = None,
        context: str = "",
        reexplore_module: Optional[str] = None,
    ):
        """
        自主探索主循环：Planner 负责战略规划，Worker 负责战术单步执行。
        """
        logger.info(f"🚀 [ExplorerAgent] 启动自主探索，目标: '{objective}', 最大步数: {max_steps}, 超时: {max_time_mins} 分钟")

        global_history: List[str] = []
        steps_taken = 0
        planner_steps = 0
        trajectory: List[Dict[str, Any]] = []
        start_time = time.time()
        stuck_task_count = 0
        last_sub_objective = None

        # 恢复断点历史
        if resume_from:
            self._load_resume_state(resume_from, global_history)

        # 模块重探模式处理
        if reexplore_module:
            global_history = self._apply_reexplore_module(reexplore_module, global_history)

        # 探索启动前静默锚定初始内存水位基线 (强制 GC 剥离启动瞬态噪音)
        memory_leak_reported = False
        try:
            if hasattr(self.driver, "record_memory_snapshot"):
                self.driver.record_memory_snapshot(label="explore_start", set_as_baseline=True, trigger_gc=True)
        except Exception as e_mem_init:
            logger.debug(f"[MemoryProbe] 探索初始基线采集跳过: {e_mem_init}")

        # =====================================================================
        # 核心主循环：统帅规划 (Planner) -> 单兵执行 (Worker)
        # =====================================================================
        while steps_taken < max_steps:
            elapsed_mins = (time.time() - start_time) / 60.0
            if elapsed_mins >= max_time_mins:
                logger.info(f"\n⏳ 达到最大探索时间限制 ({max_time_mins} 分钟)，停止探索。")
                break

            # 1. 统帅规划阶段 (Planner Phase)
            planner_steps += 1
            plan_res = self.planner.plan_next_task(
                macro_objective=objective,
                global_history=global_history,
                context=context,
                page_tree=self.page_tree,
                reexplore_module=reexplore_module,
                container_stack=self.container_stack,
                is_panel_hidden=self.is_panel_hidden,
                mailing_dialog_open=self.mailing_dialog_open,
                steps_taken=steps_taken,
                max_steps=max_steps,
                current_path=self.current_path,
                planner_step=planner_steps
            )

            # 熔断或致命异常退出
            if plan_res is None:
                logger.warning("🚨 Planner 熔断退出，中止后续探索。")
                break

            # 重试请求
            if plan_res.get("retry"):
                continue

            # 智能提前完工
            if plan_res.get("early_stop"):
                break

            sub_objective = plan_res["sub_objective"]
            budget = plan_res["budget"]

            # 2. 单兵战术执行阶段 (Worker Phase)
            worker_res = self.worker.run_sub_task(
                sub_objective=sub_objective,
                budget=budget,
                context=context,
                global_history=global_history,
                page_tree=self.page_tree,
                reexplore_module=reexplore_module,
                container_stack=self.container_stack,
                is_panel_hidden=self.is_panel_hidden,
                mailing_dialog_open=self.mailing_dialog_open,
                last_l2_route=self.last_l2_route,
                start_step=steps_taken,
                max_steps=max_steps,
                current_path=self.current_path,
                active_tab=self.active_tab
            )

            # 3. 汇总与状态机同步
            steps_taken += worker_res["steps_used"]
            trajectory.extend(worker_res["trajectory"])
            self.container_stack = worker_res["container_stack"]
            self.is_panel_hidden = worker_res["is_panel_hidden"]
            self.mailing_dialog_open = worker_res["mailing_dialog_open"]
            self.last_l2_route = worker_res["last_l2_route"]
            self.active_tab = worker_res.get("active_tab", self.active_tab)

            # 3.1 看门狗超时死锁逃逸与陷阱跳过判定 (Sub-Objective Skip & Memory Sync)
            if worker_res.get("stuck_deadlock"):
                deadlock_reason = worker_res.get("deadlock_reason", "单步操作超时死锁")
                logger.critical(
                    f"\n{'='*70}\n"
                    f"⏭️ [Planner Skip] 战略放弃卡死子目标: '{sub_objective}'\n"
                    f"   原因: {deadlock_reason}\n"
                    f"   动作: 启动器已全自动冷重启完成解冻，当前子任务作为已知陷阱记录入全局记忆，直接向下规划！\n"
                    f"{'='*70}"
                )
                global_history.append(f"子目标: '{sub_objective}' (因'{deadlock_reason}'触发安全冷重启，已跳过此陷阱)")
                self._save_checkpoint(global_history)
                stuck_task_count = 0
                last_sub_objective = None
                continue

            # 4. 极端卡死与死锁逃逸：若连续派发同一子任务且 Worker 进展极小(<=1步)，说明界面已卡死无解
            if last_sub_objective == sub_objective and worker_res.get("steps_used", 0) <= 1:
                stuck_task_count += 1
            else:
                stuck_task_count = 0
            last_sub_objective = sub_objective

            if stuck_task_count >= 3:
                logger.warning(f"🚨 [Deadlock Escape] 检测到连续 {stuck_task_count} 次陷入死循环卡住不动 ('{sub_objective}')！")
                logger.warning("🔄 [Launcher Restart] 触发保护机制：安全关闭当前启动器，冷重启应用底座以彻底恢复干净现场...")
                try:
                    self.driver.restart_app()
                    self.container_stack.clear()
                    self.is_panel_hidden = False
                    self.mailing_dialog_open = False
                    stuck_task_count = 0
                    time.sleep(3)
                    continue
                except Exception as e_restart:
                    logger.error(f"❌ 重启启动器失败: {e_restart}")

            # 记录历史记忆
            global_history.append(f"执行子目标: '{sub_objective}' (完成)")

            # 定期保存检查点
            self._save_checkpoint(global_history)

            # 每 4 轮战略规划周期执行一次静默显存/内存泄漏哨兵巡检
            if not memory_leak_reported and planner_steps % 4 == 0 and hasattr(self.driver, "check_memory_leak"):
                try:
                    passed_mem, summary_mem, _ = self.driver.check_memory_leak(
                        label=f"planner_round_{planner_steps}",
                        trigger_gc=True
                    )
                    if not passed_mem:
                        memory_leak_reported = True
                        leak_img = self.explore_dir / f"memory_leak_round_{planner_steps}.png"
                        try:
                            self.driver.capture_screenshot(str(leak_img))
                        except Exception:
                            leak_img = None
                        curr_scope = " -> ".join(self.last_l2_route) if self.last_l2_route else "全局多页面长航巡检"
                        self.bug_reporter.report_bug(
                            run_id=self.run_id,
                            title=f"[{self.run_id}] 长航探索捕获前端内存/显存资源泄漏 ({curr_scope})",
                            step_prompt=f"[MEMORY_LEAK_CHECK] 第 {planner_steps} 轮战略巡检内存水位核验",
                            actual_result=summary_mem,
                            crash_image_path=str(leak_img) if leak_img and Path(leak_img).exists() else None,
                            action_type="MEMORY_LEAK_CHECK",
                            target_element=curr_scope,
                            global_step=steps_taken,
                            severity="High",
                            ui_path=curr_scope
                        )
                except Exception as e_mem_chk:
                    logger.debug(f"[MemoryProbe] 周期内存巡检异常忽略: {e_mem_chk}")

        # =====================================================================
        # 收尾：用例固化、产物归档与可视化报告生成
        # =====================================================================
        self._finish_exploration(trajectory, start_time, steps_taken, planner_steps, max_steps)
        return {
            "planner_steps": planner_steps,
            "worker_steps": steps_taken,
            "max_steps": max_steps,
            "elapsed_seconds": time.time() - start_time,
            "trajectory": trajectory
        }

    def _load_resume_state(self, resume_from: str, global_history: List[str]):
        """恢复历史断点状态"""
        resume_path = find_run_dir(resume_from) or Path(resume_from)
        if not resume_path.is_absolute():
            resume_path = RUNS_DIR / resume_from
        logger.info(f"🔄 正在从历史运行目录恢复状态: {resume_path}")

        chk = resume_path / "checkpoint"
        hist_file = (chk / "global_history.json") if (chk / "global_history.json").exists() else (resume_path / "global_history.json")
        if hist_file.exists():
            try:
                with open(hist_file, "r", encoding="utf-8") as f:
                    loaded_hist = json.load(f)
                    global_history.extend(loaded_hist)
                logger.info(f"✅ 成功恢复 global_history，包含 {len(global_history)} 条记忆。")
            except Exception as e:
                logger.error(f"恢复 global_history 失败: {e}")

        tree_file = (chk / "page_tree.json") if (chk / "page_tree.json").exists() else (resume_path / "page_tree.json")
        if tree_file.exists():
            try:
                with open(tree_file, "r", encoding="utf-8") as f:
                    self.page_tree = json.load(f)
                logger.info("✅ 成功恢复 page_tree 架构树。")
            except Exception as e:
                logger.error(f"恢复 page_tree 失败: {e}")

    def _apply_reexplore_module(self, reexplore_module: str, global_history: List[str]) -> List[str]:
        """应用指定模块的重探策略"""
        logger.info(f"🔄 [Re-explore Mode] 激活模块强制重探模式: 【{reexplore_module}】")
        PageMapBuilder.reset_module_subtree(self.page_tree, reexplore_module)
        clean_kw = reexplore_module.strip("【】'\" ")
        old_len = len(global_history)
        new_hist = [h for h in global_history if clean_kw not in h]
        logger.info(f"🧹 [Re-explore Mode] 已从 global_history 中清除 {old_len - len(new_hist)} 条相关历史记忆。")
        self._save_checkpoint(new_hist)
        return new_hist

    def _save_checkpoint(self, global_history: List[str]):
        """将当前状态静默保存至检查点"""
        try:
            tree_file = Path(self.checkpoint_dir) / "page_tree.json"
            with open(tree_file, "w", encoding="utf-8") as f:
                json.dump(self.page_tree, f, ensure_ascii=False, indent=2)

            hist_file = Path(self.checkpoint_dir) / "global_history.json"
            with open(hist_file, "w", encoding="utf-8") as f:
                json.dump(global_history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"保存检查点失败: {e}")

    def _finish_exploration(self, trajectory: List[Dict[str, Any]], start_time: float, steps_taken: int, planner_steps: int = 0, max_steps: int = 0):
        """收尾归档、生成用例与可视化大盘"""
        elapsed = time.time() - start_time
        max_steps_str = f"/{max_steps}" if max_steps else ""
        logger.info("\n" + "=" * 60)
        logger.info(f"🏁 自主探索结束！耗时: {elapsed:.1f} 秒 | 🧠 Planner 规划: {planner_steps} 轮 | 🎯 Worker 执行: {steps_taken}{max_steps_str} 步")
        logger.info("=" * 60)

        # 1. 导出自动化回归用例
        if trajectory:
            try:
                exporter = TrajectoryExporter(run_dir=self.run_dir, run_id=self.run_id)
                case_file = exporter.export_yaml(trajectory)
                if case_file:
                    logger.info(f"📝 自动生成确定性 YAML 用例: {case_file.name}")
            except Exception as e:
                logger.warning(f"导出用例失败: {e}")

        # 2. 导出接口大盘快照 (确保报告能统计出全量业务接口)
        try:
            shots_api_file = self.run_dir / "screenshots" / "api_registry.json"
            self.driver.dump_api_registry(str(shots_api_file))
        except Exception as api_err:
            logger.warning(f"导出接口大盘异常: {api_err}")

        # 2.5 收尾执行终态内存泄漏核验并导出完整内存时序曲线
        try:
            if hasattr(self.driver, "check_memory_leak"):
                passed_end_mem, summary_end_mem, _ = self.driver.check_memory_leak(label="explore_finish", trigger_gc=True)
                if not passed_end_mem:
                    end_leak_img = self.explore_dir / "memory_leak_finish.png"
                    try:
                        self.driver.capture_screenshot(str(end_leak_img))
                    except Exception:
                        end_leak_img = None
                    self.bug_reporter.report_bug(
                        run_id=self.run_id,
                        title=f"[{self.run_id}] 探索收尾终态显存/内存泄漏超标",
                        step_prompt=f"[MEMORY_LEAK_CHECK] 探索全程 ({steps_taken} 步) 终态内存回收核验",
                        actual_result=summary_end_mem,
                        crash_image_path=str(end_leak_img) if end_leak_img and Path(end_leak_img).exists() else None,
                        action_type="MEMORY_LEAK_CHECK",
                        target_element="全局应用渲染进程",
                        global_step=steps_taken,
                        severity="High",
                        ui_path="全局终态"
                    )
            if hasattr(self.driver, "dump_memory_timeline"):
                mem_file = self.run_dir / "screenshots" / "memory_timeline.json"
                self.driver.dump_memory_timeline(str(mem_file))
        except Exception as mem_err:
            logger.warning(f"导出内存水位时序曲线异常: {mem_err}")

        # 3. 统一持久化架构树并更新全局真理源
        try:
            PageMapBuilder.export_page_map(self.page_tree)
            logger.info("🗺️ [PageMapBuilder] 全局页面架构树已完成持久化与同步更新。")
        except Exception as tree_err:
            logger.warning(f"持久化架构树失败: {tree_err}")

        # 4. 生成交互式 HTML 大盘报告
        try:
            from utils.report_generator import ReportGenerator
            reporter = ReportGenerator(self.run_dir)
            report_file = reporter.generate_html()
            logger.info(f"🎉 巡检可视化大盘已生成: file:///{report_file.as_posix()}")
        except Exception as rep_err:
            logger.warning(f"生成最终报告失败: {rep_err}")

        # 5. 任务完成收尾自洁：清理 raw_bugs 临时目录与 checkpoint 缓存
        self._cleanup_post_run()

    def _cleanup_post_run(self):
        """
        任务完成入库后的自洁收尾机制：
        1. 自动清理 raw_bugs/ 临时目录 (中间抓取物已全部沉淀入库)；
        2. 自动清理 checkpoint/ 目录 (核心页面树已归入 page_map_builder 与 root，执行流均有 logs/数据库 保障)。
        """
        import shutil
        # 1. 清理 raw_bugs 临时目录
        raw_bugs_dir = self.run_dir / "raw_bugs"
        if raw_bugs_dir.exists():
            try:
                shutil.rmtree(raw_bugs_dir, ignore_errors=True)
                logger.info("🧹 [Cleanup] 任务收尾自洁：已清理 raw_bugs/ 临时中间目录。")
            except Exception as e:
                logger.debug(f"清理 raw_bugs 目录跳过: {e}")

        # 2. 清理 checkpoint 目录 (保全 page_tree.json 至运行根目录)
        chk_dir = self.run_dir / "checkpoint"
        if chk_dir.exists():
            try:
                tree_file = chk_dir / "page_tree.json"
                if tree_file.exists():
                    root_tree = self.run_dir / "page_tree.json"
                    if not root_tree.exists():
                        shutil.copy2(tree_file, root_tree)
                shutil.rmtree(chk_dir, ignore_errors=True)
                logger.info("🧹 [Cleanup] 任务收尾自洁：已清理 checkpoint/ 目录 (历史链路已完整记录于日志与数据库)。")
            except Exception as e:
                logger.debug(f"清理 checkpoint 目录跳过: {e}")

    def smoke_tour(self, total_menus_limit: Optional[int] = None, context: str = "", prompt: str = ""):
        """二级业务菜单全量冒烟巡检模式：兼具确定性两级跳转与全自动健康度体检（无声崩溃、接口异常、多模态视觉审图）"""
        from core.explorer_agent.page_map_builder import PageMapBuilder
        from config.settings import settings

        active_app = getattr(settings, "active_app", "")
        logger.info(f"🚀 启动【{active_app or '当前软件'}全量冒烟巡检模式】")
        if prompt:
            logger.info(f"🎯 [Smoke Prompt] 冒烟体检准则: {prompt}")

        menu_items = PageMapBuilder.get_all_l2_menus()
        if total_menus_limit:
            menu_items = menu_items[:total_menus_limit]

        total_menus = len(menu_items)
        if total_menus == 0:
            logger.warning("⚠️ [Smoke Tour] 未解析到任何二级业务菜单！请检查对应 docs/explore_rules_<app>.md 的基准菜单表格。")
            self._cleanup_post_run()
            return

        results = []
        jump_success_count = 0
        clean_health_count = 0
        start_time = time.time()

        for idx, (l1, l2) in enumerate(menu_items, 1):
            logger.info(f"\n🎯 [Smoke Tour ({idx}/{total_menus})] 正在巡检模块: 【{l1} -> {l2}】")
            jump_ok = False
            console_ok = True
            api_ok = True
            visual_ok = True
            jump_err_msg = ""
            thought = ""

            # ----------------------------------------------------
            # 阶段一：二级菜单智能跳转 (Smart Hover + Click)
            # ----------------------------------------------------
            if idx == 1 and l1 == "首页" and l2 == "矿山简介":
                self.driver.set_page_scope(f"{l1} -> {l2}")
                self.last_l2_route = (l1, l2)
                jump_ok = True
                jump_success_count += 1
            else:
                try:
                    info = self.driver.get_viewport_info()
                    width, height = info.get("width", 2560), info.get("height", 1440)

                    # 悬停 L1 一级菜单
                    hover_img_path = self.explore_dir / f"smoke_jump_{idx}_hover.png"
                    b64_hover = self.driver.capture_screenshot_base64(str(hover_img_path))
                    dom_hover = self.driver.extract_interactive_elements()
                    hx, hy = self.vision.find_element(
                        instruction=f"顶部一级菜单【{l1}】",
                        base64_image=b64_hover,
                        viewport_width=width,
                        viewport_height=height,
                        dom_elements=dom_hover
                    )
                    self.driver.hover(hx, hy, delay_after=1.5)

                    # 点击 L2 下拉菜单选项
                    click_img_path = self.explore_dir / f"smoke_jump_{idx}_click.png"
                    b64_click = self.driver.capture_screenshot_base64(str(click_img_path))
                    dom_click = self.driver.extract_interactive_elements()
                    cx, cy = self.vision.find_element(
                        instruction=f"下拉菜单中的【{l2}】选项",
                        base64_image=b64_click,
                        viewport_width=width,
                        viewport_height=height,
                        dom_elements=dom_click
                    )
                    self.driver.click(cx, cy, delay_after=1.5)

                    self.driver.set_page_scope(f"{l1} -> {l2}")
                    self.last_l2_route = (l1, l2)
                    jump_ok = True
                    jump_success_count += 1
                except Exception as j_err:
                    jump_err_msg = str(j_err)
                    logger.error(f"❌ [Smoke Jump] 跳转至【{l1} -> {l2}】失败: {jump_err_msg}")
                    self.bug_reporter.report_bug(
                        run_id=self.run_id,
                        title=f"[{self.run_id}] 冒烟巡检菜单跳转失败: 【{l1} -> {l2}】",
                        step_prompt=f"[SMOKE-JUMP] 悬停【{l1}】并点击【{l2}】",
                        actual_result=jump_err_msg,
                        crash_image_path=str(click_img_path) if 'click_img_path' in locals() and click_img_path.exists() else (str(hover_img_path) if 'hover_img_path' in locals() and hover_img_path.exists() else None),
                        before_image_path=str(hover_img_path) if 'hover_img_path' in locals() and hover_img_path.exists() else None,
                        action_type="SMOKE_JUMP",
                        target_element=f"{l1} -> {l2}",
                        global_step=idx,
                        severity="High",
                        ui_path=f"{l1} -> {l2}"
                    )

            # ----------------------------------------------------
            # 阶段二：当前页面三阶健康度体检 (直接委托给 Worker 统一质检单兵)
            # ----------------------------------------------------
            if jump_ok:
                time.sleep(1.5)
                plan_img_path = self.explore_dir / f"smoke_page_{idx}_plan.png"
                b64_plan = self.driver.capture_screenshot_base64(str(plan_img_path), dim_background=False)

                health_res = self.worker.inspect_page_health(
                    ui_path=f"{l1} -> {l2}",
                    step_num=idx,
                    prompt=prompt,
                    screenshot_path=plan_img_path,
                    b64_image=b64_plan
                )

                console_ok = health_res["console_ok"]
                api_ok = health_res["api_ok"]
                visual_ok = health_res["visual_ok"]
                thought = health_res["thought"]
                logger.info(f"💡 [Smoke Planner] 页面诊断与思考: {thought}")

                if health_res["healthy"]:
                    clean_health_count += 1

            results.append({
                "index": idx,
                "module": f"{l1} -> {l2}",
                "jump": "PASS" if jump_ok else f"FAIL ({jump_err_msg[:25]})",
                "console": "PASS" if console_ok else "FAIL",
                "api": "PASS" if api_ok else "FAIL",
                "visual": "PASS" if visual_ok else "FAIL",
                "thought": thought
            })

        logger.info(f"\n{'='*75}")
        logger.info(f"🏁 冒烟巡检完成！总二级业务菜单数: {total_menus}")
        if total_menus > 0:
            logger.info(f"   - 菜单跳转成功率: {jump_success_count}/{total_menus} ({(jump_success_count/total_menus*100):.1f}%)")
            logger.info(f"   - 完全健康通过率: {clean_health_count}/{total_menus} ({(clean_health_count/total_menus*100):.1f}%)")
        logger.info(f"{'='*75}")

        try:
            from utils.report_generator import ReportGenerator
            reporter = ReportGenerator(self.run_dir)
            report_file = reporter.generate_html()
            logger.info(f"📊 冒烟巡检大盘已生成: file:///{report_file.as_posix()}")
        except Exception as rep_err:
            logger.error(f"生成冒烟巡检报告失败: {rep_err}")

        # 任务完成收尾自洁
        self._cleanup_post_run()

    # 兼容历史公开接口命名
    start_exploration = explore
    start_smoke_tour = smoke_tour
