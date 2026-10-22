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
        trajectory: List[Dict[str, Any]] = []
        start_time = time.time()

        # 恢复断点历史
        if resume_from:
            self._load_resume_state(resume_from, global_history)

        # 模块重探模式处理
        if reexplore_module:
            global_history = self._apply_reexplore_module(reexplore_module, global_history)

        # =====================================================================
        # 核心主循环：统帅规划 (Planner) -> 单兵执行 (Worker)
        # =====================================================================
        while steps_taken < max_steps:
            elapsed_mins = (time.time() - start_time) / 60.0
            if elapsed_mins >= max_time_mins:
                logger.info(f"\n⏳ 达到最大探索时间限制 ({max_time_mins} 分钟)，停止探索。")
                break

            # 1. 统帅规划阶段 (Planner Phase)
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
                current_path=self.current_path
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
                current_path=self.current_path
            )

            # 3. 汇总与状态机同步
            steps_taken += worker_res["steps_used"]
            trajectory.extend(worker_res["trajectory"])
            self.container_stack = worker_res["container_stack"]
            self.is_panel_hidden = worker_res["is_panel_hidden"]
            self.mailing_dialog_open = worker_res["mailing_dialog_open"]
            self.last_l2_route = worker_res["last_l2_route"]

            # 记录历史记忆
            global_history.append(f"执行子目标: '{sub_objective}' (完成)")

            # 定期保存检查点
            self._save_checkpoint(global_history)

        # =====================================================================
        # 收尾：用例固化、产物归档与可视化报告生成
        # =====================================================================
        self._finish_exploration(trajectory, start_time, steps_taken)

    def _load_resume_state(self, resume_from: str, global_history: List[str]):
        """恢复历史断点状态"""
        resume_path = Path(resume_from)
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

    def _finish_exploration(self, trajectory: List[Dict[str, Any]], start_time: float, steps_taken: int):
        """收尾归档、生成用例与可视化大盘"""
        elapsed = time.time() - start_time
        logger.info("\n" + "=" * 60)
        logger.info(f"🏁 自主探索结束！耗时: {elapsed:.1f} 秒, 实际完成步数: {steps_taken}")
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

        # 2. 生成交互式 HTML 大盘报告
        try:
            from utils.report_generator import ReportGenerator
            reporter = ReportGenerator(self.run_dir)
            report_file = reporter.generate_html()
            logger.info(f"🎉 巡检可视化大盘已生成: file:///{report_file.as_posix()}")
        except Exception as rep_err:
            logger.warning(f"生成最终报告失败: {rep_err}")

    def smoke_tour(self, total_menus_limit: Optional[int] = None, context: str = ""):
        """二级菜单全量冒烟巡检模式"""
        from core.explorer_agent.page_map_builder import PageMapBuilder
        logger.info("🚀 [Smoke Tour] 启动全量业务二级菜单冒烟巡检...")

        menu_items = PageMapBuilder.get_all_l2_menus()
        if total_menus_limit:
            menu_items = menu_items[:total_menus_limit]

        total_menus = len(menu_items)
        results = []
        jump_success_count = 0
        plan_success_count = 0
        start_time = time.time()

        for idx, (l1, l2) in enumerate(menu_items, 1):
            logger.info(f"\n--- [Smoke Menu {idx}/{total_menus}] 正在巡检: 【{l1} -> {l2}】 ---")
            jump_ok = False
            plan_ok = False
            jump_err_msg = ""
            plan_err_msg = ""
            sub_objective = ""

            # 阶段一：二级菜单智能跳转
            if idx == 1 and l1 == "首页" and l2 == "矿山简介":
                self.driver.set_page_scope(f"{l1} -> {l2}")
                self.last_l2_route = (l1, l2)
                jump_ok = True
                jump_success_count += 1
            else:
                try:
                    info = self.driver.get_viewport_info()
                    width, height = info.get("width", 2560), info.get("height", 1440)

                    # 悬停 L1
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

                    # 点击 L2
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
                        actual_result=jump_err_msg
                    )

            # 阶段二：当前页面体检
            if jump_ok:
                try:
                    time.sleep(1.0)
                    plan_img_path = self.explore_dir / f"smoke_page_{idx}_plan.png"
                    b64_plan = self.driver.capture_screenshot_base64(str(plan_img_path), dim_background=True)
                    plan = self.vision.plan_sub_objective(
                        macro_objective=f"对当前【{l1} -> {l2}】页面进行冒烟体检，识别核心组件",
                        base64_image=b64_plan,
                        global_history=[f"【{l1} -> {l2}】"],
                        context=context,
                        current_page_tree={},
                        reexplore_module=l2
                    )
                    sub_objective = plan.get("sub_objective", f"测试【{l2}】核心业务组件")
                    self.driver.get_and_clear_bugs()
                    plan_ok = True
                    plan_success_count += 1
                except Exception as p_err:
                    plan_err_msg = str(p_err)

            results.append({
                "index": idx,
                "module": f"{l1} -> {l2}",
                "jump": "PASS" if jump_ok else f"FAIL ({jump_err_msg[:30]})",
                "plan": "PASS" if plan_ok else ("SKIPPED" if not jump_ok else f"FAIL ({plan_err_msg[:30]})"),
                "core_component": sub_objective if plan_ok else "-"
            })

        logger.info(f"🏁 冒烟巡检完成！跳转成功: {jump_success_count}/{total_menus}, 规划成功: {plan_success_count}/{total_menus}")
        try:
            from utils.report_generator import ReportGenerator
            reporter = ReportGenerator(self.run_dir)
            report_file = reporter.generate_html()
            logger.info(f"📊 冒烟巡检大盘已生成: file:///{report_file.as_posix()}")
        except Exception:
            pass

    # 兼容历史公开接口命名
    start_exploration = explore
    start_smoke_tour = smoke_tour
