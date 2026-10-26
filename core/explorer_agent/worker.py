"""
core/explorer_agent/worker.py —— 单兵战术执行器 (ExplorerWorker)
==============================================================================
职责：
1. 接收 Planner 下达的子任务 (sub_objective) 与步数预算 (budget) 并执行微观战术探索；
2. 调度 Hybrid DOM + 纯视觉双擎定位，物理点击/悬停并绘制准星；
3. 驱动 ECharts / Canvas 双擎探针与通用亲和度守卫进行时序核验；
4. 状态机差分驱动：模态弹窗出入栈、一键隐藏/展示与迈灵助手开关追踪；
5. Auto-API 接口数据双向核验与底层崩溃缺陷隔离归档。
"""

from __future__ import annotations

import json
import logging
import math
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageChops

from .guards import ExplorerGuards
from .post_click_diff import PostClickDetector

logger = logging.getLogger("explorer_agent.worker")


class ExplorerWorker:
    """自主探索战术执行单兵"""

    def __init__(
        self,
        driver: Any,
        vision: Any,
        bug_reporter: Any,
        explore_dir: Path,
        log_dir: Path,
        checkpoint_dir: Path,
        run_id: str
    ):
        self.driver = driver
        self.vision = vision
        self.bug_reporter = bug_reporter
        self.explore_dir = Path(explore_dir)
        self.log_dir = Path(log_dir)
        self.checkpoint_dir = Path(checkpoint_dir)
        self.run_id = run_id

        # 图表全量嗅探缓存
        self.chart_data_buffer: Dict[str, Any] = {}

    def run_sub_task(
        self,
        sub_objective: str,
        budget: int,
        context: str,
        global_history: List[str],
        page_tree: Dict[str, Any],
        reexplore_module: Optional[str] = None,
        container_stack: Optional[List[str]] = None,
        is_panel_hidden: bool = False,
        mailing_dialog_open: bool = False,
        last_l2_route: Optional[Tuple[str, str]] = None,
        start_step: int = 0,
        max_steps: int = 2000,
        current_path: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        执行单次分配的子任务战术循环。
        返回包含步骤消耗数、状态更新、新增轨迹等的字典。
        """
        container_stack = container_stack if container_stack is not None else []
        action_history: List[Dict[str, Any]] = []
        task_trajectory: List[Dict[str, Any]] = []
        steps_used = 0
        current_step = start_step

        last_action_record: Optional[Dict[str, Any]] = None
        tested_targets_in_scope = set()
        consecutive_redundant_count = 0

        for worker_step in range(1, budget + 1):
            if current_step >= max_steps:
                break

            current_step += 1
            steps_used += 1
            logger.info(f"\n--- [Worker Step {worker_step}/{budget}] (Global: {current_step}/{max_steps}) ---")

            # 1. 截图并获取 Base64
            step_img_path = self.explore_dir / f"explore_step_{current_step}.png"
            try:
                base64_img = self.driver.capture_screenshot_base64(str(step_img_path))
                logger.info(f"📸 捕获环境快照: {step_img_path.name} (全屏)")
            except Exception as e:
                logger.error(f"❌ Worker 截图失败，中止当前任务: {e}")
                break

            info = self.driver.get_viewport_info()
            width = info.get("width", 2560)
            height = info.get("height", 1440)

            # 2. Worker 思考与战术决策
            try:
                worker_context = context
                if is_panel_hidden:
                    worker_context += "\n⚠️【极度紧急：大屏处于一键隐藏状态】当前页面 2D 业务面板已被收起/隐藏！下一步必须且只能执行：点击右上角【一键展开/一键显示】按钮（含 << 图标，如 class_foldBarRightunfold）恢复大屏面板显示！\n"
                if mailing_dialog_open or any("迈灵" in m for m in container_stack):
                    worker_context += "\n⚠️【极度紧急：【迈灵】助手对话弹窗处于打开状态】当前屏幕底部悬浮着【迈灵】AI助手对话窗！下一步必须立即将其关闭：直接再次点击顶部状态栏右上角的【迈灵】圆形功能按钮！绝对严禁在屏幕极右上角盲找或点击关闭叉号（极易误触系统退出按钮）！\n"

                decision = self.vision.execute_sub_objective(
                    sub_objective=sub_objective,
                    base64_image=base64_img,
                    context=worker_context,
                    history=action_history,
                    global_history=global_history,
                    current_page_tree=page_tree,
                    reexplore_module=reexplore_module,
                    container_stack=container_stack
                )
            except Exception as e:
                logger.error(f"❌ Worker 决策失败: {e}")
                logger.info("⏳ Worker 休息 5 秒...")
                time.sleep(5.0)
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

            # 3. 路由跨页检测与状态隔离
            if current_ui_path and len(current_ui_path) >= 2:
                current_l2 = (str(current_ui_path[0]), str(current_ui_path[1]))
                if last_l2_route is not None and current_l2 != last_l2_route:
                    logger.info(f"🧭 [Navigation] 跨二级页面路由跃迁: {last_l2_route} -> {current_l2}，重置容器栈与状态！")
                    container_stack.clear()
                    is_panel_hidden = False
                    mailing_dialog_open = False
                last_l2_route = current_l2
                self.driver.set_page_scope(f"{current_ui_path[0]} -> {current_ui_path[1]}")
            elif current_ui_path and len(current_ui_path) == 1:
                self.driver.set_page_scope(current_ui_path[0])

            if action_type == "finish":
                logger.info(f"🤖 [Worker] 决定: [FINISH] -> 目标: {element_desc or '子任务达成'}")
                logger.info("🏁 [Worker] 判定当前子任务已圆满达成，交还控制权给 Planner。")
                break

            action_success = False
            batch_chart_handled = False
            worker_finished_early = False

            logger.info(f"🤖 [Worker] 决定: [{action_type.upper()}] -> 目标: {element_desc or '无明确目标'}")

            if action_type == "wait":
                wait_sec = 2.0
                logger.info(f"⏳ [Worker] 执行智能等待 {wait_sec} 秒以待界面稳定或跳转完成...")
                time.sleep(wait_sec)
                action_success = True
            elif action_type == "back":
                logger.info("🔙 [Worker] 执行路由历史回退 (Back)...")
                self.driver.navigate_back()
                time.sleep(1.0)
                after_img_path = self.explore_dir / f"explore_step_{current_step}_after.png"
                self.driver.capture_screenshot_base64(str(after_img_path))
                logger.info(f"📸 捕获回退后快照: {after_img_path.name}")
                if container_stack:
                    popped = container_stack.pop()
                    logger.info(f"📤 [Container Stack] 回退动作使栈顶容器出栈: {popped}")
                action_success = True
            elif action_type == "reload":
                logger.info("🔄 [Worker] 执行页面刷新重置 (Reload)...")
                self.driver.reload_page()
                time.sleep(2.0)
                after_img_path = self.explore_dir / f"explore_step_{current_step}_after.png"
                self.driver.capture_screenshot_base64(str(after_img_path))
                logger.info(f"📸 捕获重载后快照: {after_img_path.name}")
                if container_stack:
                    container_stack.clear()
                    logger.info("🔄 [Container Stack] 页面重载，已重置清空弹窗栈")
                is_panel_hidden = False
                mailing_dialog_open = False
                action_success = True
            elif action_type in ("click", "hover", "input", "zoom", "rotate_3d", "scroll", "slide"):
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
                    logger.warning(f"⚠️ 精确定位失败 ({e})，尝试回退使用纯视觉坐标估算...")
                    x_pct = decision.get("x_percent")
                    y_pct = decision.get("y_percent")
                    if x_pct is None or y_pct is None:
                        if action_type in ("zoom", "rotate_3d", "scroll"):
                            x = width // 2
                            y = height // 2
                            logger.info(f"🌐 [Center Fallback] 未指定具体微观坐标，默认采用主视口中央: ({x}, {y})")
                        else:
                            logger.error(f"❌ Worker 亦未返回可用坐标，跳过此步。")
                            continue
                    else:
                        x = int(max(0, min(1, float(x_pct))) * width)
                        y = int(max(0, min(1, float(y_pct))) * height)
                        logger.info(f"🎯 使用纯视觉估算物理坐标: ({x}, {y})")

                # 在当步截图上绘制准星
                try:
                    dpr = info.get("devicePixelRatio", 1.0)
                    self.driver.draw_cursor_on_image(str(step_img_path), x, y, dpr)
                except Exception as e:
                    logger.warning(f"⚠️ 无法在截图 {step_img_path.name} 上绘制准星: {e}")

                # -------------------------------------------------------------
                # 🛡️ 防御 1: 差分状态感知防死循环熔断 (State-Diff Anti-Loop Fuse)
                # -------------------------------------------------------------
                is_stuck_loop = False
                if last_action_record is not None and x is not None and y is not None:
                    lx = last_action_record.get("x")
                    ly = last_action_record.get("y")
                    la = last_action_record.get("action")
                    ld = last_action_record.get("diff_ratio", 1.0)
                    if lx is not None and ly is not None:
                        dist = math.hypot(x - lx, y - ly)
                        # 判定条件：坐标极度重合 (< 25px) AND 同类型操作 AND 上一步执行后画面差分 < 1.0% (零状态响应)
                        if dist < 25 and action_type in ("click", "hover") and action_type == la and ld < 0.01:
                            is_stuck_loop = True

                if is_stuck_loop:
                    logger.warning(f"🛑 [Anti-Loop Fuse] 触发确定性防死循环熔断！目标坐标 ({x}, {y}) 连续执行 [{action_type.upper()}] 且无任何状态响应！")
                    logger.info("🏁 [Anti-Loop Fuse] 坚决拒绝原地空转打转，提前结束当前子任务交还控制权给 Planner！")
                    worker_finished_early = True
                    break

                # -------------------------------------------------------------
                # 🛡️ 防御 2: 页面饱和度动态退场 (Page Saturation Dynamic Exit Guard)
                # -------------------------------------------------------------
                norm_desc = re.sub(r'[\s\d_【】\(\)\[\]\-]+', '', element_desc).lower()
                if norm_desc and worker_step >= 3:
                    if norm_desc in tested_targets_in_scope:
                        consecutive_redundant_count += 1
                        if consecutive_redundant_count >= 2:
                            logger.info(f"🏁 [Saturation Guard] 当前页面核心交互已饱和 (连续重访已测元素: '{element_desc}')，优雅提前交还控制权！")
                            worker_finished_early = True
                            break
                    else:
                        consecutive_redundant_count = 0
                        tested_targets_in_scope.add(norm_desc)
                elif norm_desc:
                    tested_targets_in_scope.add(norm_desc)

                is_chart_target = (action_type not in ("zoom", "rotate_3d", "scroll", "slide", "input")) and ((element_type == "chart") or any(k in element_desc for k in ["折线图", "柱状图", "面积图", "数据拐点", "趋势图", "七天风量", "风量数据"]))

                # --- 分支 A: 图表全量批量嗅探引擎 ---
                if is_chart_target:
                    try:
                        probe_res = self.driver.probe_chart_all_points(x, y, chart_name=element_desc)
                        if probe_res.get("success") and probe_res.get("points"):
                            points = probe_res["points"]
                            chart_title = probe_res.get("chart_title") or element_desc
                            logger.info(f"📊 [BatchChart] 成功抓取图表 '{chart_title}' 全部 {len(points)} 个数据节点！准备执行集中接口核验...")

                            self.chart_data_buffer[chart_title] = {
                                "points": points,
                                "method": probe_res.get("method"),
                                "path": current_ui_path
                            }

                            # 1. 探针点位有效性卫语句 (排除 3D 占位态)
                            if not ExplorerGuards.is_valid_metric_chart(points):
                                logger.info(f"ℹ️ [BatchChart] 图表 '{chart_title}' 探针仅捕获到非业务占位数据 (如'默认视角')，处于3D/占位状态，跳过强行接口数据断言以防误判。")
                                action_success = True
                                task_trajectory.append({
                                    "type": "chart_probe_skip",
                                    "prompt": f"图表 '{chart_title}' 处于非时序占位态，免除数据核验",
                                    "thought": "组件当前呈现占位状态，无需触发错误警报"
                                })
                            else:
                                search_tokens = [chart_title]
                                if current_ui_path:
                                    search_tokens.extend([str(seg) for seg in current_ui_path if seg])
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
                                    # 2. 通用语义亲和度初筛卫语句 (防非同源与探针偏靶)
                                    has_affinity, metric_keys = ExplorerGuards.check_chart_api_affinity(points, api_summary)
                                    if not has_affinity:
                                        action_success = True
                                        task_trajectory.append({
                                            "type": "chart_probe_skip",
                                            "prompt": f"图表 '{chart_title}' 与候选接口非同源，免除误判",
                                            "thought": f"指标词 {metric_keys} 未在候选接口中出现，跳过比对"
                                        })
                                    else:
                                        passed, reason = self.vision.check_batch_chart_assertion(
                                            chart_name=chart_title,
                                            points=points,
                                            base64_image=base64_img,
                                            api_data_json=api_summary
                                        )
                                        if not passed:
                                            logger.error(f"🚨 [BATCH CHART MISMATCH] 图表 '{chart_title}' 全量核验失败: {reason}")
                                            action_success = False
                                            chart_bug_img = None
                                            if 'step_img_path' in locals() and step_img_path and Path(step_img_path).exists():
                                                chart_bug_img = str(step_img_path)
                                            else:
                                                chart_bug_img = str(self.explore_dir / f"chart_bug_{current_step}_{worker_step}.png")
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
                                            task_trajectory.append({
                                                "type": "api_assert",
                                                "prompt": f"批量核验图表 '{chart_title}' 全量 {len(points)} 个数据节点业务数据一致性",
                                                "thought": f"ECharts 双擎嗅探全量点位核验: {reason}"
                                            })
                                else:
                                    logger.info(f"ℹ️ [BatchChart] 未检索到图表 '{chart_title}' 的专属后台接口报文，记录图表已嗅探。")
                                    action_success = True

                            batch_chart_handled = True
                            worker_finished_early = True
                    except Exception as e_batch:
                        logger.warning(f"⚠️ [BatchChart] 图表批量嗅探处理异常 ({e_batch})，继续执行常规交互...")

                # --- 分支 B: 物理交互执行 (Hover / Click) ---
                if not batch_chart_handled:
                    try:
                        if hasattr(self.driver, "mark_action_timestamp"):
                            self.driver.mark_action_timestamp()

                        if action_type == "hover":
                            self.driver.hover(x, y, delay_after=1.0)
                            time.sleep(2.0)
                            hover_img_path = self.explore_dir / f"explore_step_{current_step}_hover.png"
                            hover_b64 = self.driver.capture_screenshot_base64(str(hover_img_path))
                            logger.info(f"📸 捕获悬停状态快照 (含 Tooltip 浮层): {hover_img_path.name}")
                            hover_diff_ratio = 0.0
                            try:
                                img_pre = Image.open(step_img_path).convert("L")
                                img_post = Image.open(hover_img_path).convert("L")
                                diff_chops = ImageChops.difference(img_pre, img_post)
                                hist = diff_chops.histogram()
                                hover_diff_ratio = sum(hist[25:]) / (img_pre.width * img_pre.height)
                            except Exception:
                                hover_diff_ratio = 0.05
                            last_action_record = {"x": x, "y": y, "action": action_type, "diff_ratio": hover_diff_ratio}
                        elif action_type == "zoom":
                            direction = decision.get("direction", "in")
                            steps = int(decision.get("steps", 3))
                            logger.info(f"🔭 [3D Zoom] 执行三维视点缩放: 方向={direction}, 步长={steps}, 视点坐标=({x}, {y})")
                            self.driver.zoom_3d(x, y, direction=direction, steps=steps, delay_after=1.5)
                            time.sleep(1.0)
                            after_img_path = self.explore_dir / f"explore_step_{current_step}_after.png"
                            after_b64 = self.driver.capture_screenshot_base64(str(after_img_path))
                            logger.info(f"📸 捕获 3D 缩放后快照: {after_img_path.name}")
                            # 3D 渲染健康度自检
                            try:
                                passed_3d, reason_3d = self.vision.assert_condition(
                                    instruction="检查当前画面在 3D 缩放后是否正常渲染三维矿山场景，没有出现模型破面、全粉色材质丢失、纯黑屏、或像素流断开崩溃报错遮罩",
                                    base64_image=after_b64
                                )
                                if not passed_3d:
                                    logger.error(f"🚨 [3D RENDER CRASH] 三维缩放后渲染健康度检测失败: {reason_3d}")
                                    path_str = " -> ".join(current_ui_path) if current_ui_path else "未知路径"
                                    self.bug_reporter.report_bug(
                                        run_id=self.run_id,
                                        title=f"[{self.run_id}] 3D空间缩放后渲染崩溃/材质异常: '{element_desc}'",
                                        step_prompt=f"[ZOOM] {direction} x {steps} (当前路径: {path_str})",
                                        actual_result=f"3D健康度检测未通过: {reason_3d}",
                                        crash_image_path=str(after_img_path),
                                        action_type="ZOOM",
                                        target_element=element_desc,
                                        global_step=current_step,
                                        severity="High",
                                        ui_path=path_str
                                    )
                                else:
                                    logger.info(f"🛡️ [3D Health] 三维缩放后画面健康度检测通过: {reason_3d}")
                            except Exception as e_3d:
                                logger.warning(f"⚠️ 3D 健康度自检异常: {e_3d}")
                        elif action_type == "rotate_3d":
                            direction = decision.get("direction", "left")
                            distance = int(decision.get("distance", 250))
                            logger.info(f"🌐 [3D Rotate] 执行三维视点旋转: 方向={direction}, 距离={distance}px, 旋转锚点=({x}, {y})")
                            self.driver.rotate_3d(center_x=x, center_y=y, direction=direction, distance=distance, button="right", delay_after=1.5)
                            time.sleep(1.0)
                            after_img_path = self.explore_dir / f"explore_step_{current_step}_after.png"
                            after_b64 = self.driver.capture_screenshot_base64(str(after_img_path))
                            logger.info(f"📸 捕获 3D 旋转后快照: {after_img_path.name}")
                            # 3D 渲染健康度自检
                            try:
                                passed_3d, reason_3d = self.vision.assert_condition(
                                    instruction="检查当前画面在 3D 视点旋转后是否正常渲染三维矿山场景，没有出现模型破面、全粉色材质丢失、纯黑屏、或像素流断开崩溃报错遮罩",
                                    base64_image=after_b64
                                )
                                if not passed_3d:
                                    logger.error(f"🚨 [3D RENDER CRASH] 三维旋转后渲染健康度检测失败: {reason_3d}")
                                    path_str = " -> ".join(current_ui_path) if current_ui_path else "未知路径"
                                    self.bug_reporter.report_bug(
                                        run_id=self.run_id,
                                        title=f"[{self.run_id}] 3D视点旋转后渲染崩溃/材质异常: '{element_desc}'",
                                        step_prompt=f"[ROTATE_3D] {direction} ({distance}px) (当前路径: {path_str})",
                                        actual_result=f"3D健康度检测未通过: {reason_3d}",
                                        crash_image_path=str(after_img_path),
                                        action_type="ROTATE_3D",
                                        target_element=element_desc,
                                        global_step=current_step,
                                        severity="High",
                                        ui_path=path_str
                                    )
                                else:
                                    logger.info(f"🛡️ [3D Health] 三维视点旋转后画面健康度检测通过: {reason_3d}")
                            except Exception as e_3d:
                                logger.warning(f"⚠️ 3D 健康度自检异常: {e_3d}")
                        elif action_type == "scroll":
                            direction = decision.get("direction", "down")
                            delta = int(decision.get("delta", 300))
                            logger.info(f"📜 [Scroll] 执行容器物理滚轮翻页: 目标='{element_desc}', 方向={direction}, 距离={delta}px, 坐标=({x}, {y})")
                            self.driver.scroll_element(x=x, y=y, direction=direction, delta=delta, delay_after=1.5)
                            time.sleep(1.0)
                            after_img_path = self.explore_dir / f"explore_step_{current_step}_after.png"
                            after_b64 = self.driver.capture_screenshot_base64(str(after_img_path))
                            logger.info(f"📸 捕获滚动翻页后快照: {after_img_path.name}")
                        elif action_type == "slide":
                            end_x_pct = decision.get("end_x_percent")
                            end_y_pct = decision.get("end_y_percent")
                            if end_x_pct is not None and end_y_pct is not None:
                                end_x = int(max(0, min(1, float(end_x_pct))) * width)
                                end_y = int(max(0, min(1, float(end_y_pct))) * height)
                            else:
                                end_x = min(width - 50, x + 200)
                                end_y = y
                            logger.info(f"🎚️ [Slide] 执行滑块拖拽: 起点=({x}, {y}) -> 终点=({end_x}, {end_y})")
                            self.driver.slide(start_x=x, start_y=y, end_x=end_x, end_y=end_y, steps=15, delay_after=1.5)
                            time.sleep(1.0)
                            after_img_path = self.explore_dir / f"explore_step_{current_step}_after.png"
                            after_b64 = self.driver.capture_screenshot_base64(str(after_img_path))
                            logger.info(f"📸 捕获滑块拖拽后快照: {after_img_path.name}")
                        elif action_type == "input":
                            input_text = decision.get("text")
                            if not input_text:
                                from utils.fuzz_payloads import get_fuzz_payload
                                input_text = get_fuzz_payload(element_desc=element_desc)
                            press_enter = bool(decision.get("press_enter", False))
                            logger.info(f"⌨️ [Input] 准备清空并键入内容: '{input_text}' (Enter={press_enter}) 到目标 '{element_desc}'")
                            self.driver.clear_and_type(x, y, text=str(input_text), press_enter=press_enter, delay_after=1.5)
                            time.sleep(1.0)
                            after_img_path = self.explore_dir / f"explore_step_{current_step}_after.png"
                            after_b64 = self.driver.capture_screenshot_base64(str(after_img_path))
                            logger.info(f"📸 捕获表单键入后快照: {after_img_path.name}")
                        else:
                            before_modals = PostClickDetector.get_current_modals(self.driver)
                            self.driver.click(x, y, button="left", delay_after=1.5)

                            # 状态差分与状态机实时追踪
                            try:
                                time.sleep(1.0)
                                after_img_path = self.explore_dir / f"explore_step_{current_step}_after.png"
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
                                click_diff = diff_res.get("change_ratio", 0.0) if isinstance(diff_res, dict) else 0.0
                                last_action_record = {"x": x, "y": y, "action": action_type, "diff_ratio": click_diff}

                                if transition == "modal_open" and trans_container:
                                    if trans_container not in container_stack:
                                        container_stack.append(trans_container)
                                        logger.info(f"📥 [Container Stack] 模态弹窗入栈: {trans_container} | 当前栈: {container_stack}")
                                elif transition == "modal_close":
                                    if container_stack:
                                        popped = container_stack.pop()
                                        logger.info(f"📤 [Container Stack] 模态弹窗出栈: {popped} | 剩余栈: {container_stack}")
                                elif transition == "page_navigate":
                                    if container_stack:
                                        logger.info(f"🔄 [Container Stack] 检测到路由跳转，清空模态栈: {container_stack}")
                                        container_stack.clear()
                                    is_panel_hidden = False
                                    mailing_dialog_open = False

                                desc_lower = (element_desc or "").lower()
                                if any(k in desc_lower for k in ["一键隐藏", "收起面板", "class_foldbarright"]) and not any(k in desc_lower for k in ["unfold", "展开", "显示"]):
                                    is_panel_hidden = True
                                    logger.warning("👁️ [Hide-Show Guard] 检测到触发【一键隐藏/收起】！大屏 2D 业务面板已隐藏。")
                                elif any(k in desc_lower for k in ["一键展开", "一键显示", "class_foldbarrightunfold", "展开面板", "展开"]):
                                    is_panel_hidden = False
                                    logger.info("👁️ [Hide-Show Guard] 检测到触发【一键展开/显示】！大屏 2D 业务面板已恢复展示。")

                                if "迈灵" in desc_lower or "mailing" in desc_lower:
                                    if any(k in desc_lower for k in ["close", "关闭", "❌", "收起"]):
                                        mailing_dialog_open = False
                                        if "“迈灵”AI助手对话框" in container_stack:
                                            container_stack.remove("“迈灵”AI助手对话框")
                                        logger.info("🤖 [Mailing Guard] 点击了关闭按钮，【迈灵】助手对话弹窗已关闭出栈。")
                                    else:
                                        mailing_dialog_open = not mailing_dialog_open
                                        if mailing_dialog_open:
                                            if "“迈灵”AI助手对话框" not in container_stack:
                                                container_stack.append("“迈灵”AI助手对话框")
                                            logger.info("🤖 [Mailing Guard] 点击了顶部【迈灵】图标，底部对话弹窗激活入栈。")
                                        else:
                                            if "“迈灵”AI助手对话框" in container_stack:
                                                container_stack.remove("“迈灵”AI助手对话框")
                                            logger.info("🤖 [Mailing Guard] 再次点击了顶部【迈灵】图标，底部对话弹窗已关闭出栈。")
                            except Exception as e_diff:
                                logger.warning(f"⚠️ Post-Click Diff 检测执行异常: {e_diff}")

                        action_success = True
                    except Exception as e_exec:
                        logger.error(f"❌ 物理执行失败: {e_exec}")
                        action_success = False
                        crash_img_path = str(self.explore_dir / f"crash_step_{current_step}_{worker_step}.png")
                        try:
                            self.driver.capture_screenshot(crash_img_path)
                        except Exception:
                            crash_img_path = None
                        path_str = " -> ".join(current_ui_path) if current_ui_path else "未知路径"
                        self.bug_reporter.report_bug(
                            run_id=self.run_id,
                            title=f"[{self.run_id}] 探索动作 '{element_desc}' 执行物理崩溃",
                            step_prompt=f"[{action_type.upper()}] {element_desc} (当前路径: {path_str})",
                            actual_result=f"底层驱动执行异常: {e_exec}",
                            crash_image_path=crash_img_path
                        )

                # --- 分支 C: Auto-API 双向核验 ---
                should_check_api = action_success and not batch_chart_handled and (validate_api or (action_type == "hover" and element_type in ("chart", "table")))
                if should_check_api:
                    check_instruction = api_assert_prompt.strip() if api_assert_prompt else f"验证截图中关于 '{element_desc}' 所展示的具体业务数值，是否与接口返回的数据逻辑一致（非 NaN 且非全 0 异常）"
                    search_context = f"{check_instruction} {element_desc}"
                    current_scope_str = " -> ".join([str(p) for p in current_ui_path[:2]]) if current_ui_path and len(current_ui_path) >= 2 else (str(current_ui_path[0]) if current_ui_path else None)
                    api_summary = self.driver.get_focused_api_records_summary(search_context, page_scope=current_scope_str)

                    if api_summary and api_summary != "[]":
                        logger.info(f"🔬 [Auto-API] 触发接口数据双向核验: {check_instruction}")
                        try:
                            full_b64 = hover_b64 if action_type == "hover" and 'hover_b64' in locals() else base64_img
                            check_b64 = full_b64
                            try:
                                if 'x' in locals() and 'y' in locals() and x is not None and y is not None:
                                    target_img_path = str(hover_img_path) if action_type == "hover" and 'hover_img_path' in locals() else str(step_img_path)
                                    dpr_val = info.get("devicePixelRatio", 1.0) if 'info' in locals() and isinstance(info, dict) else 1.0
                                    roi_save = str(self.explore_dir / f"explore_step_{current_step}_roi.png")
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
                            if is_unrelated and check_b64 != full_b64 and full_b64:
                                logger.info("ℹ️ [Auto-API] 局部 ROI 视野受限判定为非同源，回退使用全景快照进行二次核验...")
                                passed_retry, reason_retry = self.vision.check_api_assertion(
                                    instruction=check_instruction,
                                    base64_image=full_b64,
                                    api_data_json=api_summary
                                )
                                is_unrelated_retry = ("非同源" in reason_retry or "跳过" in reason_retry or "UNRELATED" in reason_retry)
                                if not is_unrelated_retry:
                                    passed, reason, is_unrelated = passed_retry, reason_retry, False
                                    logger.info(f"✨ [Auto-API] 全景快照成功命中同源业务数据！核验判定: passed={passed}")
                            if not passed:
                                logger.error(f"🚨 [API MISMATCH] 接口数据核验未通过: {reason}")
                                action_success = False
                                
                                # 优先锁定大模型用于断言判定的现场瞬态图像（局部高精 ROI 切片或当时的 hover 快照）
                                evidence_img = None
                                if 'roi_save' in locals() and roi_save and Path(roi_save).exists() and check_b64 == roi_b64:
                                    evidence_img = str(roi_save)
                                elif 'target_img_path' in locals() and target_img_path and Path(target_img_path).exists():
                                    evidence_img = str(target_img_path)
                                
                                if not evidence_img:
                                    data_bug_img = str(self.explore_dir / f"data_bug_{current_step}_{worker_step}.png")
                                    try:
                                        self.driver.capture_screenshot(data_bug_img)
                                        evidence_img = data_bug_img
                                    except Exception:
                                        evidence_img = None

                                path_str = " -> ".join(current_ui_path) if current_ui_path else "未知路径"
                                self.bug_reporter.report_bug(
                                    run_id=self.run_id,
                                    title=f"[{self.run_id}] UI数据与接口原始报文不匹配: '{element_desc}'",
                                    step_prompt=f"[{action_type.upper()}] 核验: {check_instruction} (路径: {path_str})",
                                    actual_result=f"数据断言失败: {reason}",
                                    crash_image_path=evidence_img
                                )
                            elif is_unrelated:
                                logger.info(f"ℹ️ [Auto-API] 候选接口非当前被测组件数据源，跳过数据断言（不纳入用例，不上报Bug）。")
                            else:
                                logger.info(f"🎉 [Auto-API] 接口数据核验通过！UI 渲染与后端 JSON 完全一致。")
                                task_trajectory.append({
                                    "type": "api_assert",
                                    "prompt": check_instruction,
                                    "thought": f"自动核验 {element_desc} 的接口数据对齐"
                                })
                        except Exception as api_err:
                            logger.warning(f"⚠️ 执行 API 数据核验时发生异常: {api_err}")
                    else:
                        logger.info("ℹ️ [Auto-API] 底层抓包池暂无相关 JSON 报文，跳过数据比对。")

                # --- 分支 D: 底层异常捕获 (Console / Network 500) ---
                bugs = self.driver.get_and_clear_bugs()
                if bugs:
                    action_success = False
                    logger.error(f"🚨 [BUG FOUND] 在执行操作 [{action_type.upper()}] '{element_desc}' 时，系统捕获到 {len(bugs)} 个底层异常！")
                    raw_bugs_dir = self.log_dir / "raw_bugs"
                    raw_bugs_dir.mkdir(parents=True, exist_ok=True)
                    bug_report_file = raw_bugs_dir / f"bug_report_{current_step}_{worker_step}.json"
                    with open(bug_report_file, "w", encoding="utf-8") as f:
                        json.dump(bugs, f, ensure_ascii=False, indent=2)

                    b_types = [b.get("type", "unknown") for b in bugs]
                    has_js_crash = "page_error" in b_types
                    has_500 = any(b.get("type") == "network_error" and ("500" in b.get("text", "") or "502" in b.get("text", "")) for b in bugs)
                    sev = "High" if (has_js_crash or has_500) else "Medium"

                    actual_lines = []
                    for b in bugs:
                        t = b.get("type", "error")
                        text_val = b.get("msg") or b.get("text") or ""
                        if t == "api_biz_error":
                            endpoint = b.get("endpoint") or ""
                            url = b.get("url") or ""
                            biz_code = b.get("biz_code")
                            code_str = f", 业务码: {biz_code}" if biz_code is not None else ""
                            raw_msg = b.get("msg") or ""
                            if raw_msg.startswith("接口业务报错: "):
                                raw_msg = raw_msg[len("接口业务报错: "):]
                            text_val = f"接口业务报错: {raw_msg} (接口方法: {endpoint or '未知'}, URL: {url}{code_str})"
                        elif t == "network_error" and b.get("url"):
                            status_val = b.get("status", "Error")
                            text_val = f"网络请求失败 HTTP {status_val}: {b.get('url')}"
                        loc = b.get("location", "")
                        loc_str = f" (代码位置: {loc})" if loc else ""
                        line_str = f"[{t}{loc_str}] {text_val}".strip()
                        actual_lines.append(line_str)

                    crash_img_cand = None
                    if action_type == "hover" and 'hover_img_path' in locals() and hover_img_path and Path(hover_img_path).exists():
                        crash_img_cand = str(hover_img_path)
                    elif 'after_img_path' in locals() and after_img_path and Path(after_img_path).exists():
                        crash_img_cand = str(after_img_path)
                    elif 'step_img_path' in locals() and step_img_path and Path(step_img_path).exists():
                        crash_img_cand = str(step_img_path)

                    path_str = " -> ".join(current_ui_path) if current_ui_path else "未知路径"
                    self.bug_reporter.report_bug(
                        run_id=self.run_id,
                        title=f"[{self.run_id}] 探索操作 '{element_desc}' 触发底层异常",
                        step_prompt=f"[{action_type.upper()}] 交互目标: '{element_desc}' (页面路径: {path_str})",
                        actual_result="\n".join(actual_lines),
                        crash_image_path=crash_img_cand,
                        action_type=action_type.upper(),
                        target_element=element_desc,
                        global_step=current_step,
                        severity=sev,
                        ui_path=path_str
                    )

                # 记录战术历史
                action_history.append({
                    "action": action_type,
                    "target": element_desc,
                    "success": action_success,
                    "thought": thought,
                    "current_ui_path": current_ui_path
                })
                if action_success:
                    if action_type == "zoom":
                        dir_str = str(decision.get("direction", "in")).upper()
                        steps_val = int(decision.get("steps", 3))
                        task_trajectory.append({
                            "type": "zoom",
                            "prompt": f"[ZOOM_{dir_str}] {element_desc}",
                            "direction": decision.get("direction", "in"),
                            "steps": steps_val,
                            "thought": thought
                        })
                    elif action_type == "rotate_3d":
                        dir_str = str(decision.get("direction", "left")).upper()
                        dist_val = int(decision.get("distance", 250))
                        task_trajectory.append({
                            "type": "rotate_3d",
                            "prompt": f"[ROTATE_{dir_str}] {element_desc}",
                            "direction": decision.get("direction", "left"),
                            "distance": dist_val,
                            "thought": thought
                        })
                    elif action_type == "scroll":
                        dir_str = str(decision.get("direction", "down")).upper()
                        delta_val = int(decision.get("delta", 300))
                        task_trajectory.append({
                            "type": "scroll",
                            "prompt": f"[SCROLL_{dir_str}] {element_desc}",
                            "direction": decision.get("direction", "down"),
                            "delta": delta_val,
                            "thought": thought
                        })
                    elif action_type == "slide":
                        task_trajectory.append({
                            "type": "slide",
                            "prompt": f"[SLIDE] {element_desc}",
                            "thought": thought
                        })
                    elif action_type == "input":
                        task_trajectory.append({
                            "type": "input",
                            "prompt": element_desc,
                            "text": input_text if 'input_text' in locals() else decision.get("text", ""),
                            "press_enter": bool(decision.get("press_enter", False)),
                            "thought": thought
                        })
                    elif action_type == "back":
                        task_trajectory.append({
                            "type": "back",
                            "prompt": "[BACK] 路由历史回退",
                            "thought": thought
                        })
                    elif action_type == "reload":
                        task_trajectory.append({
                            "type": "reload",
                            "prompt": "[RELOAD] 重置刷新页面",
                            "thought": thought
                        })
                    else:
                        task_trajectory.append({
                            "type": action_type,
                            "prompt": element_desc,
                            "thought": thought
                        })

                if worker_finished_early:
                    logger.info("✅ [Worker] 批量嗅探与集中核验已达成，提前交还控制权给 Planner。")
                    break

        return {
            "steps_used": steps_used,
            "trajectory": task_trajectory,
            "container_stack": container_stack,
            "is_panel_hidden": is_panel_hidden,
            "mailing_dialog_open": mailing_dialog_open,
            "last_l2_route": last_l2_route
        }
