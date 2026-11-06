import asyncio
import datetime
import logging
import os
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import Dict, List, Optional, Set
import psutil

from .database import SessionLocal
from .models import TaskRun

logger = logging.getLogger("server.task_manager")
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 正则表达式识别控制台中的当前步数
RE_WORKER_STEP = re.compile(r"\(Global:\s*(\d+)/")
RE_RUNNER_STEP = re.compile(r"\[Step\s*(\d+)/")
RE_STEP_TAG = re.compile(r"explore_step_(\d+)")


class TaskManager:
    """自动化巡检进程中枢调度器 (管理任务生命周期、日志流与当前步数探针)"""

    def __init__(self):
        self.active_processes: Dict[str, subprocess.Popen] = {}
        self.log_buffers: Dict[str, List[str]] = {}
        self.current_steps: Dict[str, int] = {}
        self.websocket_subscribers: Dict[str, Set[asyncio.Queue]] = {}
        self._lock = threading.Lock()

    def get_current_step(self, task_id: str) -> Optional[int]:
        """获取任务当前正在执行的步数"""
        with self._lock:
            return self.current_steps.get(task_id)

    def start_task(self, task_id: str) -> bool:
        """从数据库拉取任务定义并拉起执行子进程与伴生性能采样引擎"""
        with self._lock:
            if task_id in self.active_processes:
                proc = self.active_processes[task_id]
                if proc.poll() is None:
                    logger.warning(f"任务 [{task_id}] 已在运行中 (PID: {proc.pid})")
                    return False

        db = SessionLocal()
        task: Optional[TaskRun] = None
        try:
            task = db.query(TaskRun).filter(TaskRun.id == task_id).first()
            if not task:
                logger.error(f"未找到任务记录: {task_id}")
                return False

            # 组装 CLI 命令行参数
            python_exe = sys.executable
            cmd = [python_exe, "main.py"]

            if task.mode == "explore":
                if getattr(task, "tour", False):
                    cmd.append("--tour")
                else:
                    cmd.extend(["--explore", task.macro_objective or "全量自主探索"])
                cmd.extend(["--max-steps", str(task.max_steps)])
                cmd.extend(["--max-times", str(task.max_times)])
                if task.reset_memory:
                    cmd.append("--reset-memory")
                if task.ignore_errors:
                    cmd.append("--ignore-errors")
                if task.explore_context:
                    cmd.extend(["--explore-context", task.explore_context])
                if getattr(task, "resume_from", None):
                    cmd.extend(["--resume-from", task.resume_from])
                if getattr(task, "reexplore", None):
                    cmd.extend(["--reexplore", task.reexplore])
                if getattr(task, "start_delay", None) is not None:
                    cmd.extend(["--start-delay", str(task.start_delay)])
                if getattr(task, "wait_ready", None):
                    cmd.extend(["--wait-ready", task.wait_ready])
                    if getattr(task, "wait_timeout", None) is not None:
                        cmd.extend(["--wait-timeout", str(task.wait_timeout)])
                if getattr(task, "ignore_env_check", False):
                    cmd.append("--ignore-env-check")

            elif task.mode in ("smoke", "tour"):
                # 兼容旧历史任务
                cmd.append("--tour")
                if task.ignore_errors:
                    cmd.append("--ignore-errors")

            elif task.mode == "case":
                if task.case_path:
                    cmd.extend(["--case", task.case_path])
                else:
                    cmd.append("--all")
                if task.ignore_errors:
                    cmd.append("--ignore-errors")
                if getattr(task, "start_delay", None) is not None:
                    cmd.extend(["--start-delay", str(task.start_delay)])
                if getattr(task, "wait_ready", None):
                    cmd.extend(["--wait-ready", task.wait_ready])
                    if getattr(task, "wait_timeout", None) is not None:
                        cmd.extend(["--wait-timeout", str(task.wait_timeout)])
                if getattr(task, "ignore_env_check", False):
                    cmd.append("--ignore-env-check")

            elif task.mode == "all":
                cmd.append("--all")
                if task.ignore_errors:
                    cmd.append("--ignore-errors")

            logger.info(f"🚀 拉起任务子进程 [{task_id}]: {' '.join(cmd)}")

            # 启动子进程，重定向标准输出和错误流
            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"
            if task.app_name:
                env["ACTIVE_APP"] = task.app_name
                env["VISION_ACTIVE_APP"] = task.app_name

            process = subprocess.Popen(
                cmd,
                cwd=str(PROJECT_ROOT),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1
            )

            # 更新任务数据库状态
            task.status = "running"
            task.pid = process.pid
            task.start_time = datetime.datetime.now()
            db.commit()

            with self._lock:
                self.active_processes[task_id] = process
                self.log_buffers[task_id] = []
                self.current_steps[task_id] = 0

            # 启动独立线程异步读取子进程日志流
            t = threading.Thread(
                target=self._log_monitor_worker,
                args=(task_id, process),
                daemon=True
            )
            t.start()

            # 自动挂载拉起全景性能监控探针 (UE + Chrome + CDP + GPU)
            try:
                from .performance_monitor import performance_monitor
                performance_monitor.start_monitoring(task_id, app_name=task.app_name, interval_sec=5.0)
            except Exception as e_perf:
                logger.warning(f"挂载性能监控探针失败 (不影响任务主干): {e_perf}")

            return True

        except Exception as e:
            logger.error(f"拉起任务 [{task_id}] 异常: {e}")
            if task:
                task.status = "failed"
                task.error_message = str(e)
                db.commit()
            return False
        finally:
            db.close()

    def _log_monitor_worker(self, task_id: str, process: subprocess.Popen):
        """异步消费并存储子进程日志输出，实时提取当前执行步骤"""
        logger.info(f"📖 日志监听线程启动 [{task_id}], PID: {process.pid}")
        try:
            for line in iter(process.stdout.readline, ""):
                if not line:
                    break
                line_str = line.rstrip()
                with self._lock:
                    buf = self.log_buffers.setdefault(task_id, [])
                    buf.append(line_str)
                    if len(buf) > 3000:
                        self.log_buffers[task_id] = buf[-3000:]

                    # 探测日志里的步数标记
                    m1 = RE_WORKER_STEP.search(line_str)
                    m2 = RE_RUNNER_STEP.search(line_str)
                    m3 = RE_STEP_TAG.search(line_str)
                    if m1:
                        self.current_steps[task_id] = int(m1.group(1))
                    elif m2:
                        self.current_steps[task_id] = int(m2.group(1))
                    elif m3:
                        self.current_steps[task_id] = int(m3.group(1))

                # 广播给该任务的 WebSocket 订阅队列
                self._broadcast_log(task_id, line_str)

        except Exception as e:
            logger.debug(f"读取任务 [{task_id}] 日志流中断: {e}")
        finally:
            process.stdout.close()
            exit_code = process.wait()
            logger.info(f"🏁 任务进程已退出 [{task_id}], Exit Code: {exit_code}")
            
            # 停止关联的后台性能采样引擎
            try:
                from .performance_monitor import performance_monitor
                performance_monitor.stop_monitoring(task_id)
            except Exception:
                pass

            self._finalize_task_run(task_id, exit_code)

    def _finalize_task_run(self, task_id: str, exit_code: int):
        """任务结束后的终态收尾与数据同步"""
        db = SessionLocal()
        try:
            task: Optional[TaskRun] = db.query(TaskRun).filter(TaskRun.id == task_id).first()
            if task:
                task.exit_code = exit_code
                task.end_time = datetime.datetime.now()
                if task.start_time:
                    delta = task.end_time - task.start_time
                    sec = int(delta.total_seconds())
                    h = sec // 3600
                    m = (sec % 3600) // 60
                    s = sec % 60
                    task.duration = f"{h}h {m}m {s}s" if h > 0 else f"{m}m {s}s"

                if task.status != "stopped":
                    task.status = "completed" if exit_code == 0 else "failed"

                # 尝试扫描最新的 reports/runs/zhaiwan 目录回填产物
                self._enrich_task_metrics_from_runs(task)
                db.commit()

        except Exception as e:
            logger.error(f"收尾任务 [{task_id}] 数据库记录异常: {e}")
        finally:
            with self._lock:
                self.active_processes.pop(task_id, None)
            db.close()

    def _enrich_task_metrics_from_runs(self, task: TaskRun):
        """从最新的运行目录报告中同步统计指标"""
        try:
            import json
            runs_data_path = PROJECT_ROOT / "reports" / "runs" / "runs_data.js"
            if runs_data_path.exists():
                text = runs_data_path.read_text(encoding="utf-8")
                prefix = "window.GLOBAL_RUNS_LIST = "
                if text.startswith(prefix):
                    clean_text = text[len(prefix):].rstrip().rstrip(";")
                    runs = json.loads(clean_text)
                    if runs:
                        latest = runs[0]
                        kpi = latest.get("kpi", {})
                        task.total_steps = kpi.get("total_steps", 0)
                        task.planner_phases = kpi.get("planner_phases", 0)
                        task.coverage_rate = float(kpi.get("page_coverage_rate", 0.0))
                        task.bugs_count = kpi.get("bugs_count", 0)
                        task.apis_count = kpi.get("apis_count", 0)
                        task.yaml_steps_count = kpi.get("yaml_steps_count", 0)
                        raw_report_url = latest.get("report_url", "")
                        # 规范化转换为以 /reports/runs/ 开头的绝对路径，防止相对路径在不同路由层级解析错位
                        if raw_report_url:
                            cleaned = raw_report_url.lstrip(".").lstrip("/")
                            task.report_url = f"/reports/runs/{cleaned}" if not cleaned.startswith("reports/") else f"/{cleaned}"
                        task.run_dir = latest.get("rel_path")
        except Exception as e:
            logger.debug(f"回填运行产物数据异常: {e}")

    def stop_task(self, task_id: str) -> bool:
        """优雅终止执行中的任务并停止性能监控守护进程"""
        # 1. 率先停止性能采集守护
        try:
            from .performance_monitor import performance_monitor
            performance_monitor.stop_monitoring(task_id)
        except Exception:
            pass

        proc = None
        with self._lock:
            proc = self.active_processes.get(task_id)

        if not proc or proc.poll() is not None:
            logger.warning(f"任务 [{task_id}] 未在运行或已退出")
            return False

        logger.info(f"🛑 正在优雅停止任务 [{task_id}] (PID: {proc.pid})...")

        # 2. 尝试使用 electron_launcher 广播 WM_CLOSE 原生退出信号
        try:
            from utils.electron_launcher import ElectronLauncher
            ElectronLauncher.dismiss_native_dialogs(proc.pid)
        except Exception:
            pass

        # 3. 通过 psutil 优雅终止整个进程树
        try:
            parent = psutil.Process(proc.pid)
            children = parent.children(recursive=True)
            for child in children:
                try:
                    child.terminate()
                except Exception:
                    pass
            parent.terminate()

            # 等待最多 5 秒
            gone, alive = psutil.wait_procs([parent] + children, timeout=5)
            for p in alive:
                try:
                    p.kill()
                except Exception:
                    pass

            db = SessionLocal()
            try:
                task = db.query(TaskRun).filter(TaskRun.id == task_id).first()
                if task:
                    task.status = "stopped"
                    task.end_time = datetime.datetime.now()
                    db.commit()
            finally:
                db.close()

            with self._lock:
                self.active_processes.pop(task_id, None)

            logger.info(f"✅ 任务 [{task_id}] 进程树已完全停止")
            return True

        except Exception as e:
            logger.error(f"停止任务 [{task_id}] 进程异常: {e}")
            return False

    def get_logs(self, task_id: str, tail: int = 200) -> List[str]:
        """获取任务当前的内存日志切片"""
        with self._lock:
            buf = self.log_buffers.get(task_id, [])
            return buf[-tail:] if tail > 0 else buf

    def subscribe_logs(self, task_id: str) -> asyncio.Queue:
        """创建针对特定任务的 WebSocket 日志广播通道"""
        queue = asyncio.Queue()
        with self._lock:
            subs = self.websocket_subscribers.setdefault(task_id, set())
            subs.add(queue)
        return queue

    def unsubscribe_logs(self, task_id: str, queue: asyncio.Queue):
        """移除 WebSocket 订阅"""
        with self._lock:
            subs = self.websocket_subscribers.get(task_id)
            if subs:
                subs.discard(queue)
                if not subs:
                    self.websocket_subscribers.pop(task_id, None)

    def _broadcast_log(self, task_id: str, line: str):
        """非阻塞广播日志"""
        with self._lock:
            subs = list(self.websocket_subscribers.get(task_id, []))
        for q in subs:
            try:
                q.put_nowait(line)
            except Exception:
                pass


task_manager = TaskManager()
