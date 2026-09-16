import time
import logging
import json
from pathlib import Path
from typing import Optional

from core.browser import ElectronDriver
from core.vision_agent import VisionAgent
from utils.artifacts import SCREENSHOTS_DIR, report_run_id

logger = logging.getLogger("explorer_agent")

class ExplorerAgent:
    """
    自主探索 Agent：基于大模型视觉能力，自动在 Electron 大屏中随机游走或基于目标进行探索。
    """

    def __init__(self, driver: ElectronDriver, vision: VisionAgent):
        self.driver = driver
        self.vision = vision
        self.run_id = report_run_id()
        
        # 彻底隔离：存放在 reports/explore_screenshots 目录下
        from utils.artifacts import PROJECT_ROOT
        self.explore_dir = PROJECT_ROOT / "reports" / "explore_screenshots" / self.run_id
        self.explore_dir.mkdir(parents=True, exist_ok=True)

    def start_exploration(self, objective: str, max_steps: int = 20, context: str = ""):
        """
        开启自主探索循环
        :param objective: 宏观探索目标
        :param max_steps: 最大探索步数
        :param context: 注入的项目背景知识或探索规则
        """
        logger.info("=" * 60)
        logger.info(f"🚀 开启自主探索模式 | 目标: {objective}")
        if context:
            logger.info(f"📚 已加载探索先验知识: {len(context)} 字符")
        logger.info(f"🛑 最大步数限制: {max_steps} | Run ID: {self.run_id}")
        logger.info("=" * 60)

        steps_taken = 0
        global_history = []

        while steps_taken < max_steps:
            logger.info(f"\n" + "=" * 40)
            logger.info(f"🧠 [Planner Phase] 开始规划，当前进度: {steps_taken}/{max_steps}")
            
            # --- Planner Phase ---
            try:
                # 截取全局状态图给 Planner
                planner_img_path = self.explore_dir / f"plan_step_{steps_taken+1}.png"
                base64_img = self.driver.capture_screenshot_base64(str(planner_img_path))
                
                plan = self.vision.plan_sub_objective(
                    macro_objective=objective,
                    base64_image=base64_img,
                    global_history=global_history,
                    context=context
                )
                
                sub_objective = plan.get("sub_objective", "无子目标")
                thought = plan.get("thought", "")
                budget = int(plan.get("allocated_steps", 8))
                
                # 约束 budget 不能超过剩余的总步数限制，且最好给一个上限防止无限循环
                budget = max(1, min(budget, 15))
                budget = min(budget, max_steps - steps_taken)
                
                logger.info(f"💡 [Planner] 思考链: {thought}")
                logger.info(f"🎯 [Planner] 下达新任务: '{sub_objective}', 预算步数: {budget}")
                
            except Exception as e:
                logger.error(f"❌ Planner 规划失败: {e}")
                logger.info("⏳ 休息 5 秒后重试 Planner...")
                time.sleep(5.0)
                continue

            # --- Worker Phase ---
            action_history = []
            worker_finished_early = False
            
            for worker_step in range(1, budget + 1):
                steps_taken += 1
                logger.info(f"\n--- [Worker Step {worker_step}/{budget}] (Global: {steps_taken}/{max_steps}) ---")
                
                # 1. 截图并获取 Base64
                step_img_path = self.explore_dir / f"explore_step_{steps_taken}.png"
                try:
                    base64_img = self.driver.capture_screenshot_base64(str(step_img_path))
                    logger.info(f"📸 捕获环境快照: {step_img_path.name}")
                except Exception as e:
                    logger.error(f"❌ Worker 截图失败，中止当前任务: {e}")
                    break

                # 2. 获取视口信息
                info = self.driver.get_viewport_info()
                width = info.get("width", 2560)
                height = info.get("height", 1440)

                # 3. 将截图与子目标送给 Worker 决策
                try:
                    decision = self.vision.execute_sub_objective(
                        sub_objective=sub_objective,
                        base64_image=base64_img,
                        context=context,
                        history=action_history,
                        global_history=global_history
                    )
                except Exception as e:
                    logger.error(f"❌ Worker 决策失败: {e}")
                    logger.info("⏳ Worker 休息 5 秒...")
                    time.sleep(5.0)
                    # 如果决策失败，为了防止死循环，我们强制消耗步数并继续
                    continue

                action_type = decision.get("action", "finish")
                thought = decision.get("thought", "无思考过程")
                element_desc = decision.get("element_desc", "未知元素")
                
                logger.info(f"💡 [Worker] 思考链: {thought}")
                logger.info(f"🤖 [Worker] 决定: [{action_type.upper()}] -> 目标: {element_desc}")

                # 4. 执行决策
                if action_type == "finish":
                    logger.info("✅ [Worker] 判断当前子任务已完成，或无更多可探索内容，提前汇报给 Planner。")
                    worker_finished_early = True
                    break
                    
                elif action_type == "wait":
                    logger.info("⏳ [Worker] 决定停留观察 3 秒...")
                    time.sleep(3.0)
                    
                elif action_type in ("click", "hover"):
                    x_pct = decision.get("x_percent")
                    y_pct = decision.get("y_percent")
                    if x_pct is None or y_pct is None:
                        logger.error(f"❌ 返回动作缺少坐标(x_percent, y_percent)，跳过此步。")
                        continue
                    
                    x = int(max(0, min(1, float(x_pct))) * width)
                    y = int(max(0, min(1, float(y_pct))) * height)
                    
                    logger.info(f"🎯 换算物理坐标: ({x}, {y})")
                    try:
                        if action_type == "hover":
                            self.driver.hover(x, y, delay_after=1.0)
                            time.sleep(2.0)
                        else:
                            self.driver.click(x, y, button="left", delay_after=2.0)
                    except Exception as e:
                        logger.error(f"❌ 执行失败: {e}")
                else:
                    logger.warning(f"⚠️ 未知的动作类型: {action_type}，跳过此步。")
                    time.sleep(1.0)
                    
                # 记录短期历史
                history_str = f"Worker 第 {worker_step} 步: [{action_type.upper()}] {element_desc}"
                action_history.append(history_str)
                if len(action_history) > 6:
                    action_history.pop(0)
                    
                # 记录全局历史
                if action_type in ("click", "hover") and element_desc not in global_history:
                    global_history.append(element_desc)
                    # 实时持久化长期记忆到本地
                    history_file = self.explore_dir / "global_history.json"
                    with open(history_file, "w", encoding="utf-8") as f:
                        json.dump(global_history, f, ensure_ascii=False, indent=2)

            if not worker_finished_early:
                logger.info(f"✅ [Worker] 已耗尽预算步数 ({budget})，将控制权交还给 Planner。")

        logger.info("=" * 60)
        logger.info("🏁 探索任务结束！")
        logger.info(f"📂 探索产生的截图和日志已保存至: {self.explore_dir}")
        logger.info("=" * 60)
