import asyncio
import datetime
import json
import logging
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import psutil
import requests

from config.settings import settings
from .database import SessionLocal
from .models import PerformanceMetric, TaskRun

logger = logging.getLogger("server.performance_monitor")
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class PerformanceMonitor:
    """
    全景性能探针与异步采样守护引擎
    双核与全栈监控指标：
    1. UE5 伴生进程：CPU 占用率、物理内存 (RSS / Working Set)
    2. Chrome / Electron 进程树：CPU 占用率、内存占用
    3. Chromium CDP 实时协议直连 (零侵入/不干扰主 Playwright)：
       - DOM 节点数 (Nodes)
       - JS 事件监听器 (JSEventListeners)
       - V8 JSHeap 堆内存已用/总容量
       - 活跃 ECharts 图表实例数
       - Canvas 元素数
       - Video 标签数与 WebRTC 实时播放帧率 (FPS)
    4. 独立显卡 GPU 3D 渲染与 VRAM 显存负载 (nvidia-smi 极速解析)
    """

    def __init__(self):
        self._sampling_threads: Dict[str, threading.Thread] = {}
        self._stop_events: Dict[str, threading.Event] = {}
        self._cached_procs: Dict[int, psutil.Process] = {}
        self._cached_fps_state: Dict[str, Dict[str, float]] = {} # {task_or_app: {"frames": n, "time": t}}
        self._lock = threading.Lock()
        self._ws_subscribers: Dict[str, Set[asyncio.Queue]] = {}

    def get_app_config(self, app_name: str = "zhaiwan") -> Dict[str, Any]:
        """获取指定应用的配置 (端口、UE进程名、可执行文件等)"""
        apps_cfg = getattr(settings, "apps", {}) or {}
        if app_name in apps_cfg:
            return apps_cfg[app_name]
        return {
            "debug_port": getattr(settings, "debug_port", 9223),
            "ue_process_name": "zhaiwan.exe",
            "exe_path": ""
        }

    def _get_process_cpu_mem(self, proc: psutil.Process) -> Dict[str, float]:
        """安全采集单个进程的非阻塞 CPU 与内存 (MB)"""
        try:
            # interval=None 为非阻塞模式，依赖上次调用时间戳计算增量
            cpu = proc.cpu_percent(interval=None)
            mem_info = proc.memory_info()
            mem_mb = round(mem_info.rss / (1024 * 1024), 2)
            return {"cpu": cpu, "mem_mb": mem_mb, "alive": True}
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            return {"cpu": 0.0, "mem_mb": 0.0, "alive": False}

    def collect_ue_metrics(self, app_name: str = "zhaiwan") -> Dict[str, Any]:
        """采集 UE 伴生主进程及其引擎子进程的资源占用"""
        cfg = self.get_app_config(app_name)
        ue_target = cfg.get("ue_process_name", "zhaiwan.exe").lower()
        candidates: List[psutil.Process] = []

        for p in psutil.process_iter(['pid', 'name', 'exe']):
            try:
                pname = (p.info.get('name') or "").lower()
                if ue_target and (ue_target in pname or (ue_target.replace(".exe", "") in pname)):
                    candidates.append(p)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if not candidates:
            return {"ue_pid": None, "ue_cpu_percent": None, "ue_memory_mb": None}

        # 选出内存最大的为主 UE 进程 (UE5 Shipping 或 Launcher)
        main_ue = None
        max_rss = -1
        for p in candidates:
            try:
                rss = p.memory_info().rss
                if rss > max_rss:
                    max_rss = rss
                    main_ue = p
            except Exception:
                continue

        if not main_ue:
            return {"ue_pid": None, "ue_cpu_percent": None, "ue_memory_mb": None}

        # 缓存 Process 实例以保证 cpu_percent 准确非阻塞计算
        with self._lock:
            cached = self._cached_procs.get(main_ue.pid)
            if not cached or not cached.is_running():
                self._cached_procs[main_ue.pid] = main_ue
                cached = main_ue
                # 初次调用热身
                try:
                    cached.cpu_percent(interval=None)
                except Exception:
                    pass

            stats = self._get_process_cpu_mem(cached)

        return {
            "ue_pid": main_ue.pid,
            "ue_cpu_percent": stats["cpu"],
            "ue_memory_mb": stats["mem_mb"]
        }

    def collect_chrome_process_metrics(self, app_name: str = "zhaiwan") -> Dict[str, Any]:
        """采集 Electron / Chromium 渲染端进程树的 CPU 与总物理内存"""
        cfg = self.get_app_config(app_name)
        exe_path = cfg.get("exe_path", "")
        exe_stem = Path(exe_path).name.lower() if exe_path else ""

        chrome_procs: List[psutil.Process] = []
        for p in psutil.process_iter(['pid', 'name', 'exe']):
            try:
                pname = (p.info.get('name') or "").lower()
                pexe = (p.info.get('exe') or "").lower()
                if (exe_stem and exe_stem in pname) or "electron" in pname:
                    chrome_procs.append(p)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if not chrome_procs:
            return {"chrome_pid": None, "chrome_cpu_percent": None, "chrome_memory_mb": None}

        total_cpu = 0.0
        total_mem = 0.0
        main_pid = chrome_procs[0].pid

        for p in chrome_procs:
            with self._lock:
                cached = self._cached_procs.get(p.pid)
                if not cached or not cached.is_running():
                    self._cached_procs[p.pid] = p
                    cached = p
                    try:
                        cached.cpu_percent(interval=None)
                    except Exception:
                        pass
                stats = self._get_process_cpu_mem(cached)
                total_cpu += stats["cpu"]
                total_mem += stats["mem_mb"]

        return {
            "chrome_pid": main_pid,
            "chrome_cpu_percent": round(total_cpu, 2),
            "chrome_memory_mb": round(total_mem, 2)
        }

    def collect_gpu_metrics(self) -> Dict[str, Optional[float]]:
        """通过 Windows 无窗口静默调用 nvidia-smi 提取独立 GPU 3D 负载与显存"""
        cmd = [
            "nvidia-smi",
            "--query-gpu=utilization.gpu,memory.used",
            "--format=csv,noheader,nounits"
        ]
        # 使用 CREATE_NO_WINDOW (0x08000000) 确保不弹黑框干扰大屏
        creationflags = 0x08000000 if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=1.5,
                creationflags=creationflags
            )
            if res.returncode == 0 and res.stdout.strip():
                line = res.stdout.strip().splitlines()[0]
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 2:
                    return {
                        "gpu_usage_percent": float(parts[0]),
                        "gpu_memory_mb": float(parts[1])
                    }
        except Exception:
            pass
        return {"gpu_usage_percent": None, "gpu_memory_mb": None}

    def collect_cdp_metrics(self, app_name: str = "zhaiwan") -> Dict[str, Any]:
        """
        通过 CDP HTTP / WebSocket 直接读取底层 V8 JSHeap、DOM 树节点、Canvas 与 WebRTC FPS
        全程只读无害，绝对不刷新页面，不影响 WebRTC 流
        """
        cfg = self.get_app_config(app_name)
        port = cfg.get("debug_port", getattr(settings, "debug_port", 9223))
        json_url = f"http://127.0.0.1:{port}/json/list"

        empty_res = {
            "cdp_online": False,
            "page_scope": None,
            "dom_count": 0,
            "listeners_count": 0,
            "js_heap_mb": 0.0,
            "js_heap_total_mb": 0.0,
            "echarts_instances": 0,
            "canvas_count": 0,
            "video_instances": 0,
            "webrtc_fps": None
        }

        try:
            # 绕过系统网络代理直连 localhost
            resp = requests.get(json_url, timeout=1.5, proxies={"http": None, "https": None})
            if resp.status_code != 200:
                return empty_res

            pages = resp.json()
            if not pages:
                return empty_res

            # 优先寻找业务页面 (排除 devtools, background, about:blank 等)
            target_page = None
            for p in pages:
                p_url = p.get("url", "")
                p_type = p.get("type", "")
                if p_type == "page" and not p_url.startswith("devtools://") and not p_url.startswith("chrome-extension://"):
                    if "main.html" in p_url or "index.html" in p_url or "http" in p_url:
                        target_page = p
                        break
            if not target_page and pages:
                target_page = pages[0]

            ws_url = target_page.get("webSocketDebuggerUrl")
            if not ws_url:
                return empty_res

            from websockets.sync.client import connect

            with connect(ws_url, open_timeout=2.0, close_timeout=1.0) as ws:
                # 1. 采集原生 Performance.getMetrics (DOM Nodes, Listeners, JSHeap)
                ws.send(json.dumps({"id": 1, "method": "Performance.enable"}))
                _ = ws.recv()

                ws.send(json.dumps({"id": 2, "method": "Performance.getMetrics"}))
                metrics_res_raw = ws.recv()
                metrics_data = json.loads(metrics_res_raw).get("result", {}).get("metrics", [])
                
                metric_map = {m["name"]: m["value"] for m in metrics_data if "name" in m}
                nodes = int(metric_map.get("Nodes", 0))
                listeners = int(metric_map.get("JSEventListeners", 0))
                heap_used_mb = round(float(metric_map.get("JSHeapUsedSize", 0)) / (1024 * 1024), 2)
                heap_total_mb = round(float(metric_map.get("JSHeapTotalSize", 0)) / (1024 * 1024), 2)

                # 2. 采集前端组件与 WebRTC 动态指标
                eval_script = """
                (() => {
                    let echartsCount = 0;
                    try {
                        const echartsDomList = document.querySelectorAll('[_echarts_instance_]');
                        echartsCount = echartsDomList.length;
                    } catch (e) {}

                    const canvases = document.querySelectorAll('canvas').length;
                    const videos = document.querySelectorAll('video');
                    let totalPlayedFrames = 0;
                    
                    for (let i = 0; i < videos.length; i++) {
                        const v = videos[i];
                        if (typeof v.getVideoPlaybackQuality === 'function') {
                            const q = v.getVideoPlaybackQuality();
                            if (q && q.totalVideoFrames) {
                                totalPlayedFrames += q.totalVideoFrames;
                            }
                        }
                    }

                    let scope = window.location.hash || window.location.pathname || 'unknown';
                    return {
                        echarts: echartsCount,
                        canvas: canvases,
                        video: videos.length,
                        frames: totalPlayedFrames,
                        scope: scope
                    };
                })()
                """
                ws.send(json.dumps({
                    "id": 3,
                    "method": "Runtime.evaluate",
                    "params": {"expression": eval_script, "returnByValue": True}
                }))
                eval_raw = ws.recv()
                eval_val = json.loads(eval_raw).get("result", {}).get("result", {}).get("value", {})

                # 计算 WebRTC 实时播放帧率 (FPS)
                now_t = time.time()
                current_frames = eval_val.get("frames", 0)
                fps = None
                fps_key = f"{app_name}_{target_page.get('id', 'main')}"

                prev_state = self._cached_fps_state.get(fps_key)
                if prev_state and prev_state.get("time") and (now_t - prev_state["time"] > 0.5):
                    dt = now_t - prev_state["time"]
                    dframes = current_frames - prev_state["frames"]
                    if dframes >= 0:
                        fps = round(dframes / dt, 1)

                self._cached_fps_state[fps_key] = {"frames": current_frames, "time": now_t}

                return {
                    "cdp_online": True,
                    "page_scope": eval_val.get("scope"),
                    "dom_count": nodes,
                    "listeners_count": listeners,
                    "js_heap_mb": heap_used_mb,
                    "js_heap_total_mb": heap_total_mb,
                    "echarts_instances": eval_val.get("echarts", 0),
                    "canvas_count": eval_val.get("canvas", 0),
                    "video_instances": eval_val.get("video", 0),
                    "webrtc_fps": fps
                }

        except Exception as e:
            logger.debug(f"[PerformanceMonitor] CDP 通信跳过或目标离线: {e}")
            return empty_res

    def collect_full_snapshot(self, app_name: str = "zhaiwan") -> Dict[str, Any]:
        """采集一次跨核全栈性能切片 (UE + Chrome + CDP + GPU)"""
        now = datetime.datetime.utcnow()
        ue_data = self.collect_ue_metrics(app_name)
        chrome_data = self.collect_chrome_process_metrics(app_name)
        gpu_data = self.collect_gpu_metrics()
        cdp_data = self.collect_cdp_metrics(app_name)

        return {
            "app_name": app_name,
            "timestamp": now,
            "cdp_online": cdp_data.get("cdp_online", False),
            "ue_online": bool(ue_data.get("ue_pid")),
            "gpu_online": gpu_data.get("gpu_usage_percent") is not None,
            "page_scope": cdp_data.get("page_scope"),
            "dom_count": cdp_data.get("dom_count", 0),
            "listeners_count": cdp_data.get("listeners_count", 0),
            "js_heap_mb": cdp_data.get("js_heap_mb", 0.0),
            "js_heap_total_mb": cdp_data.get("js_heap_total_mb", 0.0),
            "echarts_instances": cdp_data.get("echarts_instances", 0),
            "canvas_count": cdp_data.get("canvas_count", 0),
            "video_instances": cdp_data.get("video_instances", 0),
            "webrtc_fps": cdp_data.get("webrtc_fps"),
            "chrome_pid": chrome_data.get("chrome_pid"),
            "chrome_cpu_percent": chrome_data.get("chrome_cpu_percent"),
            "chrome_memory_mb": chrome_data.get("chrome_memory_mb"),
            "ue_pid": ue_data.get("ue_pid"),
            "ue_cpu_percent": ue_data.get("ue_cpu_percent"),
            "ue_memory_mb": ue_data.get("ue_memory_mb"),
            "gpu_usage_percent": gpu_data.get("gpu_usage_percent"),
            "gpu_memory_mb": gpu_data.get("gpu_memory_mb")
        }

    # =========================================================================
    # 异步后台采样与 WebSocket 实时广播频道
    # =========================================================================

    def start_monitoring(self, task_id: str, app_name: str = "zhaiwan", interval_sec: float = 5.0):
        """为指定任务拉起后台性能采样守护线程"""
        with self._lock:
            if task_id in self._sampling_threads and self._sampling_threads[task_id].is_alive():
                logger.warning(f"任务 [{task_id}] 性能监控线程已在运行中")
                return

            stop_event = threading.Event()
            self._stop_events[task_id] = stop_event

            thread = threading.Thread(
                target=self._sampling_worker,
                args=(task_id, app_name, interval_sec, stop_event),
                name=f"PerfMonitor-{task_id}",
                daemon=True
            )
            self._sampling_threads[task_id] = thread
            thread.start()
            logger.info(f"📊 任务 [{task_id}] 性能监控后台守护引擎已激活 (采样周期: {interval_sec}s)")

    def stop_monitoring(self, task_id: str):
        """停止任务的性能采样线程"""
        with self._lock:
            stop_event = self._stop_events.get(task_id)
            if stop_event:
                stop_event.set()
            thread = self._sampling_threads.get(task_id)

        if thread and thread.is_alive():
            thread.join(timeout=2.0)

        with self._lock:
            self._stop_events.pop(task_id, None)
            self._sampling_threads.pop(task_id, None)
            logger.info(f"🛑 任务 [{task_id}] 性能监控后台守护引擎已平稳收尾")

    def _sampling_worker(self, task_id: str, app_name: str, interval: float, stop_event: threading.Event):
        """性能采样循环，写入数据库并推流给前端 WebSocket"""
        from .task_manager import task_manager

        while not stop_event.is_set():
            try:
                snapshot = self.collect_full_snapshot(app_name=app_name)
                current_step = task_manager.get_current_step(task_id)

                # 持久化入库
                db = SessionLocal()
                try:
                    metric = PerformanceMetric(
                        task_id=task_id,
                        timestamp=snapshot["timestamp"],
                        step_number=current_step,
                        page_scope=snapshot.get("page_scope"),
                        dom_count=snapshot["dom_count"],
                        listeners_count=snapshot["listeners_count"],
                        js_heap_mb=snapshot["js_heap_mb"],
                        js_heap_total_mb=snapshot["js_heap_total_mb"],
                        echarts_instances=snapshot["echarts_instances"],
                        canvas_count=snapshot["canvas_count"],
                        video_instances=snapshot["video_instances"],
                        webrtc_fps=snapshot["webrtc_fps"],
                        chrome_pid=snapshot["chrome_pid"],
                        chrome_cpu_percent=snapshot["chrome_cpu_percent"],
                        chrome_memory_mb=snapshot["chrome_memory_mb"],
                        ue_pid=snapshot["ue_pid"],
                        ue_cpu_percent=snapshot["ue_cpu_percent"],
                        ue_memory_mb=snapshot["ue_memory_mb"],
                        gpu_usage_percent=snapshot["gpu_usage_percent"],
                        gpu_memory_mb=snapshot["gpu_memory_mb"]
                    )
                    db.add(metric)
                    db.commit()
                    db.refresh(metric)
                    metric_dict = {
                        "id": metric.id,
                        "task_id": task_id,
                        "timestamp": metric.timestamp.isoformat(),
                        "step_number": metric.step_number,
                        "page_scope": metric.page_scope,
                        "dom_count": metric.dom_count,
                        "listeners_count": metric.listeners_count,
                        "js_heap_mb": metric.js_heap_mb,
                        "js_heap_total_mb": metric.js_heap_total_mb,
                        "echarts_instances": metric.echarts_instances,
                        "canvas_count": metric.canvas_count,
                        "video_instances": metric.video_instances,
                        "webrtc_fps": metric.webrtc_fps,
                        "chrome_pid": metric.chrome_pid,
                        "chrome_cpu_percent": metric.chrome_cpu_percent,
                        "chrome_memory_mb": metric.chrome_memory_mb,
                        "ue_pid": metric.ue_pid,
                        "ue_cpu_percent": metric.ue_cpu_percent,
                        "ue_memory_mb": metric.ue_memory_mb,
                        "gpu_usage_percent": metric.gpu_usage_percent,
                        "gpu_memory_mb": metric.gpu_memory_mb
                    }
                finally:
                    db.close()

                # 推送给 WebSocket 订阅者
                self._broadcast_metric(task_id, metric_dict)

            except Exception as e:
                logger.debug(f"[PerformanceMonitor] 采样周期异常: {e}")

            stop_event.wait(timeout=interval)

    def subscribe_metrics(self, task_id: str) -> asyncio.Queue:
        """创建针对特定任务的实时性能推流通道"""
        queue = asyncio.Queue()
        with self._lock:
            subs = self._ws_subscribers.setdefault(task_id, set())
            subs.add(queue)
        return queue

    def unsubscribe_metrics(self, task_id: str, queue: asyncio.Queue):
        """取消性能推流通道订阅"""
        with self._lock:
            subs = self._ws_subscribers.get(task_id)
            if subs:
                subs.discard(queue)
                if not subs:
                    self._ws_subscribers.pop(task_id, None)

    def _broadcast_metric(self, task_id: str, data: Dict[str, Any]):
        """异步广播性能指标给所有前端 ECharts 订阅端"""
        with self._lock:
            subs = list(self._ws_subscribers.get(task_id, []))
        for q in subs:
            try:
                q.put_nowait(data)
            except Exception:
                pass


performance_monitor = PerformanceMonitor()
