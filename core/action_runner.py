import logging
import time
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.browser import ElectronDriver
from core.vision.agent import VisionAgent, VisionAgentException
from utils.artifacts import screenshot_path

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

        errors = []
        for i, step in enumerate(steps, 1):
            self._step_counter = i
            # 在步骤开始前加入一个换行符，以便在日志中形成视觉分隔
            logger.info(f"\n--- [Step {i}/{len(steps)}] 类型: {step.get('type')} ---")
            
            try:
                self._execute_step(step)
            except Exception as e:
                # 出现异常时，立刻留存案发现场截图
                crash_pic = screenshot_path(f"{path.stem}_CRASH_step_{i}")
                self.driver.capture_screenshot(str(crash_pic))
                logger.error(f"❌ 步骤 {i} 执行失败！现场已保存: {crash_pic}")
                logger.error(f"异常详情: {e}")
                
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

    def _execute_step(self, step: Dict[str, Any], max_retries: int = 1):
        """
        分发执行单步指令，自带重试机制以应对页面元素加载延迟。
        """
        step_type = step.get("type")
        prompt = step.get("prompt", "")

        for attempt in range(max_retries + 1):
            try:
                if step_type == "action":
                    self._do_action(prompt)
                elif step_type == "input":
                    text = step.get("text")
                    if not text:
                        raise ValueError("input 类型的步骤必须提供 'text' 字段。")
                    self._do_input(prompt, str(text))
                elif step_type == "assert":
                    self._do_assert(prompt)
                elif step_type == "api_assert":
                    self._do_api_assert(prompt)
                elif step_type == "freeze_check":
                    wait_sec = float(step.get("wait_seconds", 5.0))
                    self._do_freeze_check(prompt, wait_sec)
                elif step_type == "wait_for":
                    timeout = float(step.get("timeout", 60.0))
                    interval = float(step.get("interval", 3.0))
                    self._do_wait_for(prompt, timeout, interval)
                elif step_type == "wait":
                    wait_sec = float(step.get("seconds", 2.0))
                    self.driver.wait(wait_sec)
                else:
                    logger.warning(f"未知步骤类型: {step_type}，跳过执行。")
                
                # 如果没有抛出异常，说明执行成功，跳出重试循环
                break
                
            except VisionAgentException as ve:
                if attempt < max_retries:
                    logger.warning(f"AI 未找到目标或断言失败，等待 3 秒后重试 (第 {attempt+1}/{max_retries} 次重试)... 异常: {ve}")
                    time.sleep(3.0)
                else:
                    logger.error("已达到最大重试次数，任务中断。")
                    raise

    def _do_action(self, prompt: str):
        """执行视觉动作 (支持自动解析 [HOVER]/[CLICK] 前缀)"""
        # 1. Perception
        b64_img = self.driver.capture_screenshot_base64()
        viewport = self.driver.get_viewport_info()
        dom_elements = self.driver.extract_interactive_elements()
        
        # 解析动作类型 (支持 ExplorerAgent 自动生成的 [HOVER] / [CLICK] 前缀)
        action_type = "click"
        prompt_upper = prompt.strip().upper()
        if prompt_upper.startswith("[HOVER]"):
            action_type = "hover"
            prompt = prompt.strip()[7:].strip()
        elif prompt_upper.startswith("[CLICK]"):
            action_type = "click"
            prompt = prompt.strip()[7:].strip()
            
        # 2. Cognition
        x, y = self.vision.find_element(
            instruction=prompt,
            base64_image=b64_img,
            viewport_width=viewport["width"],
            viewport_height=viewport["height"],
            dom_elements=dom_elements
        )
        
        # 3. Action
        if action_type == "hover":
            self.driver.hover(x, y)
        else:
            self.driver.click(x, y)

    def _do_input(self, prompt: str, text: str):
        """执行视觉点击后输入文本"""
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
        self.driver.click(x, y)
        self.driver.type_text(text)

    def _do_assert(self, prompt: str):
        """执行单次视觉断言"""
        b64_img = self.driver.capture_screenshot_base64()
        passed, reason = self.vision.check_assertion(instruction=prompt, base64_image=b64_img)
        
        if not passed:
            raise ActionRunnerException(f"视觉断言失败！理由: {reason}")

    def _do_api_assert(self, prompt: str):
        """执行 API 接口与视觉双重断言"""
        b64_img = self.driver.capture_screenshot_base64()
        api_data_json = self.driver.get_api_records_summary()
        
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

