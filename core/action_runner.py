import logging
import time
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.browser import ElectronDriver
from core.vision.agent import VisionAgent, VisionAgentException
from core.bug_reporter import BugReporter
from utils.paths import screenshot_path, report_run_id

logger = logging.getLogger("core.action_runner")

class ActionRunnerException(Exception):
    pass


class ActionRunner:
    """
    调度核心引擎 (神经系统)
    串联 YAML 脚本解析、物理驱动操作(Browser)、AI 多模态推理(VisionAgent)。
    """

    def __init__(self, driver: ElectronDriver, vision_agent: VisionAgent):
        self.driver = driver
        self.vision = vision_agent
        self.bug_reporter = BugReporter(vision_agent=self.vision)
        self._step_counter = 0

    def run_yaml_case(self, yaml_path: str, global_ignore_errors: bool = False):
        """执行单个 YAML 测试用例"""
        path = Path(yaml_path)
        if not path.exists():
            raise FileNotFoundError(f"用例文件不存在: {yaml_path}")

        with open(path, "r", encoding="utf-8") as f:
            case_data = yaml.safe_load(f)

        case_name = case_data.get("name", "未命名测试场景")
        yaml_ignore_error = case_data.get("ignore_error", False)
        should_ignore = global_ignore_errors or yaml_ignore_error
        steps = case_data.get("steps", [])

        logger.info("=" * 60)
        logger.info(f"▶️ 开始执行巡检用例: {case_name}")
        logger.info("=" * 60)

        # 用例启动前静默锚定初始内存水位基线，供后续 memory_leak_check 步骤执行增量对比
        try:
            if hasattr(self.driver, "record_memory_snapshot"):
                self.driver.record_memory_snapshot(label=f"case_start:{case_name}", set_as_baseline=True, trigger_gc=True)
        except Exception as e_mem:
            logger.debug(f"[MemoryProbe] 初始化用例内存基线跳过: {e_mem}")

        errors = []
        for i, step in enumerate(steps, 1):
            self._step_counter = i
            # 在步骤开始前加入一个换行符，以便在日志中形成视觉分隔
            logger.info(f"\n--- [Step {i}/{len(steps)}] 类型: {step.get('type')} ---")
            
            try:
                self._execute_step(step)
            except Exception as e:
                # 出现异常时，立刻留存案发现场截图至当前运行的专属截图目录
                curr_run_id = report_run_id()
                crash_pic = screenshot_path(f"{path.stem}_CRASH_step_{i}", run_id=curr_run_id)
                self.driver.capture_screenshot(str(crash_pic))
                logger.error(f"❌ 步骤 {i} 执行失败！现场已保存: {crash_pic}")
                logger.error(f"异常详情: {e}")
                
                # 记录缺陷并收敛至单次运行目录与全局资产库
                title = f"[{path.stem}] Step {i} 异常崩溃"
                prompt_text = step.get('prompt', '无操作指令')
                self.bug_reporter.report_bug(
                    run_id=curr_run_id,
                    title=title,
                    step_prompt=prompt_text,
                    actual_result=str(e),
                    crash_image_path=str(crash_pic)
                )
                
                if step.get("ignore_error", should_ignore):
                    logger.warning(f"⚠️ 步骤 {i} 触发了 ignore_error 机制，记录错误并继续往下执行。")
                    errors.append(f"Step {i}: {str(e)}")
                else:
                    raise ActionRunnerException(f"用例执行失败: {case_name} -> Step {i}") from e

        if errors:
            logger.error("=" * 60)
            logger.error(f"⚠️ 用例执行完毕，但存在 {len(errors)} 个忽略的报错。")
            error_summary = '\n'.join(errors)
            raise ActionRunnerException(f"用例包含被忽略的报错（Soft Errors）:\n{error_summary}")

        logger.info("=" * 60)
        logger.info(f"✅ 用例执行圆满完成: {case_name}")
        logger.info("=" * 60)

    def _execute_step(self, step: Dict[str, Any], max_retries: int = 2):
        """
        分发执行单步指令，带有三层递进式智能补偿机制:
        - 策略 A (物理等待): 等 3 秒，让前端渲染完成。
        - 策略 B (物理滚动): 向下滚动一小屏，寻找隐藏元素。
        - 策略 C (语义自愈): 截图给 AI 看，让它诊断根因并执行一个前置补救动作，再重试原步骤。
        """
        step_type = step.get("type")
        prompt = step.get("prompt", "")

        last_exception = None

        for attempt in range(max_retries + 1):
            try:
                if step_type == "action":
                    self._do_action(prompt)
                elif step_type == "input":
                    text = step.get("text")
                    fuzz = step.get("fuzz", False)
                    fuzz_category = step.get("fuzz_category", "auto")
                    if fuzz or not text:
                        from utils.fuzz_payloads import get_fuzz_payload
                        text = get_fuzz_payload(element_desc=prompt, category=fuzz_category)
                    press_enter = bool(step.get("press_enter", False))
                    clear_first = bool(step.get("clear_first", True))
                    self._do_input(prompt, str(text), clear_first=clear_first, press_enter=press_enter)
                elif step_type == "assert":
                    self._do_assert(prompt)
                elif step_type == "api_assert":
                    target_api = step.get("target_api")
                    self._do_api_assert(prompt, target_api=target_api)
                elif step_type in ("physics_sanity_check", "sanity_check"):
                    self._do_physics_sanity_check(prompt)
                elif step_type in ("assert_no_console_errors", "console_crash_check"):
                    strict_mode = bool(step.get("strict", False))
                    reset_only = bool(step.get("reset", False))
                    self._do_assert_no_console_errors(prompt=prompt, strict=strict_mode, reset=reset_only)
                elif step_type in ("memory_leak_check", "memory_probe"):
                    self._do_memory_leak_check(step)
                elif step_type in ("canvas_stress_drag", "stress_3d"):
                    stress_mode = str(step.get("mode", "hybrid"))
                    rounds = int(step.get("rounds", 3))
                    radius = int(step.get("radius", 300))
                    btn = str(step.get("button", "right"))
                    visual_assert = bool(step.get("visual_assert", True))
                    self._do_canvas_stress_drag(
                        prompt=prompt,
                        mode=stress_mode,
                        rounds=rounds,
                        radius=radius,
                        button=btn,
                        visual_assert=visual_assert
                    )
                elif step_type == "freeze_check":
                    wait_sec = float(step.get("wait_seconds", 5.0))
                    self._do_freeze_check(prompt, wait_sec)
                elif step_type == "wait_for":
                    timeout = float(step.get("timeout", 60.0))
                    interval = float(step.get("interval", 3.0))
                    self._do_wait_for(prompt, timeout, interval)
                elif step_type in ("zoom", "zoom_3d"):
                    direction = step.get("direction", "in")
                    steps_cnt = int(step.get("steps", 3))
                    self._do_zoom(prompt, direction=direction, steps=steps_cnt)
                elif step_type in ("rotate_3d", "orbit"):
                    direction = step.get("direction", "left")
                    distance = int(step.get("distance", 250))
                    button = step.get("button", "right")
                    self._do_rotate_3d(prompt, direction=direction, distance=distance, button=button)
                elif step_type in ("wheel", "mouse_wheel"):
                    delta_x = float(step.get("delta_x", 0))
                    delta_y = float(step.get("delta_y", -300))
                    self._do_wheel(prompt, delta_x=delta_x, delta_y=delta_y)
                elif step_type in ("scroll", "scroll_element"):
                    direction = step.get("direction", "down")
                    delta = int(step.get("delta", 300))
                    self._do_scroll(prompt, direction=direction, delta=delta)
                elif step_type in ("slide", "slider"):
                    start = step.get("start")
                    end = step.get("end")
                    start_x = step.get("start_x")
                    start_y = step.get("start_y")
                    end_x = step.get("end_x")
                    end_y = step.get("end_y")
                    self._do_slide(prompt=prompt, start=start, end=end, start_x=start_x, start_y=start_y, end_x=end_x, end_y=end_y)
                elif step_type == "drag":
                    from_x = step.get("from_x")
                    from_y = step.get("from_y")
                    to_x = step.get("to_x")
                    to_y = step.get("to_y")
                    btn = step.get("button", "left")
                    if from_x is not None and from_y is not None and to_x is not None and to_y is not None:
                        self.driver.drag(int(from_x), int(from_y), int(to_x), int(to_y), button=btn)
                    else:
                        logger.warning("drag 步骤缺少具体坐标参数！")
                elif step_type in ("back", "go_back", "navigate_back"):
                    self.driver.navigate_back()
                elif step_type in ("reload", "refresh"):
                    self.driver.reload_page()
                elif step_type == "wait":
                    wait_sec = float(step.get("seconds", 2.0))
                    self.driver.wait(wait_sec)
                else:
                    logger.warning(f"未知步骤类型: {step_type}，跳过执行。")

                # 执行成功，跳出重试循环
                return

            except VisionAgentException as ve:
                last_exception = ve
                if attempt < max_retries:
                    # ====== 物理补偿机制 ======
                    logger.warning(f"⚠️ AI 寻找目标或断言失败: {ve}")
                    logger.warning(f"🔧 启动物理补偿 (第 {attempt+1}/{max_retries} 次)...")

                    if attempt == 0:
                        logger.info("🔧 [策略 A] 纯物理等待 3 秒，让前端有时间渲染...")
                        time.sleep(3.0)
                    elif attempt == 1:
                        logger.info("🔧 [策略 B] 尝试向下滚动一小屏寻找隐藏元素...")
                        if step_type in ("action", "input"):
                            self.driver.scroll(delta_y=400)
                        time.sleep(2.0)
                else:
                    # 物理重试全部耗尽，启动语义自愈
                    logger.warning("⚠️ 物理补偿已耗尽，升级到 [策略 C] 语义自愈模式...")
                    healed = self._try_semantic_heal(prompt, str(ve), step_type)
                    if healed:
                        # 自愈动作执行完毕，再给原步骤最后一次机会
                        logger.info("🔁 [策略 C] 补救动作已执行，最后一次尝试原始步骤...")
                        # 直接执行（不再嵌套重试），如果还是失败则抛出
                        if step_type == "action":
                            self._do_action(prompt)
                        elif step_type == "input":
                            self._do_input(prompt, str(step.get("text", "")))
                        elif step_type == "assert":
                            self._do_assert(prompt)
                        return  # 自愈后成功执行
                    else:
                        logger.error("🚫 [策略 C] AI 无法给出有效补救方案，任务中断。")
                        raise


    def _try_semantic_heal(self, failed_prompt: str, error_msg: str, step_type: str) -> bool:
        """
        语义自愈执行器 (Semantic Self-Healer)
        调用 AI 分析当前截图，获取补救建议，并真实执行补救动作。
        返回 True 表示补救动作已执行完毕（不代表一定修复成功），False 表示 AI 无法给出方案。
        """
        try:
            b64_img = self.driver.capture_screenshot_base64()
            viewport = self.driver.get_viewport_info()
            dom_elements = self.driver.extract_interactive_elements()

            result = self.vision.analyze_failure_and_suggest_fix(
                failed_prompt=failed_prompt,
                error_msg=error_msg,
                base64_image=b64_img
            )

            can_fix = result.get("can_fix", False)
            reason = result.get("reason", "未知")
            fix_action = result.get("fix_action", "")
            fix_type = result.get("fix_type", "click")

            logger.info(f"🔬 [语义自愈] AI 诊断结果: {reason}")

            if not can_fix or not fix_action:
                logger.warning("🔬 [语义自愈] AI 判定无法自动修复此问题。")
                return False

            logger.info(f"💊 [语义自愈] 执行补救动作 [{fix_type}]: {fix_action}")

            if fix_type == "click":
                x, y = self.vision.find_element(
                    instruction=fix_action,
                    base64_image=b64_img,
                    viewport_width=viewport["width"],
                    viewport_height=viewport["height"],
                    dom_elements=dom_elements
                )
                self.driver.click(x, y)
                time.sleep(1.5)  # 等待补救动作生效
            elif fix_type == "hover":
                x, y = self.vision.find_element(
                    instruction=fix_action,
                    base64_image=b64_img,
                    viewport_width=viewport["width"],
                    viewport_height=viewport["height"],
                    dom_elements=dom_elements
                )
                self.driver.hover(x, y)
                time.sleep(2.0)  # 等待悬浮下拉菜单完全展开渲染
            elif fix_type == "scroll_down":
                self.driver.scroll(delta_y=500)
                time.sleep(1.0)
            elif fix_type == "scroll_up":
                self.driver.scroll(delta_y=-500)
                time.sleep(1.0)
            elif fix_type == "press_escape":
                self.driver.press_key("Escape")
                time.sleep(1.0)
            elif fix_type == "wait":
                time.sleep(3.0)

            return True

        except Exception as heal_err:
            logger.warning(f"🔬 [语义自愈] 补救执行本身出现异常: {heal_err}，将放弃自愈。")
            return False

    def _do_action(self, prompt: str):
        """执行视觉动作 (支持自动解析 [HOVER]/[CLICK] 前缀)"""
        # 1. Perception
        b64_img = self.driver.capture_screenshot_base64()
        viewport = self.driver.get_viewport_info()
        dom_elements = self.driver.extract_interactive_elements()
        
        # 解析动作类型 (支持 ExplorerAgent 自动生成的各类 [TAG] 前缀)
        action_type = "click"
        direction = "in"
        prompt_upper = prompt.strip().upper()
        if prompt_upper.startswith("[HOVER]"):
            action_type = "hover"
            prompt = prompt.strip()[7:].strip()
        elif prompt_upper.startswith("[CLICK]"):
            action_type = "click"
            prompt = prompt.strip()[7:].strip()
        elif prompt_upper.startswith("[ZOOM_IN]"):
            action_type = "zoom"
            direction = "in"
            prompt = prompt.strip()[9:].strip()
        elif prompt_upper.startswith("[ZOOM_OUT]"):
            action_type = "zoom"
            direction = "out"
            prompt = prompt.strip()[10:].strip()
        elif prompt_upper.startswith("[ROTATE_3D]"):
            action_type = "rotate_3d"
            prompt = prompt.strip()[11:].strip()
        elif prompt_upper.startswith("[ROTATE_LEFT]"):
            action_type = "rotate_3d"
            direction = "left"
            prompt = prompt.strip()[13:].strip()
        elif prompt_upper.startswith("[ROTATE_RIGHT]"):
            action_type = "rotate_3d"
            direction = "right"
            prompt = prompt.strip()[14:].strip()
        elif prompt_upper.startswith("[ROTATE_UP]"):
            action_type = "rotate_3d"
            direction = "up"
            prompt = prompt.strip()[11:].strip()
        elif prompt_upper.startswith("[CANVAS_STRESS_DRAG]"):
            action_type = "canvas_stress_drag"
            prompt = prompt.strip()[20:].strip()
        elif prompt_upper.startswith("[STRESS_3D]"):
            action_type = "canvas_stress_drag"
            prompt = prompt.strip()[11:].strip()
        elif prompt_upper.startswith("[ROTATE_DOWN]"):
            action_type = "rotate_3d"
            direction = "down"
            prompt = prompt.strip()[13:].strip()
        elif prompt_upper.startswith("[SCROLL_DOWN]"):
            action_type = "scroll"
            direction = "down"
            prompt = prompt.strip()[13:].strip()
        elif prompt_upper.startswith("[SCROLL_UP]"):
            action_type = "scroll"
            direction = "up"
            prompt = prompt.strip()[11:].strip()
        elif prompt_upper.startswith("[SCROLL]"):
            action_type = "scroll"
            direction = "down"
            prompt = prompt.strip()[8:].strip()
        elif prompt_upper.startswith("[BACK]"):
            action_type = "back"
            prompt = prompt.strip()[6:].strip()
        elif prompt_upper.startswith("[RELOAD]"):
            action_type = "reload"
            prompt = prompt.strip()[8:].strip()

        # 针对 3D、手势与路由回溯动作分发
        if action_type == "zoom":
            self._do_zoom(prompt=prompt if prompt else None, direction=direction)
            return
        elif action_type == "canvas_stress_drag":
            self._do_canvas_stress_drag(prompt=prompt if prompt else "")
            return
        elif action_type == "rotate_3d":
            self._do_rotate_3d(prompt=prompt if prompt else None, direction=direction if direction != "in" else "left")
            return
        elif action_type == "scroll":
            self._do_scroll(prompt=prompt if prompt else None, direction=direction)
            return
        elif action_type == "slide":
            self._do_slide(prompt=prompt if prompt else None)
            return
        elif action_type == "back":
            self.driver.navigate_back()
            return
        elif action_type == "reload":
            self.driver.reload_page()
            return

        # 针对关闭弹窗动作优先尝试原生确定性关闭
        prompt_lower = prompt.lower()
        if action_type == "click" and any(k in prompt_lower for k in ["弹窗", "浮窗", "查看器", "pdf", "图纸", "证书", "详情", "modal", "dialog"]) and any(k in prompt_lower for k in ["关闭", "❌", "叉号", "close", "收起"]):
            if self.driver.close_active_modal():
                logger.info(f"🎉 [Modal Close] ActionRunner 已通过底层原生 DOM 成功关闭弹窗: '{prompt}'！")
                return

        # 2. Cognition
        x, y = self.vision.find_element(
            instruction=prompt,
            base64_image=b64_img,
            viewport_width=viewport["width"],
            viewport_height=viewport["height"],
            dom_elements=dom_elements
        )

        # 3. Action
        if hasattr(self.driver, "mark_action_timestamp"):
            self.driver.mark_action_timestamp()
        if action_type == "hover":
            self.driver.hover(x, y)
        else:
            self.driver.click(x, y)

    def _do_zoom(self, prompt: str = None, direction: str = "in", steps: int = 3):
        """执行三维场景镜头推进或拉远"""
        target_x, target_y = None, None
        if prompt and prompt.strip():
            try:
                b64_img = self.driver.capture_screenshot_base64()
                viewport = self.driver.get_viewport_info()
                dom_elements = self.driver.extract_interactive_elements()
                target_x, target_y = self.vision.find_element(
                    instruction=prompt,
                    base64_image=b64_img,
                    viewport_width=viewport["width"],
                    viewport_height=viewport["height"],
                    dom_elements=dom_elements
                )
            except Exception:
                pass
        if hasattr(self.driver, "mark_action_timestamp"):
            self.driver.mark_action_timestamp()
        self.driver.zoom_3d(x=target_x, y=target_y, direction=direction, steps=steps)

    def _do_rotate_3d(self, prompt: str = None, direction: str = "left", distance: int = 250, button: str = "right"):
        """执行三维场景轨道平滑旋转"""
        cx, cy = None, None
        if prompt and prompt.strip():
            try:
                b64_img = self.driver.capture_screenshot_base64()
                viewport = self.driver.get_viewport_info()
                dom_elements = self.driver.extract_interactive_elements()
                cx, cy = self.vision.find_element(
                    instruction=prompt,
                    base64_image=b64_img,
                    viewport_width=viewport["width"],
                    viewport_height=viewport["height"],
                    dom_elements=dom_elements
                )
            except Exception:
                pass
        if hasattr(self.driver, "mark_action_timestamp"):
            self.driver.mark_action_timestamp()
        self.driver.rotate_3d(center_x=cx, center_y=cy, direction=direction, distance=distance, button=button)

    def _do_wheel(self, prompt: str = None, delta_x: float = 0, delta_y: float = -300):
        """执行鼠标滚轮滚动"""
        tx, ty = None, None
        if prompt and prompt.strip():
            try:
                b64_img = self.driver.capture_screenshot_base64()
                viewport = self.driver.get_viewport_info()
                dom_elements = self.driver.extract_interactive_elements()
                tx, ty = self.vision.find_element(
                    instruction=prompt,
                    base64_image=b64_img,
                    viewport_width=viewport["width"],
                    viewport_height=viewport["height"],
                    dom_elements=dom_elements
                )
            except Exception:
                pass
        if hasattr(self.driver, "mark_action_timestamp"):
            self.driver.mark_action_timestamp()
        self.driver.mouse_wheel(x=tx, y=ty, delta_x=delta_x, delta_y=delta_y)

    def _do_scroll(self, prompt: str = None, direction: str = "down", delta: int = 300):
        """执行指定容器或长表格内的滚轮翻页"""
        tx, ty = None, None
        if prompt and prompt.strip():
            try:
                b64_img = self.driver.capture_screenshot_base64()
                viewport = self.driver.get_viewport_info()
                dom_elements = self.driver.extract_interactive_elements()
                tx, ty = self.vision.find_element(
                    instruction=prompt,
                    base64_image=b64_img,
                    viewport_width=viewport["width"],
                    viewport_height=viewport["height"],
                    dom_elements=dom_elements
                )
            except Exception:
                pass
        if hasattr(self.driver, "mark_action_timestamp"):
            self.driver.mark_action_timestamp()
        self.driver.scroll_element(x=tx, y=ty, direction=direction, delta=delta)

    def _do_slide(self, prompt: str = None, start: str = None, end: str = None,
                  start_x: int = None, start_y: int = None, end_x: int = None, end_y: int = None):
        """执行滑块或时间轴连续平滑拖拽"""
        b64_img = self.driver.capture_screenshot_base64()
        viewport = self.driver.get_viewport_info()
        dom_elements = self.driver.extract_interactive_elements()

        sx, sy = start_x, start_y
        ex, ey = end_x, end_y

        if (sx is None or sy is None) and start:
            sx, sy = self.vision.find_element(
                instruction=start,
                base64_image=b64_img,
                viewport_width=viewport["width"],
                viewport_height=viewport["height"],
                dom_elements=dom_elements
            )
        elif (sx is None or sy is None) and prompt:
            sx, sy = self.vision.find_element(
                instruction=prompt,
                base64_image=b64_img,
                viewport_width=viewport["width"],
                viewport_height=viewport["height"],
                dom_elements=dom_elements
            )

        if (ex is None or ey is None) and end:
            ex, ey = self.vision.find_element(
                instruction=end,
                base64_image=b64_img,
                viewport_width=viewport["width"],
                viewport_height=viewport["height"],
                dom_elements=dom_elements
            )

        if sx is None or sy is None:
            raise VisionAgentException("未能定位滑块拖拽的起始坐标！")
        if ex is None or ey is None:
            ex = sx + 200
            ey = sy

        if hasattr(self.driver, "mark_action_timestamp"):
            self.driver.mark_action_timestamp()
        self.driver.slide(start_x=int(sx), start_y=int(sy), end_x=int(ex), end_y=int(ey))

    def _do_input(self, prompt: str, text: str, clear_first: bool = True, press_enter: bool = False):
        """执行视觉定位后清空并键入文本"""
        # 1. Perception
        b64_img = self.driver.capture_screenshot_base64()
        viewport = self.driver.get_viewport_info()
        dom_elements = self.driver.extract_interactive_elements()
        
        # 2. Cognition
        x, y = self.vision.find_element(
            instruction=prompt,
            base64_image=b64_img,
            viewport_width=viewport["width"],
            viewport_height=viewport["height"],
            dom_elements=dom_elements
        )
        
        # 3. Action
        if hasattr(self.driver, "mark_action_timestamp"):
            self.driver.mark_action_timestamp()
        if clear_first:
            self.driver.clear_and_type(x, y, text, press_enter=press_enter)
        else:
            self.driver.click(x, y)
            self.driver.type_text(text)
            if press_enter:
                self.driver.press_key("Enter")

    def _do_assert(self, prompt: str):
        """执行单次视觉断言"""
        b64_img = self.driver.capture_screenshot_base64()
        passed, reason = self.vision.check_assertion(instruction=prompt, base64_image=b64_img)
        
        if not passed:
            raise ActionRunnerException(f"视觉断言失败！理由: {reason}")

    def _do_api_assert(self, prompt: str, target_api: Optional[str] = None):
        """执行 API 接口与视觉双重断言（支持基于特征倒排索引的动态聚焦与 target_api 指定过滤）"""
        b64_img = self.driver.capture_screenshot_base64()
        query_text = f"{target_api} {prompt}" if target_api else prompt
        api_data_json = self.driver.get_focused_api_records_summary(query_text)
        
        passed, reason = self.vision.check_api_assertion(
            instruction=prompt, 
            base64_image=b64_img, 
            api_data_json=api_data_json
        )
        
        if not passed:
            raise ActionRunnerException(f"API 双重断言失败！理由: {reason}")

    def _do_wait_for(self, prompt: str, timeout: float = 60.0, interval: float = 3.0):
        """
        智能视觉轮询等待。
        不断截屏并利用大模型断言目标条件，直到通过或超时。
        """
        logger.info(f"⏳ [Vision Wait] 开始智能等待 (超时: {timeout}s): {prompt}")
        start_time = time.time()
        attempt = 1
        
        while True:
            elapsed = time.time() - start_time
            if elapsed > timeout:
                raise ActionRunnerException(f"智能视觉等待超时 ({timeout}s)! 条件始终未满足: {prompt}")
                
            b64_img = self.driver.capture_screenshot_base64()
            passed, reason = self.vision.check_assertion(instruction=prompt, base64_image=b64_img)
            
            if passed:
                logger.info(f"✅ [Vision Wait] 画面满足条件，等待结束 (耗时: {elapsed:.1f}s)")
                break
                
            logger.info(f"🔄 [Vision Wait] 画面尚未就绪，{interval}s 后重试 (第 {attempt} 次检测)...")
            time.sleep(interval)
            attempt += 1

    def _do_freeze_check(self, prompt: str, wait_seconds: float):
        """
        防假死时序断言（矿山核心铁律二）。
        在相隔 `wait_seconds` 的时间内连续截取两张图，交由大模型对比判断动态数据是否卡死。
        """
        logger.info(f"❄️ 开始防假死检测，获取快照 A，并等待 {wait_seconds} 秒...")
        img_a = self.driver.capture_screenshot_base64()
        
        time.sleep(wait_seconds)
        
        logger.info("❄️ 获取快照 B...")
        img_b = self.driver.capture_screenshot_base64()
        
        # 要求 VisionAgent 比对两者
        # 注意：这里我们拼接两张图片发送，或者在 Prompt 里说明两者是前后时序
        instruction = f"前一张图片是 {wait_seconds} 秒前的快照，后一张图片是当前快照。请关注指定区域：{prompt}。请对比两张图，判断该区域内的数值、图表或动画是否发生了明显的变化？如果完全静止一样，请判定为 false (假死)。"
        
        logger.info("⚖️ 将两张时序快照送往大模型进行双重比对...")
        # 为了适配单图接口，我们可以修改 vision_agent 接收列表，或者巧妙地将两张图片发送。
        # 鉴于标准的 _call_llm 目前支持一张图，我们可以对 vision_agent 做小小扩展，
        # 或者在这里分两次查询，但效果不如直接让多模态模型看多图。
        # 这里演示简单实现：假设模型可以直接理解我们的 prompt 中的“对比”指令，我们需要稍微调整 _call_llm 接收 list。
        # 作为折中方案，我们复用 check_assertion，但底层需支持传入两张图。
        # 在此版本中，我们在 _do_freeze_check 调用特殊方法（需稍后在 VisionAgent 中扩充），
        # 或者采用一种逻辑：先让 AI 提取 A 图特征，再提取 B 图特征，代码端对比。
        
        # 为了极致纯视觉化，我们直接调用一个特殊方法
        passed, reason = self.vision.compare_images_for_freeze(
            instruction=instruction,
            base64_image_a=img_a,
            base64_image_b=img_b
        )
        
        if not passed:
            raise ActionRunnerException(f"❄️ 防假死检测不通过，大屏涉嫌卡死或数据断流！AI 理由: {reason}")


    def _do_physics_sanity_check(self, prompt: str = ""):
        """
        物理常识与合理性断言（矿山核心铁律三）。
        结合零 Token 静态 DOM 脏值预筛与多模态视觉巡检，拦截 NaN/undefined、负人数、越界百分比与 ERP 1000倍量纲灾难。
        """
        from core.explorer_agent.guards import ExplorerGuards

        b64_img = self.driver.capture_screenshot_base64()
        dom_elements = []
        try:
            dom_elements = self.driver.extract_interactive_elements() or []
        except Exception as e_dom:
            logger.debug(f"[PhysicsSanity] DOM 提取降级纯视觉模式: {e_dom}")

        dom_anomalies = ExplorerGuards.scan_text_physics_anomalies(dom_elements)
        if dom_anomalies:
            logger.warning(f"🔎 [PhysicsSanity] 静态 DOM 预筛捕获到 {len(dom_anomalies)} 条疑似脏值/物理异常线索: {dom_anomalies}")

        api_context = ""
        try:
            search_q = f"{prompt} {' '.join(dom_anomalies[:3])}".strip()
            if search_q and hasattr(self.driver, "get_focused_api_records_summary"):
                api_context = self.driver.get_focused_api_records_summary(search_q)
        except Exception:
            api_context = ""

        passed, reason = self.vision.check_physics_sanity(
            instruction=prompt,
            base64_image=b64_img,
            dom_anomalies=dom_anomalies,
            api_context=api_context
        )

        if not passed:
            raise ActionRunnerException(f"🧪 物理常识与合理性断言不通过！原因: {reason}")

    def _do_assert_no_console_errors(self, prompt: str = "", strict: bool = False, reset: bool = False):
        """
        无声崩溃嗅探断言 (Silent Frontend Crash Sniffer)。
        高强度剔除前端日常非阻塞告警噪音，精准拦截 Uncaught TypeError/ReferenceError、
        Vue 渲染生命周期崩溃、ChunkLoadError、渲染进程 OOM 与 WebGL 上下文丢失。
        """
        if not hasattr(self.driver, "get_fatal_console_errors"):
            logger.warning("当前驱动未挂载 get_fatal_console_errors，跳过无声崩溃检查。")
            return

        if reset:
            cleared = self.driver.get_fatal_console_errors(clear=True, strict=strict)
            logger.info(f"🧹 [SilentCrashSniffer] 已清空历史崩溃基线缓冲 (共清理 {len(cleared)} 条旧记录)。")
            return

        crashes = self.driver.get_fatal_console_errors(clear=True, strict=strict)
        if not crashes:
            logger.info(f"🛡️ [SilentCrashSniffer] 无声崩溃嗅探通过 (strict={strict})：未检测到前端致命异常或 WebGL 崩溃。{(' - ' + prompt) if prompt else ''}")
            return

        formatted_lines = []
        for idx, c in enumerate(crashes[:10], 1):
            c_type = c.get("type", "js_crash")
            c_loc = f" @ {c['location']}" if c.get("location") else ""
            c_scope = f" [{c['page_scope']}]" if c.get("page_scope") and c.get("page_scope") != "_global_shared" else ""
            c_msg = str(c.get("msg") or c.get("text") or "").strip()[:300]
            formatted_lines.append(f"{idx}. [{c_type}{c_loc}]{c_scope} {c_msg}")

        detail_str = "\n".join(formatted_lines)
        logger.error(f"💥 [SilentCrashSniffer] 捕获到 {len(crashes)} 条前端无声致命崩溃:\n{detail_str}")
        raise ActionRunnerException(
            f"【前端无声致命崩溃】捕获到 {len(crashes)} 个未捕获 JS 运行时异常/WebGL 崩溃"
            f"{(' (' + prompt + ')') if prompt else ''}:\n{detail_str}"
        )

    def _do_canvas_stress_drag(
        self,
        prompt: str = "",
        mode: str = "hybrid",
        rounds: int = 3,
        radius: int = 300,
        button: str = "right",
        visual_assert: bool = True
    ):
        """
        执行 3D 场景暴力晃动抗压测试 (canvas_stress_drag)，并在结束后联合校验：
        1) WebRTC 像素流与 WebGL 上下文健康度；
        2) 无声致命前端崩溃池；
        3) 多模态视觉核验三维场景未出现黑屏、粉红棋盘格丢失材质或崩溃遮罩。
        """
        if hasattr(self.driver, "mark_action_timestamp"):
            self.driver.mark_action_timestamp()

        health = self.driver.canvas_stress_drag(
            mode=mode,
            rounds=rounds,
            radius=radius,
            button=button,
            delay_after=1.5
        )

        if not health.get("healthy", True):
            issues_str = "；".join(health.get("issues", []))
            raise ActionRunnerException(f"💥 3D 场景暴力晃动后底层流/WebGL 崩溃！详情: {issues_str}")

        # 联动检查暴力晃动期间是否诱发了前端无声致命 JS 崩溃
        if hasattr(self.driver, "get_fatal_console_errors"):
            fatal_errs = self.driver.get_fatal_console_errors(clear=True, strict=False)
            if fatal_errs:
                err_summary = "；".join(str(e.get("msg", ""))[:180] for e in fatal_errs[:5])
                raise ActionRunnerException(f"💥 3D 场景暴力晃动诱发前端致命运行时崩溃: {err_summary}")

        if visual_assert:
            b64_after = self.driver.capture_screenshot_base64()
            check_desc = (
                prompt.strip()
                if prompt and any(k in prompt for k in ["检查", "断言", "核验", "正常", "黑屏", "破面"])
                else "检查当前三维数字孪生矿山场景在剧烈旋转缩放压力测试后是否依然正常渲染，未出现纯黑屏、白屏、全粉色材质丢失、模型严重破面或推流断开报错弹窗"
            )
            passed, reason = self.vision.check_assertion(instruction=check_desc, base64_image=b64_after)
            if not passed:
                raise ActionRunnerException(f"💥 3D 场景暴力晃动后视觉健康度核验未通过！原因: {reason}")

    def _do_memory_leak_check(self, step: Dict[str, Any]):
        """
        显存/内存与 DOM/事件监听器泄漏探针步骤 (memory_leak_check)。
        支持两种模式：
        - mode: "baseline" -> 强制 GC 后将当前内存水位重设为基线（常用于高频压测循环开始前）；
        - mode: "assert" (默认) -> 强制 GC 后比对当前水位与基线，超阈值则抛出泄漏异常。
        """
        if not hasattr(self.driver, "check_memory_leak"):
            logger.warning("当前驱动未挂载 check_memory_leak，跳过内存探针检查。")
            return

        prompt = str(step.get("prompt", "") or "").strip()
        mode = str(step.get("mode", "assert") or "assert").strip().lower()
        label = prompt or f"step_{self._step_counter}_{mode}"
        trigger_gc = bool(step.get("trigger_gc", True))

        if mode in ("baseline", "reset"):
            self.driver.record_memory_snapshot(label=label, set_as_baseline=True, trigger_gc=trigger_gc)
            return

        max_heap_mb = float(step.get("max_heap_mb", 1024.0))
        max_growth_mb = float(step.get("max_growth_mb", 300.0))
        max_growth_ratio = float(step.get("max_growth_ratio", 2.5))
        max_dom_nodes = int(step.get("max_dom_nodes", 50000))
        max_listener_growth = int(step.get("max_listener_growth", 5000))

        passed, summary, _ = self.driver.check_memory_leak(
            label=label,
            max_heap_mb=max_heap_mb,
            max_growth_mb=max_growth_mb,
            max_growth_ratio=max_growth_ratio,
            max_dom_nodes=max_dom_nodes,
            max_listener_growth=max_listener_growth,
            trigger_gc=trigger_gc
        )
        if not passed:
            raise ActionRunnerException(f"🚨 显存/内存探针断言失败！{summary}")
