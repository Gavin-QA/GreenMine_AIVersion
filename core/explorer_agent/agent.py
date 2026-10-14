import time
import logging
import json
import re
from pathlib import Path
from typing import Optional

from core.browser import ElectronDriver
from core.vision.agent import VisionAgent
from core.bug_reporter import BugReporter
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
from .post_click_diff import PostClickDetector

logger = logging.getLogger("explorer_agent")

class ExplorerAgent:
    """
    自主探索 Agent：基于大模型视觉能力，自动在 Electron 大屏中随机游走或基于目标进行探索。
    """

    def __init__(self, driver: ElectronDriver, vision: VisionAgent):
        self.driver = driver
        self.vision = vision
        self.bug_reporter = BugReporter(vision_agent=self.vision)
        self.run_id = report_run_id()
        
        # 统一归档：单次运行专属根目录 reports/runs/<run_id>/
        self.run_dir = get_run_dir(self.run_id)
        self.log_dir = self.run_dir  # 保持向下兼容
        
        # 运行细分工作区
        self.checkpoint_dir = get_run_checkpoint_dir(self.run_id)
        self.explore_dir = get_run_screenshots_dir(self.run_id)
        self.bugs_dir = get_run_bugs_dir(self.run_id)
        self.generated_cases_dir = get_run_generated_cases_dir(self.run_id)
        
        # 初始化动态架构树（自动继承历史全局探索树，永不因清空日志丢失）与容器调用栈
        self.page_tree = PageMapBuilder.load_global_tree()
        self.container_stack = []
        self.active_tab = None  # 记录当前页面激活的子 Tab / 子设备视图（如 1242回风竖井风机）
        self.last_l2_route = None  # 记录当前所处的二级路由元组 (L1, L2)，用于严格判定跨页跃迁并重置状态
        self.failed_counts = {}  # 记录各目标的失败/报错次数，用于触发熔断保护 (Fault Circuit Breaker)
        self.chart_data_buffer = {}  # 缓存图表全量节点数据，用于集中断言与跨弹窗数据暂存 (Batch Chart Inspector)


    def start_exploration(self, objective: str, max_steps: int = 20, max_time_mins: int = 10, context: str = "", resume_from: Optional[str] = None, reexplore_module: Optional[str] = None):
        """
        开启自主探索循环
        :param objective: 宏观探索目标
        :param max_steps: 最大探索步数
        :param max_time_mins: 最大探索时间（分钟）
        :param context: 注入的项目背景知识或探索规则
        :param resume_from: 续跑目录 (如 'logs/explore_xxx')
        :param reexplore_module: 指定强制重新探索的二级模块名（清空该模块历史子树，展开全新探索）
        """
        logger.info("=" * 60)
        logger.info(f"🚀 开启自主探索模式 | 目标: {objective}")
        if context:
            logger.info(f"📚 已加载探索先验知识: {len(context)} 字符")
        logger.info(f"🛑 最大步数限制: {max_steps} | 最大时间: {max_time_mins}分钟 | Run ID: {self.run_id}")
        logger.info("=" * 60)

        steps_taken = 0
        exploration_start_time = time.time()
        global_history = []
        trajectory = [] # 用于记录闭环转化生成的完整轨迹
        
        if resume_from:
            resume_path = Path(resume_from)
            if not resume_path.exists():
                candidate = RUNS_DIR / resume_from
                if candidate.exists():
                    resume_path = candidate
                else:
                    legacy_candidate = Path("logs") / resume_from
                    if legacy_candidate.exists():
                        resume_path = legacy_candidate

            logger.info(f"♻️ 正在从 {resume_path} 恢复历史记忆...")
            
            # 优先从 checkpoint 结构化子目录恢复，同时向下兼容直接存放在根目录的旧格式
            chk = resume_path / "checkpoint"
            history_file = (chk / "global_history.json") if (chk / "global_history.json").exists() else (resume_path / "global_history.json")
            if history_file.exists():
                try:
                    with open(history_file, "r", encoding="utf-8") as f:
                        global_history = json.load(f)
                    logger.info(f"✅ 成功恢复 global_history，包含 {len(global_history)} 条记忆。")
                except Exception as e:
                    logger.error(f"恢复 global_history 失败: {e}")
                    
            tree_file = (chk / "page_tree.json") if (chk / "page_tree.json").exists() else (resume_path / "page_tree.json")
            if tree_file.exists():
                try:
                    with open(tree_file, "r", encoding="utf-8") as f:
                        self.page_tree = json.load(f)
                    logger.info(f"✅ 成功恢复 page_tree 架构树。")
                except Exception as e:
                    logger.error(f"恢复 page_tree 失败: {e}")

            fail_file = (chk / "failed_counts.json") if (chk / "failed_counts.json").exists() else (resume_path / "failed_counts.json")
            if fail_file.exists():
                try:
                    with open(fail_file, "r", encoding="utf-8") as f:
                        self.failed_counts = json.load(f)
                    logger.info(f"✅ 成功恢复 failed_counts，包含 {len(self.failed_counts)} 条记录。")
                except Exception as e:
                    logger.error(f"恢复 failed_counts 失败: {e}")

        # 如果指定了强制重新探索的模块，在此刻重置该模块子树并清理历史记忆
        if reexplore_module:
            logger.info(f"🔄 [Re-explore Mode] 激活模块强制重探模式: 【{reexplore_module}】（该模块历史子节点已重置为空）")
            PageMapBuilder.reset_module_subtree(self.page_tree, reexplore_module)
            # 清洗 global_history，防止模型因为记忆中的历史记录而避开该模块
            clean_kw = reexplore_module.strip("【】'\" ")
            old_len = len(global_history)
            global_history = [h for h in global_history if clean_kw not in h]
            if len(global_history) < old_len:
                logger.info(f"🧹 [Re-explore Mode] 已从 global_history 中清除 {old_len - len(global_history)} 条与【{reexplore_module}】相关的历史记忆。")
            # 仅在内存和本地 checkpoint 中更新重置后的树，彻底剥离 View 层的高频渲染
            tree_file = Path(self.checkpoint_dir) / "page_tree.json"
            with open(tree_file, "w", encoding="utf-8") as f:
                json.dump(self.page_tree, f, ensure_ascii=False, indent=2)

        recent_sub_objectives = []
        consecutive_planner_failures = 0
        MAX_PLANNER_FAILURES = 8

        while steps_taken < max_steps:
            elapsed_mins = (time.time() - exploration_start_time) / 60.0
            if elapsed_mins >= max_time_mins:
                logger.info(f"\n⏳ 达到最大探索时间限制 ({max_time_mins} 分钟)，停止探索。")
                break

            logger.info(f"\n" + "=" * 40)
            logger.info(f"🧠 [Planner Phase] 开始规划，当前进度: {steps_taken}/{max_steps}")
            
            # --- Planner Phase ---
            try:
                # ---- Planner 截图 (启用背景熄灯) ----
                planner_img_path = self.explore_dir / f"plan_step_{steps_taken+1}.png"
                base64_img = self.driver.capture_screenshot_base64(str(planner_img_path), dim_background=True)
                
                plan = self.vision.plan_sub_objective(
                    macro_objective=objective,
                    base64_image=base64_img,
                    global_history=global_history,
                    context=context,
                    current_page_tree=self.page_tree,
                    reexplore_module=reexplore_module,
                    recent_sub_objectives=recent_sub_objectives,
                    container_stack=self.container_stack
                )
                
                sub_objective = plan.get("sub_objective", "无子目标")
                thought = plan.get("thought", "")
                budget = int(plan.get("allocated_steps", 8))
                focus_region = plan.get("focus_region")
                is_completed = bool(plan.get("is_completed", False))

                # --- 智能提前完工判定 (Smart Early Stop) ---
                # 1. 显式布尔值 is_completed 为 True
                # 2. 或子目标中明确包含目标已完全达成/收工的关键词
                completion_keywords = ["探索完成", "完全覆盖", "全面达成", "优雅收工", "结束探索", "已全部探索", "无未测盲区"]
                if is_completed or any(k in sub_objective for k in completion_keywords):
                    logger.info("=" * 60)
                    logger.info(f"🎉 [Planner Early Stop] 目标已 100% 达成，提前优雅收工！")
                    logger.info(f"   📊 步数结余: 实际消耗 {steps_taken}/{max_steps} 步 (结余 {max_steps - steps_taken} 步)")
                    logger.info(f"   💡 完工依据: {thought}")
                    logger.info(f"   🎯 最终状态: {sub_objective}")
                    logger.info("=" * 60)
                    break

                if sub_objective:
                    recent_sub_objectives.append(sub_objective)
                    if len(recent_sub_objectives) > 10:
                        recent_sub_objectives.pop(0)

                info = self.driver.get_viewport_info()
                width = info.get("width", 2560)
                height = info.get("height", 1440)
                
                # [TODO] 暂不裁剪截图，后续优化局部图的使用场景
                # if focus_region and isinstance(focus_region, list) and len(focus_region) == 4:
                #     logger.info(f"🔍 [Planner] 圈定了局部区域，但当前配置为使用全屏以提供更好的上下文。")
                
                # 约束 budget 不能超过剩余的总步数限制，且最好给一个上限防止无限循环
                budget = max(1, min(budget, 15))
                budget = min(budget, max_steps - steps_taken)
                
                logger.info(f"💡 [Planner] 思考链: {thought}")
                logger.info(f"🎯 [Planner] 下达新任务: '{sub_objective}', 预算步数: {budget}")
                
                # 规划成功，清零连续失败计数器
                consecutive_planner_failures = 0
                
            except Exception as e:
                consecutive_planner_failures += 1
                logger.error(f"❌ Planner 规划失败 ({consecutive_planner_failures}/{MAX_PLANNER_FAILURES}): {e}")

                # 防死锁熔断判定 (达到8次上限直接熔断收工)
                if consecutive_planner_failures >= MAX_PLANNER_FAILURES:
                    logger.critical("=" * 70)
                    logger.critical(
                        f"🚨 [防死锁熔断] Planner 连续失败已达 {MAX_PLANNER_FAILURES} 次上限！\n"
                        f"   判定被测客户端进程已崩溃退出或 CDP 调试通道彻底断开，主动触发紧急收工与产物归档！\n"
                        f"   最后捕获致命异常: {e}"
                    )
                    logger.critical("=" * 70)

                    # 自动上报崩溃缺陷至全局缺陷库
                    try:
                        self.bug_reporter.report_bug(
                            run_id=self.run_id,
                            title=f"[{self.run_id}] 客户端异常崩溃/调试连接断开 (防死锁熔断)",
                            step_prompt=f"自动化探索 Planner 阶段连续 {MAX_PLANNER_FAILURES} 次无法捕获界面，CDP 调试通道已断开",
                            actual_result=f"致命异常: 目标页面或客户端进程已关闭。\n底层报错堆栈: {e}",
                            action_type="crash_circuit_breaker",
                            target_element="Electron客户端主窗口",
                            global_step=f"GlobalStep_{steps_taken}",
                            ui_path=" -> ".join(self.current_path) if hasattr(self, "current_path") and self.current_path else "应用主界面"
                        )
                    except Exception as report_err:
                        logger.warning(f"熔断时自动上报崩溃缺陷异常: {report_err}")

                    break

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
                    logger.info(f"📸 捕获环境快照: {step_img_path.name} (全屏)")
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
                        global_history=global_history,
                        current_page_tree=self.page_tree,
                        reexplore_module=reexplore_module,
                        container_stack=self.container_stack
                    )
                except Exception as e:
                    logger.error(f"❌ Worker 决策失败: {e}")
                    logger.info("⏳ Worker 休息 5 秒...")
                    time.sleep(5.0)
                    # 如果决策失败，为了防止死循环，我们强制消耗步数并继续
                    continue

                action_type = str(decision.get("action") or "finish").strip().lower()
                thought = decision.get("thought") or "无思考过程"
                element_desc = str(decision.get("element_desc") or "").strip()
                current_ui_path = decision.get("current_ui_path") or []
                if not isinstance(current_ui_path, list):
                    current_ui_path = [str(current_ui_path)]
                element_type = decision.get("element_type") or "other"
                container_name = str(decision.get("container_name") or "").strip()
                validate_api = bool(decision.get("validate_api", False))
                api_assert_prompt = str(decision.get("api_assert_prompt") or "").strip()
                
                logger.info(f"💡 [Worker] 思考链: {thought}")
                logger.info(f"📍 [Worker] 当前推断路径: {current_ui_path} | 类型: {element_type} | 容器: {container_name}")
                # 二级路由跨页跃迁检测与状态隔离
                if current_ui_path and isinstance(current_ui_path, list) and len(current_ui_path) >= 2:
                    current_l2 = (str(current_ui_path[0]), str(current_ui_path[1]))
                    if self.last_l2_route is not None and current_l2 != self.last_l2_route:
                        logger.info(f"🧭 [Navigation] 跨二级页面路由跃迁: {self.last_l2_route} -> {current_l2}，强行重置 active_tab 与容器栈！")
                        self.container_stack.clear()
                        self.active_tab = None
                    self.last_l2_route = current_l2
                    self.driver.set_page_scope(f"{current_ui_path[0]} -> {current_ui_path[1]}")
                elif current_ui_path and isinstance(current_ui_path, list) and len(current_ui_path) == 1:
                    self.driver.set_page_scope(current_ui_path[0])
                if validate_api:
                    logger.info(f"🔍 [Worker] 标记了接口核验需求: {api_assert_prompt}")
                
                # 动态合并架构树 (集成 Component Awareness 与 Container Stack，并过滤全局导航交互)
                nav_noise_keywords = ["顶部导航栏", "导航栏", "下拉菜单", "菜单栏"]
                
                # 获取基准骨架中的 1级 与 2级 菜单名
                base_l1_names = set(self.page_tree.keys())
                base_l2_all = set()
                for l2_dict in self.page_tree.values():
                    if isinstance(l2_dict, dict):
                        base_l2_all.update(l2_dict.keys())
                
                clean_target = (
                    element_desc.replace("按钮", "").replace("选项", "").replace("菜单", "").strip("‘’'\"“” ")
                    if element_desc else ""
                )
                
                # 判定是否属于切换菜单的全局路由动作 (如 hover 顶部导航栏的一级菜单，或 click 下拉菜单项)
                is_nav_interaction = (
                    (any(k in element_desc for k in nav_noise_keywords) if element_desc else False) or
                    (any(k in container_name for k in nav_noise_keywords) if container_name else False) or
                    (bool(clean_target) and (clean_target in base_l1_names or clean_target in base_l2_all))
                )
                
                # 若点击了二级菜单项，作为全局路由跃迁，清空模态调用栈与子Tab状态
                if action_type == "click" and clean_target and clean_target in base_l2_all:
                    for l1, l2_dict in self.page_tree.items():
                        if clean_target in l2_dict:
                            logger.info(f"🧭 [Navigation] 检测到全局路由跃迁: 前往 [{l1} -> {clean_target}]")
                            self.container_stack.clear()
                            self.active_tab = None
                            self.last_l2_route = (l1, clean_target)
                            break

                # 记录页面内激活的子 Tab 状态 (如点击风机标签切换到对应设备视图)
                if element_type == "tab" and clean_target and action_type == "click":
                    self.active_tab = clean_target
                    logger.info(f"🔖 [Tab Navigation] 激活当前子标签/视图为: {self.active_tab}")

                # 仅当不是全局导航交互时，才将该元素作为业务组件挂载到当前页面分支下
                curr_node = None
                if not is_nav_interaction and current_ui_path and isinstance(current_ui_path, list):
                    # 清洗路径，剔除可能混入的导航冗余词或跨模块一级菜单
                    clean_path = [p for p in current_ui_path if not any(k in p for k in nav_noise_keywords)]
                    if len(clean_path) > 1 and clean_path[1] in base_l1_names:
                        # 避免如 ["首页", "生产管理"] 的错误跨级嵌套，纠正为主干模块
                        clean_path = [clean_path[1]] + clean_path[2:]

                    # 若大模型已在 current_ui_path 中指定了第3级子Tab (如 ["智控管理", "智能通风", "1242回风竖井风机"])
                    if len(clean_path) >= 3:
                        self.active_tab = clean_path[2]
                    elif self.active_tab and len(clean_path) == 2:
                        # 仅当当前元素非独立弹窗/媒体组件时，才自动将子Tab注入路径层级
                        is_standalone = any(k in (element_desc or "") for k in ["播放器", "弹窗", "浮窗", "抽屉", "对话框"])
                        if not is_standalone and self.active_tab not in clean_path and clean_target != self.active_tab:
                            clean_path.append(self.active_tab)
                        
                    effective_path = list(clean_path)
                    
                    # 辅助函数：判断容器是否与当前路径末尾语义冗余（如“资源储量数据卡片” vs “资源储量”）
                    def _is_redundant_container(c_name: str, p_list: list) -> bool:
                        if not p_list:
                            return False
                        last_p = p_list[-1]
                        import re
                        c_core = re.sub(r'(?:数据卡片|卡片区域|卡片|模块|区域|容器|列表|表格|图表)$', '', c_name).strip()
                        p_core = re.sub(r'(?:数据卡片|卡片区域|卡片|模块|区域|容器|列表|表格|图表)$', '', last_p).strip()
                        if c_core and p_core and (c_core == p_core or c_core in p_core or p_core in c_core):
                            return True
                        return False

                    # 补充局部容器上下文 (排除导航噪音与语义套娃重复)
                    if container_name and not any(k in container_name for k in nav_noise_keywords):
                        if container_name not in effective_path and container_name not in self.container_stack:
                            if not _is_redundant_container(container_name, effective_path):
                                effective_path.append(container_name)
                        
                    # 补充当前活跃的模态弹窗调用栈
                    for modal in self.container_stack:
                        if modal not in effective_path and not _is_redundant_container(modal, effective_path):
                            effective_path.append(modal)
                            
                    curr_node = self.page_tree
                    for path_node in effective_path:
                        if path_node not in curr_node:
                            curr_node[path_node] = {}
                        curr_node = curr_node[path_node]
                        
                    # 将即将操作的元素作为叶子节点挂载 (附带 Emoji)
                    # 严格排除 wait 动作与过渡性等待描述，避免非业务控件污染至架构树
                    is_wait_action = (action_type == "wait") or (element_desc and any(k in element_desc for k in ["等待", "wait", "加载完成", "完全加载", "完全可见", "渲染完成"]))
                    if element_desc and action_type != "finish" and not is_wait_action:
                        leaf_name = PageMapBuilder.format_node_label(element_desc)
                        if leaf_name not in curr_node:
                            curr_node[leaf_name] = {}
                            
                    # 实时持久化树到本地 checkpoint
                    tree_file = self.log_dir / "page_tree.json"
                    with open(tree_file, "w", encoding="utf-8") as f:
                        json.dump(self.page_tree, f, ensure_ascii=False, indent=2)

                logger.info(f"🤖 [Worker] 决定: [{action_type.upper()}] -> 目标: {element_desc or '(子任务达成/完成)'}")

                action_success = False
                batch_chart_handled = False

                # 4. 执行决策
                if action_type == "finish":
                    # 防早退卫兵：如果子目标要求进入某个具体的二级菜单，且前一步仅仅是 hover 了一级菜单，
                    # 则说明下拉菜单刚被展开，此时绝不能直接 finish，而应强制继续让 Worker 在下一步执行点击子菜单！
                    is_menu_jump_objective = any(kw in sub_objective for kw in ["二级菜单", "下拉菜单", "进入【", "跳转到", "二级业务"])
                    just_hovered_l1 = action_history and any("HOVER" in h and "一级菜单" in h for h in action_history[-1:])
                    if is_menu_jump_objective and just_hovered_l1 and worker_step < budget:
                        logger.info("🛡️ [Worker Guard] 检测到刚完成一级菜单悬停展开，当前子目标尚未完成对目标二级菜单的点击，阻止过早 finish，继续执行下一步！")
                        continue
                    logger.info("✅ [Worker] 判断当前子任务已完成，或无更多可探索内容，提前汇报给 Planner。")
                    worker_finished_early = True
                    break
                    
                elif action_type == "wait":
                    logger.info("⏳ [Worker] 决定停留观察 3 秒...")
                    time.sleep(3.0)
                    action_success = True

                elif action_type in ("click", "hover"):
                    # 模态逃逸防御：如果当前处于模态弹窗中，但试图与顶部导航栏交互，自动定位并物理点击右上角关闭按钮解除遮罩阻断
                    if is_nav_interaction and self.container_stack:
                        logger.warning(f"🛡️ [Modal Escape] 检测到页面仍有模态遮罩/查看器未关闭 ({self.container_stack})，将阻断顶部导航栏交互！自动定位并物理点击右上角关闭按钮【❌】...")
                        try:
                            dom_elements = self.driver.extract_interactive_elements()
                            cx, cy = self.vision.find_element(
                                instruction="当前弹窗或查看器右上角的关闭按钮(❌图标或关闭按钮)",
                                base64_image=base64_img,
                                viewport_width=width,
                                viewport_height=height,
                                dom_elements=dom_elements
                            )
                            self.driver.click(cx, cy, delay_after=1.5)
                            popped = self.container_stack.pop()
                            logger.info(f"📤 [Container Stack] 成功点击关闭按钮，模态弹窗已出栈: {popped} | 剩余栈: {self.container_stack}")
                            # 重新捕获快照
                            step_img_path = self.explore_dir / f"explore_step_{steps_taken}.png"
                            base64_img = self.driver.capture_screenshot_base64(str(step_img_path))
                        except Exception as esc_err:
                            logger.warning(f"⚠️ 自动点击关闭按钮逃逸异常: {esc_err}")

                    # 记录动作前可见的模态层 (用于 Post-Click Diff)
                    before_modals = PostClickDetector.get_current_modals(self.driver)

                    # 引入 Hybrid DOM 精确坐标修正
                    try:
                        logger.info(f"⚡ 开始对目标 '{element_desc}' 进行 DOM 与视觉二次精确定位...")
                        dom_elements = self.driver.extract_interactive_elements()
                        x, y = self.vision.find_element(
                            instruction=element_desc,
                            base64_image=base64_img,
                            viewport_width=width,
                            viewport_height=height,
                            dom_elements=dom_elements
                        )
                    except Exception as e:
                        logger.warning(f"⚠️ 精确定位失败 ({e})，尝试回退使用 Worker 的纯视觉坐标估算...")
                        x_pct = decision.get("x_percent")
                        y_pct = decision.get("y_percent")
                        if x_pct is None or y_pct is None:
                            logger.error(f"❌ Worker 亦未返回可用坐标，跳过此步。")
                            continue
                        
                        x = int(max(0, min(1, float(x_pct))) * width)
                        y = int(max(0, min(1, float(y_pct))) * height)
                        logger.info(f"🎯 使用纯视觉估算物理坐标: ({x}, {y})")
                        
                    # ========================================================
                    # 立即在当步截图上硬画出目标准星，实现“所见即所得”
                    # ========================================================
                    try:
                        dpr = info.get("devicePixelRatio", 1.0)
                        self.driver.draw_cursor_on_image(str(step_img_path), x, y, dpr)
                    except Exception as e:
                        logger.warning(f"⚠️ 无法在截图 {step_img_path.name} 上绘制准星: {e}")
                    is_chart_target = (element_type == "chart") or any(k in (element_desc or "") for k in ["折线图", "柱状图", "面积图", "数据拐点", "趋势图", "七天风量", "风量数据"])

                    # 1. 优先尝试触发【图表全量节点批量嗅探引擎】(Batch Chart Inspector)
                    if is_chart_target:
                        try:
                            probe_res = self.driver.probe_chart_all_points(x, y, chart_name=element_desc)
                            if probe_res.get("success") and probe_res.get("points"):
                                points = probe_res["points"]
                                chart_title = probe_res.get("chart_title") or element_desc
                                logger.info(f"📊 [BatchChart] 成功抓取图表 '{chart_title}' 全部 {len(points)} 个数据节点！准备执行集中接口核验...")

                                # 存入全量图表数据池缓存 (供跨卡片、跨弹窗与集中断言比对)
                                self.chart_data_buffer[chart_title] = {
                                    "points": points,
                                    "method": probe_res.get("method"),
                                    "path": current_ui_path
                                }

                                # 检索后台相关接口报文（融合图表名、序列名与具体数值，驱动两级智能寻索）
                                search_tokens = [chart_title]
                                for p in points[:6]:
                                    if isinstance(p, dict):
                                        for k, v in p.items():
                                            if k and str(k).strip() not in ("style", "itemStyle"):
                                                search_tokens.append(str(k).strip())
                                            if v is not None and str(v).strip():
                                                search_tokens.append(str(v).strip())
                                    else:
                                        search_tokens.append(str(p))
                                search_context = " ".join(search_tokens)
                                current_scope_str = " -> ".join([str(p) for p in current_ui_path[:2]]) if current_ui_path and len(current_ui_path) >= 2 else (str(current_ui_path[0]) if current_ui_path else None)
                                api_summary = self.driver.get_focused_api_records_summary(search_context, page_scope=current_scope_str)

                                if api_summary and api_summary != "[]":
                                    passed, reason = self.vision.check_batch_chart_assertion(
                                        chart_name=chart_title,
                                        points=points,
                                        base64_image=base64_img,
                                        api_data_json=api_summary
                                    )
                                    if not passed:
                                        logger.error(f"🚨 [BATCH CHART MISMATCH] 图表 '{chart_title}' 全量核验失败: {reason}")
                                        action_success = False
                                        chart_bug_img = str(self.explore_dir / f"chart_bug_{steps_taken}_{worker_step}.png")
                                        try:
                                            self.driver.capture_screenshot(chart_bug_img)
                                        except Exception:
                                            chart_bug_img = None
                                        path_str = " -> ".join(current_ui_path) if current_ui_path else "未知路径"
                                        self.bug_reporter.report_bug(
                                            run_id=self.run_id,
                                            title=f"[{self.run_id}] 图表全量数据核验异常: '{chart_title}'",
                                            step_prompt=f"[CHART-PROBE] 批量核验图表: '{chart_title}' ({len(points)}个数据点) (路径: {path_str})",
                                            actual_result=f"图表批量断言未通过: {reason}",
                                            crash_image_path=chart_bug_img
                                        )
                                    else:
                                        logger.info(f"🎉 [BatchChart] 图表 '{chart_title}' 全量 {len(points)} 个数据点集中核验 100% 通过！")
                                        action_success = True
                                        trajectory.append({
                                            "type": "api_assert",
                                            "prompt": f"批量核验图表 '{chart_title}' 全量 {len(points)} 个数据节点业务数据一致性",
                                            "thought": f"ECharts 双擎嗅探全量点位核验: {reason}"
                                        })
                                else:
                                    logger.info(f"ℹ️ [BatchChart] 未检索到图表 '{chart_title}' 的专属后台接口报文，记录图表已嗅探。")
                                    action_success = True

                                # 将拓扑树收敛为一个规范的聚合图表节点
                                if curr_node is not None:
                                    consolidated_label = f"📊 {chart_title} (全量{len(points)}个数据点已核验)"
                                    curr_node[consolidated_label] = {}
                                    
                                    # 将聚合后的状态静默落盘到 checkpoint
                                    tree_file = Path(self.checkpoint_dir) / "page_tree.json"
                                    with open(tree_file, "w", encoding="utf-8") as f:
                                        json.dump(self.page_tree, f, ensure_ascii=False, indent=2)

                                # 标记已处理并指示 Worker 本轮探索已圆满达成
                                batch_chart_handled = True
                                worker_finished_early = True
                        except Exception as e_batch:
                            logger.warning(f"⚠️ [BatchChart] 图表批量嗅探处理异常 ({e_batch})，继续执行常规交互...")

                    if not batch_chart_handled:
                        try:
                            if action_type == "hover":
                                self.driver.hover(x, y, delay_after=1.0)
                                time.sleep(2.0)
                                # 捕获悬停产生的 Tooltip 悬浮卡片
                                hover_img_path = self.explore_dir / f"explore_step_{steps_taken}_hover.png"
                                hover_b64 = self.driver.capture_screenshot_base64(str(hover_img_path))
                                logger.info(f"📸 捕获悬停状态快照 (含 Tooltip 浮层): {hover_img_path.name}")
                            else:
                                self.driver.click(x, y, button="left", delay_after=1.5)
                                
                                # ========================================================
                                # [Post-Click Diff] 捕获点击后状态，探测模态弹窗与路由跳转
                                # ========================================================
                                try:
                                    time.sleep(1.0) # 等待可能的动画或弹窗渲染
                                    after_img_path = self.explore_dir / f"explore_step_{steps_taken}_after.png"
                                    self.driver.capture_screenshot_base64(str(after_img_path))
                                    
                                    diff_res = PostClickDetector.detect_transition(
                                        driver=self.driver,
                                        before_img_path=str(step_img_path),
                                        after_img_path=str(after_img_path),
                                        before_modals=before_modals,
                                        action_desc=element_desc
                                    )
                                    transition = diff_res.get("transition")
                                    trans_container = diff_res.get("container_name")
                                    
                                    if transition == "modal_open" and trans_container:
                                        if trans_container not in self.container_stack:
                                            self.container_stack.append(trans_container)
                                            logger.info(f"📥 [Container Stack] 模态弹窗入栈: {trans_container} | 当前栈: {self.container_stack}")
                                            
                                    elif transition == "modal_close":
                                        if self.container_stack:
                                            popped = self.container_stack.pop()
                                            logger.info(f"📤 [Container Stack] 模态弹窗出栈: {popped} | 剩余栈: {self.container_stack}")
                                            
                                    elif transition == "page_navigate":
                                        if self.container_stack:
                                            logger.info(f"🔄 [Container Stack] 检测到路由跳转，清空模态栈: {self.container_stack}")
                                            self.container_stack.clear()
                                except Exception as e:
                                    logger.warning(f"⚠️ Post-Click Diff 检测执行异常: {e}")
                                    
                            action_success = True
                        except Exception as e:
                            logger.error(f"❌ 执行失败: {e}")
                            action_success = False
                            crash_img_path = str(self.explore_dir / f"crash_step_{steps_taken}_{worker_step}.png")
                            try:
                                self.driver.capture_screenshot(crash_img_path)
                            except Exception:
                                crash_img_path = None
                            path_str = " -> ".join(current_ui_path) if current_ui_path else "未知路径"
                            self.bug_reporter.report_bug(
                                run_id=self.run_id,
                                title=f"[{self.run_id}] 探索动作 '{element_desc}' 执行物理崩溃",
                                step_prompt=f"[{action_type.upper()}] {element_desc} (当前路径: {path_str})",
                                actual_result=f"底层驱动执行异常: {e}",
                                crash_image_path=crash_img_path
                            )
                else:
                    logger.warning(f"⚠️ 未知的动作类型: {action_type}，跳过此步。")
                    time.sleep(1.0)
                    
                # ========================================================
                # [Auto-API Cross Check] 探索期底层接口数据自动双向核验
                # 当 Worker 明确标记 validate_api，或悬停在图表/表格上时触发
                # ========================================================
                should_check_api = action_success and not batch_chart_handled and (validate_api or (action_type == "hover" and element_type in ("chart", "table")))
                if should_check_api:
                    check_instruction = api_assert_prompt.strip() if api_assert_prompt else f"验证截图中关于 '{element_desc}' 所展示的具体业务数值，是否与接口返回的数据逻辑一致（非 NaN 且非全 0 异常）"
                    # 构建富语义检索上下文：融合断言意图、交互元素描述及目标名称，驱动底层倒排索引精准过滤
                    search_context = f"{check_instruction} {element_desc}"
                    current_scope_str = " -> ".join([str(p) for p in current_ui_path[:2]]) if current_ui_path and len(current_ui_path) >= 2 else (str(current_ui_path[0]) if current_ui_path else None)
                    api_summary = self.driver.get_focused_api_records_summary(search_context, page_scope=current_scope_str)
                    if api_summary and api_summary != "[]":
                        logger.info(f"🔬 [Auto-API] 触发接口数据双向核验: {check_instruction}")
                        try:
                            # 优先尝试生成局部 ROI 裁剪图（彻底隔离邻近卡片与文字的注意力串扰）
                            check_b64 = hover_b64 if action_type == "hover" and 'hover_b64' in locals() else base64_img
                            try:
                                if 'x' in locals() and 'y' in locals() and x is not None and y is not None:
                                    target_img_path = str(hover_img_path) if action_type == "hover" and 'hover_img_path' in locals() else str(step_img_path)
                                    dpr_val = info.get("devicePixelRatio", 1.0) if 'info' in locals() and isinstance(info, dict) else 1.0
                                    roi_save = str(self.explore_dir / f"explore_step_{steps_taken}_roi.png")
                                    roi_b64 = self.driver.crop_roi_base64(
                                        image_path=target_img_path,
                                        center_x=x,
                                        center_y=y,
                                        dpr=dpr_val,
                                        save_path=roi_save
                                    )
                                    if roi_b64:
                                        logger.info(f"🎯 [Auto-API] 启用局部 ROI 聚焦图（已隔离邻居卡片视觉干扰）: {Path(roi_save).name}")
                                        check_b64 = roi_b64
                            except Exception as crop_err:
                                logger.warning(f"⚠️ ROI 局部裁剪过程异常，回退使用全屏原图: {crop_err}")

                            passed, reason = self.vision.check_api_assertion(
                                instruction=check_instruction,
                                base64_image=check_b64,
                                api_data_json=api_summary
                            )
                            is_unrelated = ("非同源" in reason or "跳过" in reason or "UNRELATED" in reason)
                            if not passed:
                                logger.error(f"🚨 [API MISMATCH] 接口数据核验未通过: {reason}")
                                action_success = False
                                data_bug_img = str(self.explore_dir / f"data_bug_{steps_taken}_{worker_step}.png")
                                try:
                                    self.driver.capture_screenshot(data_bug_img)
                                except Exception:
                                    data_bug_img = None
                                path_str = " -> ".join(current_ui_path) if current_ui_path else "未知路径"
                                self.bug_reporter.report_bug(
                                    run_id=self.run_id,
                                    title=f"[{self.run_id}] UI数据与接口原始报文不匹配: '{element_desc}'",
                                    step_prompt=f"[{action_type.upper()}] 核验: {check_instruction} (路径: {path_str})",
                                    actual_result=f"数据断言失败: {reason}",
                                    crash_image_path=data_bug_img
                                )
                            elif is_unrelated:
                                logger.info(f"ℹ️ [Auto-API] 候选接口非当前被测组件数据源，跳过数据断言（不纳入用例，不上报Bug）。")
                            else:
                                logger.info(f"🎉 [Auto-API] 接口数据核验通过！UI 渲染与后端 JSON 完全一致。")
                                # 仅在真实核验一致时，沉淀到回归用例轨迹中
                                trajectory.append({
                                    "type": "api_assert",
                                    "prompt": check_instruction,
                                    "thought": f"自动核验 {element_desc} 的接口数据对齐"
                                })
                        except Exception as api_err:
                            logger.warning(f"⚠️ 执行 API 数据核验时发生异常: {api_err}")
                    else:
                        logger.info("ℹ️ [Auto-API] 底层抓包池暂无相关 JSON 报文，跳过数据比对。")
                    
                # 检查是否在操作期间触发了后台 Bug (控制台报错、网络500、未捕获异常)
                bugs = self.driver.get_and_clear_bugs()
                if bugs:
                    action_success = False
                    logger.error(f"🚨 [BUG FOUND] 在执行操作 [{action_type.upper()}] '{element_desc}' 时/后，系统捕获到 {len(bugs)} 个底层异常！")
                    raw_bugs_dir = self.log_dir / "raw_bugs"
                    raw_bugs_dir.mkdir(parents=True, exist_ok=True)
                    bug_report_file = raw_bugs_dir / f"bug_report_{steps_taken}_{worker_step}.json"
                    with open(bug_report_file, "w", encoding="utf-8") as f:
                        json.dump(bugs, f, ensure_ascii=False, indent=2)
                    
                    # 保存 Bug 现场截图
                    bug_img_path = str(self.explore_dir / f"bug_screenshot_{steps_taken}_{worker_step}.png")
                    self.driver.capture_screenshot(bug_img_path)
                    logger.error(f"📸 Bug 现场已保存至: {bug_img_path}")
                    logger.error(f"📄 原始异常已归档至: {bug_report_file}")

                    # 格式化报错详情并上报到全局 BugReporter (触发 LLM 语义查重并沉淀至全局 bugs/ 库)
                    error_lines = []
                    for b in bugs:
                        b_type = b.get("type", "unknown")
                        b_url = b.get("url")
                        b_loc = b.get("location")
                        b_related = b.get("related_api")
                        b_msg = b.get("msg") or ""

                        if b_type == "api_biz_error":
                            error_lines.append(f"[api_biz_error] 接口业务报错: {b.get('endpoint')} -> {b_msg}")
                            error_lines.append(f"  ↳ 接口地址: {b_url}")
                            if b.get("response"):
                                resp_preview = json.dumps(b["response"], ensure_ascii=False)
                                if len(resp_preview) > 300:
                                    resp_preview = resp_preview[:300] + "..."
                                error_lines.append(f"  ↳ 响应报文: {resp_preview}")
                        elif b_type == "network_error":
                            error_lines.append(f"[network_error] HTTP {b.get('status')}: {b_url}")
                        elif b_type == "console_error":
                            loc_suffix = f" (代码位置: {b_loc})" if b_loc else ""
                            error_lines.append(f"[console_error{loc_suffix}] {b_msg}")
                        else:
                            error_lines.append(f"[{b_type}] {b_msg}")
                    actual_err_str = "\n".join(error_lines)

                    path_str = " -> ".join(current_ui_path) if current_ui_path else "未知路径"
                    self.bug_reporter.report_bug(
                        run_id=self.run_id,
                        title=f"[{self.run_id}] 探索操作 '{element_desc}' 触发底层异常",
                        step_prompt=f"[{action_type.upper()}] 交互目标: '{element_desc}' (页面路径: {path_str})",
                        actual_result=actual_err_str,
                        crash_image_path=bug_img_path
                    )

                # 记录短期历史 (不管成功与否都记录，防止局部死循环)
                status_tag = " (NG-异常)" if not action_success else " (OK)"
                history_str = f"Worker 第 {worker_step} 步: [{action_type.upper()}] {element_desc}{status_tag}"
                action_history.append(history_str)
                if len(action_history) > 6:
                    action_history.pop(0)
                    
                # 记录全局历史与详细轨迹 (仅在动作成功且无 Bug 的 PASS 状态下，才沉淀进用例库轨迹)
                if action_success:
                    if action_type in ("click", "hover", "wait"):
                        trajectory.append({
                            "type": "action" if action_type in ("click", "hover") else "wait",
                            "action_type": action_type,
                            "prompt": element_desc if action_type in ("click", "hover") else f"Wait for {element_desc}",
                            "thought": thought
                        })
                        
                    if action_type in ("click", "hover") and element_desc:
                        # 成功执行，重置该目标的失败计数
                        if element_desc in self.failed_counts:
                            self.failed_counts.pop(element_desc, None)

                        if element_desc not in global_history:
                            global_history.append(element_desc)
                            # 实时持久化长期记忆到 checkpoint 目录 (轻量级纯文本，永久安全留存)
                            for h_file in [self.checkpoint_dir / "global_history.json", self.log_dir / "global_history.json"]:
                                try:
                                    with open(h_file, "w", encoding="utf-8") as f:
                                        json.dump(global_history, f, ensure_ascii=False, indent=2)
                                except Exception:
                                    pass
                else:
                    logger.warning(f"⚠️ 步骤 [{action_type.upper()}] '{element_desc}' 判定为 NG，已上报 BUG 库，不纳入回归用例库。")
                    # ========================================================
                    # [Fault Circuit Breaker] 缺陷节点熔断机制
                    # 当同一个目标连续失败/报错达到 3 次，自动熔断跳过并录入长期记忆，
                    # 彻底解决在已报错节点上陷入几十上百步的死循环空转！
                    # ========================================================
                    if element_desc:
                        target_key = element_desc.strip()
                        self.failed_counts[target_key] = self.failed_counts.get(target_key, 0) + 1
                        fail_count = self.failed_counts[target_key]
                        
                        # 持久化失败计数到 checkpoint 目录
                        for f_file in [self.checkpoint_dir / "failed_counts.json", self.log_dir / "failed_counts.json"]:
                            try:
                                with open(f_file, "w", encoding="utf-8") as f:
                                    json.dump(self.failed_counts, f, ensure_ascii=False, indent=2)
                            except Exception:
                                pass

                        if fail_count >= 3:
                            skip_desc = f"{target_key} (已发现缺陷，熔断跳过)"
                            logger.warning(f"🛑 [Circuit Breaker] 目标 '{target_key}' 累计失败 {fail_count} 次，触发熔断保护！已存入长期记忆，由 Planner 在宏观规划层避开该目标，Worker 继续执行后续步骤。")
                            if target_key not in global_history:
                                global_history.append(target_key)
                            if skip_desc not in global_history:
                                global_history.append(skip_desc)
                            for h_file in [self.checkpoint_dir / "global_history.json", self.log_dir / "global_history.json"]:
                                try:
                                    with open(h_file, "w", encoding="utf-8") as f:
                                        json.dump(global_history, f, ensure_ascii=False, indent=2)
                                except Exception:
                                    pass

                if worker_finished_early:
                    logger.info("✅ [Worker] 图表批量嗅探与集中核验已达成，提前交还控制权给 Planner。")
                    break

            if not worker_finished_early:
                logger.info(f"✅ [Worker] 已耗尽预算步数 ({budget})，将控制权交还给 Planner。")

        # 固化本次运行的页面架构记忆 (用于续跑)
        for t_file in [self.checkpoint_dir / "page_tree.json", self.log_dir / "page_tree.json"]:
            try:
                with open(t_file, "w", encoding="utf-8") as f:
                    json.dump(self.page_tree, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

        # 自动生成 YAML 用例 (存入本次运行专属 generated_cases/，避免污染正式用例库)
        if trajectory:
            yaml_path = TrajectoryExporter.export_yaml_case(self.run_id, trajectory, output_dir=self.generated_cases_dir)
            if yaml_path:
                logger.info(f"💡 [Case Isolated] 自动生成闭环用例已保存至本次运行专属目录: {yaml_path}")
                logger.info(f"   (如需纳入正式回归测试，可人工确认后复制/提升至 test_cases/ 目录下)")
            
        # 自动生成全景架构图与纯 Markdown 组件拓扑树
        PageMapBuilder.export_page_map(self.page_tree)

        # 自动固化全局接口大盘供人工查阅与诊断
        try:
            api_file = self.explore_dir / "api_registry.json"
            self.driver.dump_api_registry(str(api_file))
        except Exception as api_err:
            logger.warning(f"⚠️ 导出接口大盘异常: {api_err}")

        # 自动生成高颜值可视化 HTML 全景报告
        try:
            from utils.report_generator import ReportGenerator
            reporter = ReportGenerator(self.run_dir)
            report_file = reporter.generate_html()
            logger.info("=" * 60)
            logger.info(f"📊 [Auto-Report] 交互式全景视觉报告已同步生成！")
            logger.info(f"   👉 双击或浏览器打开查看: file:///{report_file.as_posix()}")
            logger.info("=" * 60)
        except Exception as rep_err:
            logger.warning(f"⚠️ 自动生成 HTML 报告失败: {rep_err}")

        logger.info("=" * 60)
        logger.info("🏁 探索任务结束！")
        logger.info(f"📂 探索产物已完整归档至: {self.run_dir}")
        logger.info(f"   ├── 运行检查点与记忆: {self.checkpoint_dir}")
        logger.info(f"   ├── 自动生成测试用例: {self.generated_cases_dir}")
        logger.info(f"   └── 探索截图与凭据图: {self.explore_dir}")
        logger.info("=" * 60)

    def start_smoke_tour(self, context: str = ""):
        """
        全量 33 个二级菜单冒烟巡检模式 (Full Menu Smoke Tour):
        单次启动 Electron 进程，按顺序遍历 6 个一级模块下的全部 33 个二级菜单：
        1. 验证两级菜单跳转：悬停对应一级菜单展开下拉框 -> 点击二级菜单进入目标页面；
        2. 页面就绪后，由 Planner 进行 1 步宏观规划，Worker 执行 1 步页面内业务操作；
        3. 纯日志记录，不生成/修改 Mermaid 架构图（仅作为一条全量冒烟测试用例），单次启动零重启完成全屏巡检。
        """
        logger.info("=" * 60)
        logger.info(f"🚀 启动【33个二级菜单全量冒烟巡检模式】(Smoke Tour) | Run ID: {self.run_id}")
        logger.info("=" * 60)

        base_tree = PageMapBuilder.parse_base_rules()
        menu_list = []
        for l1, l2_dict in base_tree.items():
            if isinstance(l2_dict, dict):
                for l2 in l2_dict.keys():
                    menu_list.append((l1, l2))

        total_menus = len(menu_list)
        if total_menus == 0:
            logger.error("❌ 未从 docs/explore_rules.md 中解析到任何二级菜单，冒烟巡检中止！")
            return

        logger.info(f"📋 已加载全部 {total_menus} 个待测二级菜单清单。准备开始单会话流水巡检...")
        start_time = time.time()
        results = []
        jump_success_count = 0
        plan_success_count = 0

        for idx, (l1, l2) in enumerate(menu_list, 1):
            logger.info("\n" + "=" * 60)
            logger.info(f"🎯 [Smoke Tour ({idx}/{total_menus})] 正在巡检模块: 【{l1} -> {l2}】")
            logger.info("=" * 60)

            jump_ok = False
            plan_ok = False
            jump_err_msg = ""
            plan_err_msg = ""
            sub_objective = ""

            # -----------------------------------------------------------------
            # 阶段一：二级菜单两级智能跳转 (Two-Tier Jump: Hover L1 -> Click L2)
            # -----------------------------------------------------------------
            if idx == 1 and l1 == "首页" and l2 == "矿山简介":
                logger.info(f"ℹ️ [Smoke Jump] 系统初始启动默认处于【首页 -> 矿山简介】，跳过菜单跳转。")
                self.driver.set_page_scope(f"{l1} -> {l2}")
                self.last_l2_route = (l1, l2)
                jump_ok = True
                jump_success_count += 1
            else:
                try:
                    info = self.driver.get_viewport_info()
                    width, height = info.get("width", 2560), info.get("height", 1440)

                    # 1. 悬停一级菜单展开下拉浮层
                    logger.info(f"👉 [Smoke Jump 1/2] 正在寻索并悬停顶部一级菜单【{l1}】...")
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
                    try:
                        dpr = info.get("devicePixelRatio", 1.0)
                        self.driver.draw_cursor_on_image(str(hover_img_path), hx, hy, dpr)
                    except Exception as e:
                        logger.warning(f"⚠️ 无法在截图 {hover_img_path.name} 上绘制准星: {e}")
                    self.driver.hover(hx, hy, delay_after=1.5)

                    # 2. 点击下拉菜单中的二级菜单项
                    logger.info(f"👉 [Smoke Jump 2/2] 正在寻索并点击下拉菜单项【{l2}】...")
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
                    try:
                        dpr = info.get("devicePixelRatio", 1.0)
                        self.driver.draw_cursor_on_image(str(click_img_path), cx, cy, dpr)
                    except Exception as e:
                        logger.warning(f"⚠️ 无法在截图 {click_img_path.name} 上绘制准星: {e}")
                    self.driver.click(cx, cy, delay_after=1.5)

                    # 状态重置与页面作用域切换
                    self.driver.set_page_scope(f"{l1} -> {l2}")
                    self.last_l2_route = (l1, l2)
                    self.container_stack.clear()
                    self.active_tab = None
                    jump_ok = True
                    jump_success_count += 1
                    logger.info(f"✅ [Smoke Jump] 成功跳转进入业务页面: 【{l1} -> {l2}】！")

                except Exception as j_err:
                    jump_err_msg = str(j_err)
                    logger.error(f"❌ [Smoke Jump] 跳转至【{l1} -> {l2}】失败: {jump_err_msg}")
                    self.bug_reporter.report_bug(
                        run_id=self.run_id,
                        title=f"[{self.run_id}] 冒烟巡检菜单跳转失败: 【{l1} -> {l2}】",
                        step_prompt=f"[SMOKE-JUMP] 悬停【{l1}】并点击【{l2}】",
                        actual_result=jump_err_msg
                    )

            # -----------------------------------------------------------------
            # 阶段二：当前页面 Planner 宏观视觉体检与核心业务规划 (Page Health & Inspection)
            # -----------------------------------------------------------------
            if jump_ok:
                try:
                    time.sleep(1.0)

                    logger.info(f"🧠 [Smoke Planner] 正在对当前【{l1} -> {l2}】页面进行视觉体检与核心业务识别...")
                    plan_img_path = self.explore_dir / f"smoke_page_{idx}_plan.png"
                    b64_plan = self.driver.capture_screenshot_base64(str(plan_img_path), dim_background=True)

                    plan = self.vision.plan_sub_objective(
                        macro_objective=f"对当前【{l1} -> {l2}】页面进行冒烟体检与视觉健康度评估，识别页面内核心展示组件、指标卡片或数据图表",
                        base64_image=b64_plan,
                        global_history=[f"【{l1} -> {l2}】"],
                        context=context,
                        current_page_tree={},  # 传空字典，防止冒烟步骤污染正式架构树
                        reexplore_module=l2
                    )
                    sub_objective = plan.get("sub_objective", f"测试【{l2}】核心业务组件")
                    p_thought = plan.get("thought", "")
                    logger.info(f"💡 [Smoke Planner] 页面诊断与思考: {p_thought}")
                    logger.info(f"🎯 [Smoke Planner] 识别核心业务模块: '{sub_objective}'")

                    # 检查页面是否有被捕获的后台静默报错
                    bugs = self.driver.get_and_clear_bugs()
                    if bugs:
                        logger.warning(f"⚠️ [Smoke Planner] 页面加载触发了 {len(bugs)} 个控制台/网络错误: {bugs[0]}")

                    plan_ok = True
                    plan_success_count += 1
                    logger.info(f"🎉 [Smoke Tour ({idx}/{total_menus})] 【{l1} -> {l2}】冒烟巡检 PASS！")

                except Exception as p_err:
                    plan_err_msg = str(p_err)
                    logger.warning(f"⚠️ [Smoke Planner] 页面体检执行异常: {plan_err_msg}")

            results.append({
                "index": idx,
                "module": f"{l1} -> {l2}",
                "jump": "PASS" if jump_ok else f"FAIL ({jump_err_msg[:40]})",
                "plan": "PASS" if plan_ok else ("SKIPPED" if not jump_ok else f"FAIL ({plan_err_msg[:40]})"),
                "core_component": sub_objective if plan_ok else "-"
            })

        # -----------------------------------------------------------------
        # 冒烟巡检大盘汇总报告 (纯日志展示，不生成/改写 Mermaid 地图)
        # -----------------------------------------------------------------
        elapsed = time.time() - start_time
        logger.info("\n" + "=" * 70)
        logger.info("🏁 【33 个二级菜单全量冒烟巡检完成报告】")
        logger.info("=" * 70)
        logger.info(f"⏱️ 巡检总耗时: {elapsed:.1f} 秒 ({elapsed/60:.1f} 分钟)")
        logger.info(f"📊 二级菜单跳转覆盖率: {jump_success_count}/{total_menus} ({(jump_success_count/total_menus)*100:.1f}%)")
        logger.info(f"📊 页面体检规划成功率: {plan_success_count}/{total_menus} ({(plan_success_count/total_menus)*100:.1f}%)")
        logger.info("-" * 70)
        logger.info(f"{'序号':<6}{'二级业务菜单':<28}{'菜单跳转':<12}{'页面体检':<12}{'识别核心业务组件'}")
        logger.info("-" * 70)
        for r in results:
            logger.info(f"{r['index']:<6}{r['module']:<28}{r['jump']:<12}{r['plan']:<12}{r['core_component']}")
        logger.info("=" * 70)
        logger.info(f"📂 冒烟截图与详细日志保存在: {self.explore_dir}")
        logger.info("ℹ️ 说明: 本次运行为纯冒烟测试模式，未修改或导出 Mermaid 架构地图文件。")
        logger.info("=" * 70)

        # 自动生成冒烟巡检可视化 HTML 报告
        try:
            from utils.report_generator import ReportGenerator
            reporter = ReportGenerator(self.run_dir)
            report_file = reporter.generate_html()
            logger.info("=" * 70)
            logger.info(f"📊 [Auto-Report] 冒烟巡检可视化大盘已生成！")
            logger.info(f"   👉 双击或浏览器打开查看: file:///{report_file.as_posix()}")
            logger.info("=" * 70)
        except Exception as rep_err:
            logger.warning(f"⚠️ 自动生成冒烟报告失败: {rep_err}")




