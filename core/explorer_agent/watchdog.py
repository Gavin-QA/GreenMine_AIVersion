import os
import sys
import time
import logging
import threading
import subprocess
from typing import Optional, Callable, Any

logger = logging.getLogger("explorer_agent.watchdog")

class StepWatchdog:
    """
    单步超时看门狗守护者 (Step-Level Deadlock Watchdog)
    
    职责：
    1. 在独立后台守护线程中实时监控 Worker 单步物理动作的执行耗时。
    2. 若单步耗时超过 timeout_sec（默认 90 秒），判定进入底层挂起（如被 Windows 系统模态弹窗、
       CDP 内部消息阻塞或死循环阻塞），立即发出严重警报。
    3. 自动触发脱困解冻动作：
       - 先发送系统级 Esc 尝试关闭阻塞对话框；
       - 若仍未恢复，强制回收假死 Electron 启动器进程，使主线程中阻塞的 Playwright 同步调用
         立即抛出异常脱困，不再无休止挂死一整夜！
    """

    def __init__(self, timeout_sec: float = 90.0, driver: Any = None):
        self.timeout_sec = float(timeout_sec)
        self.driver = driver
        self._step_start_time: Optional[float] = None
        self._step_desc: str = ""
        self._running = False
        self._triggered = False
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None

    def start(self):
        """启动后台看门狗监控守护线程"""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._triggered = False
            self._step_start_time = None
            self._thread = threading.Thread(
                target=self._monitor_loop,
                daemon=True,
                name="StepWatchdogThread"
            )
            self._thread.start()
            logger.info(f"🐕 [Step Watchdog] 单步死锁看门狗守护线程已就绪 (超时阈值: {self.timeout_sec:.0f}s)。")

    def stop(self):
        """停止看门狗线程"""
        with self._lock:
            self._running = False
            self._step_start_time = None

    def begin_step(self, step_desc: str = ""):
        """开始新的单步动作计时"""
        with self._lock:
            self._step_start_time = time.time()
            self._step_desc = step_desc
            self._triggered = False

    def end_step(self):
        """结束当前单步计时"""
        with self._lock:
            self._step_start_time = None
            self._step_desc = ""

    def is_triggered(self) -> bool:
        """检查看门狗是否已触发超时报警"""
        with self._lock:
            return self._triggered

    def _monitor_loop(self):
        while self._running:
            time.sleep(1.0)
            should_rescue = False
            desc_to_report = ""
            elapsed = 0.0

            with self._lock:
                if not self._running:
                    break
                if self._step_start_time is not None and not self._triggered:
                    elapsed = time.time() - self._step_start_time
                    if elapsed >= self.timeout_sec:
                        self._triggered = True
                        should_rescue = True
                        desc_to_report = self._step_desc

            if should_rescue:
                logger.critical(
                    f"\n{'='*70}\n"
                    f"🚨 [Watchdog Alert] 单步执行超时严重报警！\n"
                    f"   步骤: '{desc_to_report}'\n"
                    f"   耗时已达: {elapsed:.1f}s (已超过警戒线: {self.timeout_sec:.0f}s)\n"
                    f"   诊断: 判定被 Windows 系统原生模态弹窗、底座假死或网络调用阻塞挂起！\n"
                    f"   正在启动全自动解冻脱困动作...\n"
                    f"{'='*70}"
                )
                self._rescue_blocked_process()

    def _rescue_blocked_process(self):
        """执行系统级脱困与进程强破"""
        # 1. 尝试使用 PyAutoGUI 发送系统级 Escape 尝试关闭顶层模态窗 (如系统打印、文件选择框)
        try:
            import pyautogui
            pyautogui.press('esc')
            time.sleep(0.3)
            pyautogui.press('esc')
            time.sleep(0.5)
        except Exception:
            pass

        # 2. 终止卡死的目标进程，使主线程的 Playwright 同步阻塞立即抛出异常脱困
        try:
            exe_path = None
            if self.driver:
                if hasattr(self.driver, "launcher") and self.driver.launcher:
                    exe_path = getattr(self.driver.launcher, "exe_path", None)
                if not exe_path and hasattr(self.driver, "exe_path"):
                    exe_path = self.driver.exe_path

            if not exe_path:
                try:
                    from config.settings import settings
                    exe_path = getattr(settings, "app_path", "")
                except Exception:
                    pass

            if exe_path:
                exe_name = os.path.basename(exe_path)
                logger.warning(f"🔨 [Watchdog Rescue] 强制回收卡死的目标主进程 【{exe_name}】 以唤醒阻塞的执行主线程...")
                subprocess.run(["taskkill", "/F", "/IM", exe_name, "/T"], capture_output=True)
                time.sleep(0.5)

            # 同时回收伴生 UE 进程（若有配置），确保显存和端口完全清空
            try:
                from config.settings import settings
                ue_name = getattr(settings, "ue_process_name", None)
                if ue_name:
                    logger.warning(f"🔨 [Watchdog Rescue] 同步清理伴生引擎进程 【{ue_name}】...")
                    subprocess.run(["taskkill", "/F", "/IM", ue_name, "/T"], capture_output=True)
            except Exception:
                pass

            logger.info("✅ [Watchdog Rescue] 阻塞进程已强制终止，等待主线程捕获异常完成冷重启恢复。")
        except Exception as e:
            logger.error(f"❌ [Watchdog Rescue] 强制回收阻塞进程异常: {e}")
