"""
core/explorer_agent/planner.py —— 宏观战略规划统帅 (ExplorerPlanner)
==============================================================================
职责：
1. 观察全局环境，调用视觉大模型进行宏观态势分析与盲区推断；
2. 动态注入关键状态告警（如大屏一键隐藏、迈灵AI助手弹窗）；
3. 智能下达具有确定性战术意义的子任务 (sub_objective) 与步数预算 (budget)；
4. 完工智能提前判定 (Early Stop) 与防死锁熔断保护 (Circuit Breaker)。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config.settings import settings

logger = logging.getLogger("explorer_agent.planner")


class ExplorerPlanner:
    """自主探索战略规划统帅"""

    def __init__(self, driver: Any, vision: Any, bug_reporter: Any, explore_dir: Path, run_id: str):
        self.driver = driver
        self.vision = vision
        self.bug_reporter = bug_reporter
        self.explore_dir = Path(explore_dir)
        self.run_id = run_id

        self.consecutive_failures = 0
        self.max_failures = getattr(settings, "max_planner_failures", 8)
        self.recent_sub_objectives: List[str] = []

    def plan_next_task(
        self,
        macro_objective: str,
        global_history: List[str],
        context: str,
        page_tree: Dict[str, Any],
        reexplore_module: Optional[str] = None,
        container_stack: Optional[List[str]] = None,
        is_panel_hidden: bool = False,
        mailing_dialog_open: bool = False,
        steps_taken: int = 0,
        max_steps: int = 2000,
        current_path: Optional[List[str]] = None,
        planner_step: int = 1
    ) -> Optional[Dict[str, Any]]:
        """
        根据当前全屏环境快照规划下一步的子目标与步数预算。
        若熔断退出则返回 None；正常规划返回字典。
        """
        container_stack = container_stack or []
        logger.info(f"\n" + "=" * 40)
        logger.info(f"🧠 [Planner Phase {planner_step}] 开始规划，当前进度: {steps_taken}/{max_steps}")

        try:
            # 1. 捕获规划快照 (启用背景熄灯聚焦)
            planner_img_path = self.explore_dir / f"plan_step_{steps_taken + 1}.png"
            base64_img = self.driver.capture_screenshot_base64(str(planner_img_path), dim_background=True)

            # 2. 动态注入闭环状态与警报 (一键隐藏与迈灵弹窗)
            planner_context = context
            if is_panel_hidden:
                planner_context += "\n⚠️【大屏处于一键隐藏状态】当前页面 2D 业务面板已被收起/隐藏！如果页面存在【一键展开】按钮，必须保持一键展开状态：优先规划子目标为：'点击右侧面板边缘【一键展开】按钮恢复大屏面板显示'！绝对严禁规划点击顶部状态栏最右侧退出按钮！\n"
            if mailing_dialog_open or any("迈灵" in m for m in container_stack):
                planner_context += "\n⚠️【极度紧急：【迈灵】助手对话弹窗处于打开状态】当前屏幕底部悬浮着【迈灵】AI助手对话窗！必须优先规划子目标为：'再次点击顶部状态栏右上角的【迈灵】圆形功能按钮以关闭对话窗'！注意：该弹窗本身无独立关闭❌叉号，必须且只能再次点击【迈灵】按钮本身进行 Toggle 关闭！严禁去屏幕极右上角寻找关闭叉号！\n"

            # 3. 大模型宏观思考
            plan = self.vision.plan_sub_objective(
                macro_objective=macro_objective,
                base64_image=base64_img,
                global_history=global_history,
                context=planner_context,
                current_page_tree=page_tree,
                reexplore_module=reexplore_module,
                recent_sub_objectives=self.recent_sub_objectives,
                container_stack=container_stack
            )

            sub_objective = plan.get("sub_objective", "无子目标")
            thought = plan.get("thought", "")
            raw_budget = int(plan.get("allocated_steps", 8))
            is_completed = bool(plan.get("is_completed", False))

            # 4. 智能提前完工判定 (Smart Early Stop)
            completion_keywords = ["探索完成", "完全覆盖", "全面达成", "优雅收工", "结束探索", "已全部探索", "无未测盲区"]
            if is_completed or any(k in sub_objective for k in completion_keywords):
                logger.info("=" * 60)
                logger.info(f"🎉 [Planner Early Stop] 目标已 100% 达成，提前优雅收工！")
                logger.info(f"   📊 步数结余: 实际消耗 {steps_taken}/{max_steps} 步 (结余 {max_steps - steps_taken} 步)")
                logger.info(f"   💡 完工依据: {thought}")
                logger.info(f"   🎯 最终状态: {sub_objective}")
                logger.info("=" * 60)
                return {
                    "early_stop": True,
                    "sub_objective": sub_objective,
                    "budget": 0,
                    "thought": thought
                }

            # 记录近期目标防止局部振荡
            if sub_objective:
                self.recent_sub_objectives.append(sub_objective)
                if len(self.recent_sub_objectives) > 10:
                    self.recent_sub_objectives.pop(0)

            # 约束步数预算
            budget = max(1, min(raw_budget, 15))
            budget = min(budget, max_steps - steps_taken)

            logger.info(f"💡 [Planner] 思考链: {thought}")
            logger.info(f"🎯 [Planner] 下达新任务: '{sub_objective}', 预算步数: {budget}")

            self.consecutive_failures = 0
            return {
                "early_stop": False,
                "sub_objective": sub_objective,
                "budget": budget,
                "thought": thought
            }

        except Exception as e:
            self.consecutive_failures += 1
            logger.error(f"❌ Planner 规划失败 ({self.consecutive_failures}/{self.max_failures}): {e}")

            # 防死锁熔断判定
            if self.consecutive_failures >= self.max_failures:
                logger.critical("=" * 70)
                logger.critical(
                    f"🚨 [防死锁熔断] Planner 连续失败已达 {self.max_failures} 次上限！\n"
                    f"   判定被测客户端进程已崩溃退出或 CDP 调试通道彻底断开，主动触发紧急收工与产物归档！\n"
                    f"   最后捕获致命异常: {e}"
                )
                logger.critical("=" * 70)

                try:
                    path_str = " -> ".join(current_path) if current_path else "应用主界面"
                    self.bug_reporter.report_bug(
                        run_id=self.run_id,
                        title=f"[{self.run_id}] 客户端异常崩溃/调试连接断开 (防死锁熔断)",
                        step_prompt=f"自动化探索 Planner 阶段连续 {self.max_failures} 次无法捕获界面，CDP 调试通道已断开",
                        actual_result=f"致命异常: 目标页面或客户端进程已关闭。\n底层报错堆栈: {e}",
                        action_type="crash_circuit_breaker",
                        target_element="Electron客户端主窗口",
                        global_step=f"GlobalStep_{steps_taken}",
                        ui_path=path_str
                    )
                except Exception as report_err:
                    logger.warning(f"熔断时自动上报崩溃缺陷异常: {report_err}")

                return None

            logger.info("⏳ 休息 5 秒后准备重试 Planner...")
            time.sleep(5.0)
            return {"retry": True}
