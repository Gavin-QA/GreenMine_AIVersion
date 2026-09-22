import time
import logging
import json
import re
from pathlib import Path
from typing import Optional

from core.browser import ElectronDriver
from core.vision.agent import VisionAgent
from core.bug_reporter import BugReporter
from utils.artifacts import report_run_id, LOGS_DIR
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
        
        # 记录探索日志的目录
        self.log_dir = LOGS_DIR / self.run_id
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # 统一归档：截图存放在 logs/<run_id>/screenshots 目录下
        self.explore_dir = self.log_dir / "screenshots"
        self.explore_dir.mkdir(parents=True, exist_ok=True)
        
        # 初始化动态架构树与容器调用栈
        self.page_tree = PageMapBuilder.parse_base_rules()
        self.container_stack = []

    def start_exploration(self, objective: str, max_steps: int = 20, context: str = "", resume_from: Optional[str] = None):
        """
        开启自主探索循环
        :param objective: 宏观探索目标
        :param max_steps: 最大探索步数
        :param context: 注入的项目背景知识或探索规则
        :param resume_from: 续跑目录 (如 'logs/explore_xxx')
        """
        logger.info("=" * 60)
        logger.info(f"🚀 开启自主探索模式 | 目标: {objective}")
        if context:
            logger.info(f"📚 已加载探索先验知识: {len(context)} 字符")
        logger.info(f"🛑 最大步数限制: {max_steps} | Run ID: {self.run_id}")
        logger.info("=" * 60)

        steps_taken = 0
        global_history = []
        trajectory = [] # 用于记录闭环转化生成的完整轨迹
        
        if resume_from:
            resume_path = Path(resume_from)
            logger.info(f"♻️ 正在从 {resume_path} 恢复历史记忆...")
            
            history_file = resume_path / "global_history.json"
            if history_file.exists():
                try:
                    with open(history_file, "r", encoding="utf-8") as f:
                        global_history = json.load(f)
                    logger.info(f"✅ 成功恢复 global_history，包含 {len(global_history)} 条记忆。")
                except Exception as e:
                    logger.error(f"恢复 global_history 失败: {e}")
                    
            tree_file = resume_path / "page_tree.json"
            if tree_file.exists():
                try:
                    with open(tree_file, "r", encoding="utf-8") as f:
                        self.page_tree = json.load(f)
                    logger.info(f"✅ 成功恢复 page_tree 架构树。")
                except Exception as e:
                    logger.error(f"恢复 page_tree 失败: {e}")

        while steps_taken < max_steps:
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
                    current_page_tree=self.page_tree
                )
                
                sub_objective = plan.get("sub_objective", "无子目标")
                thought = plan.get("thought", "")
                budget = int(plan.get("allocated_steps", 8))
                focus_region = plan.get("focus_region")
                
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
                        current_page_tree=self.page_tree
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
                current_ui_path = decision.get("current_ui_path", [])
                element_type = decision.get("element_type", "other")
                container_name = decision.get("container_name")
                validate_api = decision.get("validate_api", False)
                api_assert_prompt = decision.get("api_assert_prompt", "")
                
                logger.info(f"💡 [Worker] 思考链: {thought}")
                logger.info(f"📍 [Worker] 当前推断路径: {current_ui_path} | 类型: {element_type} | 容器: {container_name}")
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
                
                clean_target = element_desc.replace("按钮", "").replace("选项", "").replace("菜单", "").strip("‘’'\"“” ")
                
                # 判定是否属于切换菜单的全局路由动作 (如 hover 顶部导航栏的一级菜单，或 click 下拉菜单项)
                is_nav_interaction = (
                    any(k in element_desc for k in nav_noise_keywords) or
                    any(k in (container_name or "") for k in nav_noise_keywords) or
                    clean_target in base_l1_names or
                    clean_target in base_l2_all
                )
                
                # 若点击了二级菜单项，作为全局路由跃迁，清空模态调用栈
                if action_type == "click" and clean_target in base_l2_all:
                    for l1, l2_dict in self.page_tree.items():
                        if clean_target in l2_dict:
                            logger.info(f"🧭 [Navigation] 检测到全局路由跃迁: 前往 [{l1} -> {clean_target}]")
                            self.container_stack.clear()
                            break

                # 仅当不是全局导航交互时，才将该元素作为业务组件挂载到当前页面分支下
                if not is_nav_interaction and current_ui_path and isinstance(current_ui_path, list):
                    # 清洗路径，剔除可能混入的导航冗余词或跨模块一级菜单
                    clean_path = [p for p in current_ui_path if not any(k in p for k in nav_noise_keywords)]
                    if len(clean_path) > 1 and clean_path[1] in base_l1_names:
                        # 避免如 ["首页", "生产管理"] 的错误跨级嵌套，纠正为主干模块
                        clean_path = [clean_path[1]] + clean_path[2:]
                        
                    effective_path = list(clean_path)
                    
                    # 补充局部容器上下文 (排除导航噪音)
                    if container_name and not any(k in container_name for k in nav_noise_keywords) and container_name not in effective_path and container_name not in self.container_stack:
                        effective_path.append(container_name)
                        
                    # 补充当前活跃的模态弹窗调用栈
                    for modal in self.container_stack:
                        if modal not in effective_path:
                            effective_path.append(modal)
                            
                    curr_node = self.page_tree
                    for path_node in effective_path:
                        if path_node not in curr_node:
                            curr_node[path_node] = {}
                        curr_node = curr_node[path_node]
                        
                    # 将即将操作的元素作为叶子节点挂载 (附带 Emoji)
                    if element_desc and action_type != "finish":
                        leaf_name = PageMapBuilder.format_node_label(element_desc)
                        if leaf_name not in curr_node:
                            curr_node[leaf_name] = {}
                            
                    # 实时持久化树与导出纯 Markdown 树状图
                    tree_file = self.log_dir / "page_tree.json"
                    with open(tree_file, "w", encoding="utf-8") as f:
                        json.dump(self.page_tree, f, ensure_ascii=False, indent=2)
                        
                    PageMapBuilder.export_page_map(self.page_tree)

                logger.info(f"🤖 [Worker] 决定: [{action_type.upper()}] -> 目标: {element_desc}")

                action_success = False

                # 4. 执行决策
                if action_type == "finish":
                    logger.info("✅ [Worker] 判断当前子任务已完成，或无更多可探索内容，提前汇报给 Planner。")
                    worker_finished_early = True
                    break
                    
                elif action_type == "wait":
                    logger.info("⏳ [Worker] 决定停留观察 3 秒...")
                    time.sleep(3.0)
                    action_success = True
                    
                elif action_type in ("click", "hover"):
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
                should_check_api = action_success and (validate_api or (action_type == "hover" and element_type in ("chart", "table")))
                if should_check_api:
                    api_summary = self.driver.get_api_records_summary()
                    if api_summary and api_summary != "[]":
                        check_instruction = api_assert_prompt.strip() if api_assert_prompt else f"验证截图中关于 '{element_desc}' 所展示的具体业务数值，是否与接口返回的数据逻辑一致（非 NaN 且非全 0 异常）"
                        logger.info(f"🔬 [Auto-API] 触发接口数据双向核验: {check_instruction}")
                        try:
                            check_b64 = hover_b64 if action_type == "hover" and 'hover_b64' in locals() else base64_img
                            passed, reason = self.vision.check_api_assertion(
                                instruction=check_instruction,
                                base64_image=check_b64,
                                api_data_json=api_summary
                            )
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
                            else:
                                logger.info(f"🎉 [Auto-API] 接口数据核验通过！UI 渲染与后端 JSON 完全一致。")
                                # 沉淀到回归用例轨迹中
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
                    bug_report_file = self.log_dir / f"bug_report_{steps_taken}_{worker_step}.json"
                    with open(bug_report_file, "w", encoding="utf-8") as f:
                        json.dump(bugs, f, ensure_ascii=False, indent=2)
                    
                    # 保存 Bug 现场截图
                    bug_img_path = str(self.explore_dir / f"bug_screenshot_{steps_taken}_{worker_step}.png")
                    self.driver.capture_screenshot(bug_img_path)
                    logger.error(f"📸 Bug 现场已保存至: {bug_img_path}")
                    logger.error(f"📄 Bug 报告已存至: {bug_report_file}")

                    # 格式化报错详情并上报到全局 BugReporter (触发 LLM 语义查重并沉淀至全局 bugs/ 库)
                    error_lines = []
                    for b in bugs:
                        b_type = b.get("type", "unknown")
                        b_msg = b.get("msg") or f"{b.get('url')} (Status: {b.get('status')})"
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
                        
                    if action_type in ("click", "hover") and element_desc not in global_history:
                        global_history.append(element_desc)
                        # 实时持久化长期记忆到本地日志目录
                        history_file = self.log_dir / "global_history.json"
                        with open(history_file, "w", encoding="utf-8") as f:
                            json.dump(global_history, f, ensure_ascii=False, indent=2)
                else:
                    logger.warning(f"⚠️ 步骤 [{action_type.upper()}] '{element_desc}' 判定为 NG，已上报 BUG 库，不纳入回归用例库。")

            if not worker_finished_early:
                logger.info(f"✅ [Worker] 已耗尽预算步数 ({budget})，将控制权交还给 Planner。")

        # 自动生成 YAML 用例
        if trajectory:
            TrajectoryExporter.export_yaml_case(self.run_id, trajectory)
            
        # 自动生成全景架构图与纯 Markdown 组件拓扑树
        PageMapBuilder.export_page_map(self.page_tree)

        logger.info("=" * 60)
        logger.info("🏁 探索任务结束！")
        logger.info(f"📂 探索产生的截图和日志已保存至: {self.explore_dir}")
        logger.info("=" * 60)


