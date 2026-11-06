import asyncio
import datetime
import json
import logging
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
import collections
import psutil
import requests

from config.settings import settings
from utils.system_guard import SystemMemoryGuard
from .database import SessionLocal
from .models import PerformanceMetric, TaskRun, AmbientMetric

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
        self._cached_gpu: Dict[str, Any] = {"time": 0.0, "data": {"gpu_usage_percent": None, "gpu_memory_mb": None}}
        self._ambient_thread: Optional[threading.Thread] = None
        self._ambient_stop_event = threading.Event()
        self._ambient_buffers: Dict[str, collections.deque] = {}
        self._ambient_offline_skip: Dict[str, int] = {}

    def get_app_config(self, app_name: str = "zhaiwan") -> Dict[str, Any]:
        """获取指定应用的配置 (端口、UE进程名、可执行文件等)"""
        cfg = settings.get_app_config(app_name)
        if cfg:
            return cfg
        apps_cfg = getattr(settings, "apps", {}) or {}
        if app_name in apps_cfg:
            return apps_cfg[app_name]
        return {
            "debug_port": getattr(settings, "debug_port", 9223),
            "ue_process_name": f"{app_name}.exe" if app_name else "zhaiwan.exe",
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

    def collect_ue_metrics(self, app_name: str = "zhaiwan", allow_fallback: bool = False) -> Dict[str, Any]:
        """采集 UE 伴生主进程及其引擎子进程的资源占用 (支持分项目精确匹配，彻底杜绝跨应用数据串线)"""
        cfg = self.get_app_config(app_name)
        ue_target = cfg.get("ue_process_name", f"{app_name}.exe").lower()
        exe_path = cfg.get("exe_path", "")
        exe_stem = Path(exe_path).name.lower() if exe_path else ""
        app_keyword = app_name.lower()

        candidates: List[psutil.Process] = []

        for p in psutil.process_iter(['pid', 'name', 'exe']):
            try:
                pname = (p.info.get('name') or "").lower()
                pexe = (p.info.get('exe') or "").lower()
                # 严格匹配目标 UE 进程或该矿山专属 launcher 进程，绝不借用其他矿山进程
                is_match = False
                if ue_target and (ue_target in pname or ue_target.replace(".exe", "") in pname):
                    is_match = True
                elif exe_stem and exe_stem in pname:
                    is_match = True
                elif app_keyword in pexe and ("se-launcher" in pname or app_keyword in pname):
                    is_match = True

                if is_match:
                    candidates.append(p)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if not candidates:
            return {"ue_pid": None, "ue_cpu_percent": None, "ue_cpu_raw_percent": None, "ue_memory_mb": None, "ue_commit_mb": None}

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
            return {"ue_pid": None, "ue_cpu_percent": None, "ue_cpu_raw_percent": None, "ue_memory_mb": None, "ue_commit_mb": None}

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

        # 穿透采集底层专用提交量 (Private Bytes / Commit)，精准捕获虚拟内存泄漏
        detailed_mem = SystemMemoryGuard.get_process_detailed_memory(main_ue.pid)
        ue_commit_mb = detailed_mem.get("private_mb", 0.0)

        logical_cores = psutil.cpu_count(logical=True) or 1
        raw_cpu = stats["cpu"]
        normalized_cpu = round(raw_cpu / logical_cores, 2) if raw_cpu is not None else None

        return {
            "ue_pid": main_ue.pid,
            "ue_cpu_percent": normalized_cpu,
            "ue_cpu_raw_percent": round(raw_cpu, 2) if raw_cpu is not None else None,
            "ue_memory_mb": stats["mem_mb"],
            "ue_commit_mb": ue_commit_mb,
            "cpu_cores": logical_cores
        }

    def collect_chrome_process_metrics(self, app_name: str = "zhaiwan") -> Dict[str, Any]:
        """采集 Electron / Chromium 渲染端进程树的 CPU 与总物理内存 (严格分应用归属)"""
        cfg = self.get_app_config(app_name)
        exe_path = cfg.get("exe_path", "")
        exe_stem = Path(exe_path).name.lower() if exe_path else ""
        app_keyword = app_name.lower()

        chrome_procs: List[psutil.Process] = []
        for p in psutil.process_iter(['pid', 'name', 'exe']):
            try:
                pname = (p.info.get('name') or "").lower()
                pexe = (p.info.get('exe') or "").lower()
                is_chrome = False
                if exe_stem and exe_stem in pname:
                    is_chrome = True
                elif app_keyword in pexe and ("se-launcher" in pname or "electron" in pname or app_keyword in pname):
                    is_chrome = True
                if is_chrome:
                    chrome_procs.append(p)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if not chrome_procs:
            return {"chrome_pid": None, "chrome_cpu_percent": None, "chrome_cpu_raw_percent": None, "chrome_memory_mb": None}

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

        logical_cores = psutil.cpu_count(logical=True) or 1
        normalized_cpu = round(total_cpu / logical_cores, 2)

        return {
            "chrome_pid": main_pid,
            "chrome_cpu_percent": normalized_cpu,
            "chrome_cpu_raw_percent": round(total_cpu, 2),
            "chrome_memory_mb": round(total_mem, 2),
            "cpu_cores": logical_cores
        }

    def collect_gpu_metrics(self) -> Dict[str, Optional[float]]:
        """通过 Windows 无窗口静默调用 nvidia-smi 提取独立 GPU 3D 负载与显存 (带极速本地缓存)"""
        with self._lock:
            if time.time() - self._cached_gpu["time"] < 2.5 and self._cached_gpu["data"].get("gpu_usage_percent") is not None:
                return self._cached_gpu["data"]

        cmd = [
            "nvidia-smi",
            "--query-gpu=utilization.gpu,memory.used",
            "--format=csv,noheader,nounits"
        ]
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
                    res_dict = {
                        "gpu_usage_percent": float(parts[0]),
                        "gpu_memory_mb": float(parts[1])
                    }
                    with self._lock:
                        self._cached_gpu = {"time": time.time(), "data": res_dict}
                    return res_dict
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

        # 项目专属身份特征签名 (解决共用 9223 端口时的张冠李戴串线 Bug)
        app_signatures = {
            "zhaiwan": ["zhaiwan", "寨湾"],
            "liwutong": ["liwutong", "里伍", "里伍铜"],
            "tianrui": ["tianrui", "天瑞", "四川天瑞"]
        }
        signatures = app_signatures.get(app_name, [app_name.lower()])

        try:
            # 绕过系统网络代理直连 localhost
            resp = requests.get(json_url, timeout=1.5, proxies={"http": None, "https": None})
            if resp.status_code != 200:
                return empty_res

            pages = resp.json()
            if not pages:
                return empty_res

            # 严格验明正身：优先寻找业务页面，且该页面必须归属于当前 app_name
            target_page = None
            for p in pages:
                p_url = (p.get("url") or "").lower()
                p_title = (p.get("title") or "").lower()
                p_type = p.get("type", "")
                if p_type == "page" and not p_url.startswith("devtools://") and not p_url.startswith("chrome-extension://"):
                    belongs_to_app = any(sig in p_url or sig in p_title for sig in signatures)
                    if belongs_to_app and ("main.html" in p_url or "index.html" in p_url or "http" in p_url):
                        target_page = p
                        break
                    elif belongs_to_app and not target_page:
                        target_page = p

            # 若 9223 端口中无归属当前 app_name 的业务页面，坚决判定该应用 CDP 离线，严禁跨项目串线
            if not target_page:
                return empty_res

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

    def collect_host_memory_metrics(self) -> Dict[str, Any]:
        """采集 Windows 宿主机物理内存与专用虚拟提交量 (Commit) 整体负荷水位"""
        host_mem = SystemMemoryGuard.get_host_memory_status()
        if not host_mem.get("available"):
            return {
                "host_ram_load_percent": None,
                "host_commit_load_percent": None,
                "host_commit_avail_gb": None,
            }
        return {
            "host_ram_load_percent": float(host_mem.get("load_percent", 0)),
            "host_commit_load_percent": float(host_mem.get("commit_load_percent", 0)),
            "host_commit_avail_gb": float(host_mem.get("commit_avail_gb", 0.0)),
        }

    def collect_full_snapshot(self, app_name: str = "zhaiwan", allow_fallback: bool = False) -> Dict[str, Any]:
        """采集一次跨核全栈性能切片 (UE + Chrome + CDP + GPU + Host Commit)"""
        now = datetime.datetime.utcnow()
        logical_cores = psutil.cpu_count(logical=True) or 1
        ue_data = self.collect_ue_metrics(app_name, allow_fallback=allow_fallback)
        chrome_data = self.collect_chrome_process_metrics(app_name)
        gpu_data = self.collect_gpu_metrics()
        cdp_data = self.collect_cdp_metrics(app_name)
        host_mem_data = self.collect_host_memory_metrics()

        return {
            "app_name": app_name,
            "timestamp": now,
            "cpu_cores": logical_cores,
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
            "chrome_cpu_raw_percent": chrome_data.get("chrome_cpu_raw_percent"),
            "chrome_memory_mb": chrome_data.get("chrome_memory_mb"),
            "ue_pid": ue_data.get("ue_pid"),
            "ue_cpu_percent": ue_data.get("ue_cpu_percent"),
            "ue_cpu_raw_percent": ue_data.get("ue_cpu_raw_percent"),
            "ue_memory_mb": ue_data.get("ue_memory_mb"),
            "ue_commit_mb": ue_data.get("ue_commit_mb"),
            "host_ram_load_percent": host_mem_data.get("host_ram_load_percent"),
            "host_commit_load_percent": host_mem_data.get("host_commit_load_percent"),
            "host_commit_avail_gb": host_mem_data.get("host_commit_avail_gb"),
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
                        ue_commit_mb=snapshot.get("ue_commit_mb"),
                        host_ram_load_percent=snapshot.get("host_ram_load_percent"),
                        host_commit_load_percent=snapshot.get("host_commit_load_percent"),
                        gpu_usage_percent=snapshot["gpu_usage_percent"],
                        gpu_memory_mb=snapshot["gpu_memory_mb"]
                    )
                    db.add(metric)
                    db.commit()
                    db.refresh(metric)
                    metric_dict = {
                        "id": metric.id,
                        "task_id": task_id,
                        "timestamp": (metric.timestamp.isoformat() + "Z") if not metric.timestamp.isoformat().endswith("Z") else metric.timestamp.isoformat(),
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
                        "ue_commit_mb": metric.ue_commit_mb,
                        "host_ram_load_percent": metric.host_ram_load_percent,
                        "host_commit_load_percent": metric.host_commit_load_percent,
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

    def cleanup_expired_metrics(self, retention_days: int = 7) -> int:
        """
        正式测试任务性能资产安全守护说明：
        根据业务要求，用户每天执行的正式巡检与长周期回归测试任务（如 14 小时压测等）
        属于必须永久保全的测试缺陷与复盘资产，永久保留不自动清理。
        """
        logger.info("🛡️ [PerformanceMonitor] 正式测试任务性能资产永久保全 (不自动清理)")
        return 0

    def cleanup_expired_ambient_metrics(self, hours: int = 24) -> int:
        """
        环境实时时序数据滚动清理机制：
        只保留最近 24 小时内的环境实时心电图打点，超过 24 小时的自动滚动剔除，保障轻量零负担。
        - 仅清理 ambient_metrics 表中的实时数据；
        - 正式测试任务 (14小时+任务) 的 performance_metrics 永久保留，绝不清理！
        """
        db = SessionLocal()
        deleted_count = 0
        try:
            cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=hours)
            deleted_count = db.query(AmbientMetric).filter(AmbientMetric.timestamp < cutoff).delete(synchronize_session=False)
            db.commit()
            if deleted_count > 0:
                logger.info(f"🧹 [AmbientMonitor] 滚动清理完成：已自动清除 {deleted_count} 条超过 {hours} 小时的环境心电图打点")
            return deleted_count
        except Exception as e:
            db.rollback()
            logger.error(f"❌ [AmbientMonitor] 清理环境时序异常: {e}")
            return 0
        finally:
            db.close()

    def start_ambient_monitoring(self, interval_sec: float = 4.0):
        """拉起后台常驻环境监控守护线程，静默记录已运行应用的 24 小时心电图"""
        with self._lock:
            if self._ambient_thread and self._ambient_thread.is_alive():
                logger.info("⚡ [AmbientMonitor] 环境监控常驻守护线程已在运行中")
                return

            self._ambient_stop_event.clear()
            thread = threading.Thread(
                target=self._ambient_worker,
                args=(interval_sec,),
                name="PerfMonitor-AmbientDaemon",
                daemon=True
            )
            self._ambient_thread = thread
            thread.start()
            logger.info(f"📊 [AmbientMonitor] 环境监控常驻守护线程已激活 (心跳周期: {interval_sec}s，自动分项目隔离采样)")

    def stop_ambient_monitoring(self):
        """停止后台常驻环境监控守护线程"""
        with self._lock:
            self._ambient_stop_event.set()
            thread = self._ambient_thread
        if thread and thread.is_alive():
            thread.join(timeout=2.0)
        logger.info("🛑 [AmbientMonitor] 环境监控常驻守护线程已停止")

    def _warmup_ambient_buffers(self):
        """服务冷启动时，从 DB 预热最近 24 小时的数据到内存环形缓冲区，确保图表瞬间充满数据"""
        db = SessionLocal()
        try:
            cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=24)
            records = db.query(AmbientMetric).filter(AmbientMetric.timestamp >= cutoff).order_by(AmbientMetric.timestamp.asc()).all()
            with self._lock:
                for r in records:
                    app = r.app_name
                    if app not in self._ambient_buffers:
                        self._ambient_buffers[app] = collections.deque(maxlen=17280)
                    ts_str = r.timestamp.isoformat()
                    if not ts_str.endswith("Z"):
                        ts_str += "Z"
                    self._ambient_buffers[app].append({
                        "app_name": app,
                        "timestamp": ts_str,
                        "page_scope": r.page_scope,
                        "dom_count": r.dom_count or 0,
                        "listeners_count": r.listeners_count or 0,
                        "js_heap_mb": r.js_heap_mb or 0.0,
                        "js_heap_total_mb": r.js_heap_total_mb or 0.0,
                        "echarts_instances": r.echarts_instances or 0,
                        "canvas_count": r.canvas_count or 0,
                        "video_instances": r.video_instances or 0,
                        "webrtc_fps": r.webrtc_fps,
                        "chrome_pid": r.chrome_pid,
                        "chrome_cpu_percent": r.chrome_cpu_percent,
                        "chrome_memory_mb": r.chrome_memory_mb,
                        "ue_pid": r.ue_pid,
                        "ue_cpu_percent": r.ue_cpu_percent,
                        "ue_memory_mb": r.ue_memory_mb,
                        "ue_commit_mb": r.ue_commit_mb,
                        "host_ram_load_percent": r.host_ram_load_percent,
                        "host_commit_load_percent": r.host_commit_load_percent,
                        "host_commit_avail_gb": r.host_commit_avail_gb,
                        "gpu_usage_percent": r.gpu_usage_percent,
                        "gpu_memory_mb": r.gpu_memory_mb,
                    })
            if records:
                logger.info(f"🔥 [AmbientMonitor] 已成功预热 {len(records)} 条历史实时指标到内存环形队列")
        except Exception as e:
            logger.debug(f"[AmbientMonitor] 预热历史数据异常 (可忽略): {e}")
        finally:
            db.close()

    def _ambient_worker(self, interval_sec: float = 4.0):
        """常驻环境守护采样循环：即使未启动测试任务，也在后台静默记录已运行应用的 24 小时心电图"""
        self._warmup_ambient_buffers()
        cleanup_counter = 0

        while not self._ambient_stop_event.is_set():
            try:
                apps_cfg = getattr(settings, "apps", {}) or {}
                target_apps = list(apps_cfg.keys()) if apps_cfg else ["zhaiwan", "tianrui", "liwutong"]

                for app_name in target_apps:
                    snapshot = self.collect_full_snapshot(app_name=app_name)
                    ue_online = snapshot.get("ue_online", False)
                    cdp_online = snapshot.get("cdp_online", False)

                    # 离线应用退避策略：若应用离线，每隔 8 次周期 (约 32 秒) 记录一次离线点
                    if not ue_online and not cdp_online:
                        skip_count = self._ambient_offline_skip.get(app_name, 0) + 1
                        self._ambient_offline_skip[app_name] = skip_count
                        if skip_count < 8:
                            continue
                        self._ambient_offline_skip[app_name] = 0
                    else:
                        self._ambient_offline_skip[app_name] = 0

                    ts = snapshot["timestamp"]
                    ts_str = ts.isoformat() + "Z" if not ts.isoformat().endswith("Z") else ts.isoformat()

                    point = {
                        "app_name": app_name,
                        "timestamp": ts_str,
                        "page_scope": snapshot.get("page_scope"),
                        "dom_count": snapshot.get("dom_count", 0),
                        "listeners_count": snapshot.get("listeners_count", 0),
                        "js_heap_mb": snapshot.get("js_heap_mb", 0.0),
                        "js_heap_total_mb": snapshot.get("js_heap_total_mb", 0.0),
                        "echarts_instances": snapshot.get("echarts_instances", 0),
                        "canvas_count": snapshot.get("canvas_count", 0),
                        "video_instances": snapshot.get("video_instances", 0),
                        "webrtc_fps": snapshot.get("webrtc_fps"),
                        "chrome_pid": snapshot.get("chrome_pid"),
                        "chrome_cpu_percent": snapshot.get("chrome_cpu_percent"),
                        "chrome_memory_mb": snapshot.get("chrome_memory_mb"),
                        "ue_pid": snapshot.get("ue_pid"),
                        "ue_cpu_percent": snapshot.get("ue_cpu_percent"),
                        "ue_memory_mb": snapshot.get("ue_memory_mb"),
                        "ue_commit_mb": snapshot.get("ue_commit_mb"),
                        "host_ram_load_percent": snapshot.get("host_ram_load_percent"),
                        "host_commit_load_percent": snapshot.get("host_commit_load_percent"),
                        "host_commit_avail_gb": snapshot.get("host_commit_avail_gb"),
                        "gpu_usage_percent": snapshot.get("gpu_usage_percent"),
                        "gpu_memory_mb": snapshot.get("gpu_memory_mb"),
                    }

                    with self._lock:
                        if app_name not in self._ambient_buffers:
                            self._ambient_buffers[app_name] = collections.deque(maxlen=17280)
                        self._ambient_buffers[app_name].append(point)

                    # 若应用在线运行，持久化到 ambient_metrics 表
                    if ue_online or cdp_online:
                        db = SessionLocal()
                        try:
                            amb = AmbientMetric(
                                app_name=app_name,
                                timestamp=ts,
                                page_scope=snapshot.get("page_scope"),
                                dom_count=snapshot.get("dom_count", 0),
                                listeners_count=snapshot.get("listeners_count", 0),
                                js_heap_mb=snapshot.get("js_heap_mb", 0.0),
                                js_heap_total_mb=snapshot.get("js_heap_total_mb", 0.0),
                                echarts_instances=snapshot.get("echarts_instances", 0),
                                canvas_count=snapshot.get("canvas_count", 0),
                                video_instances=snapshot.get("video_instances", 0),
                                webrtc_fps=snapshot.get("webrtc_fps"),
                                chrome_pid=snapshot.get("chrome_pid"),
                                chrome_cpu_percent=snapshot.get("chrome_cpu_percent"),
                                chrome_memory_mb=snapshot.get("chrome_memory_mb"),
                                ue_pid=snapshot.get("ue_pid"),
                                ue_cpu_percent=snapshot.get("ue_cpu_percent"),
                                ue_memory_mb=snapshot.get("ue_memory_mb"),
                                ue_commit_mb=snapshot.get("ue_commit_mb"),
                                host_ram_load_percent=snapshot.get("host_ram_load_percent"),
                                host_commit_load_percent=snapshot.get("host_commit_load_percent"),
                                host_commit_avail_gb=snapshot.get("host_commit_avail_gb"),
                                gpu_usage_percent=snapshot.get("gpu_usage_percent"),
                                gpu_memory_mb=snapshot.get("gpu_memory_mb")
                            )
                            db.add(amb)
                            db.commit()
                        except Exception as dbe:
                            db.rollback()
                            logger.debug(f"[AmbientMonitor] 写入 ambient_metrics 失败: {dbe}")
                        finally:
                            db.close()

                cleanup_counter += 1
                if cleanup_counter >= (15 * 60 // max(int(interval_sec), 1)):
                    cleanup_counter = 0
                    self.cleanup_expired_ambient_metrics(hours=24)

            except Exception as e:
                logger.debug(f"[AmbientMonitor] 守护循环异常: {e}")

            self._ambient_stop_event.wait(timeout=interval_sec)

    def get_ambient_history(self, app_name: str, hours: float = 24.0, limit: int = 1000, downsample: bool = True) -> List[Dict[str, Any]]:
        """获取指定应用最近 hours 小时 (最高 24 小时) 的环境实时历史时序，支持自适应等间距智能降采样"""
        cutoff = datetime.datetime.utcnow() - datetime.timedelta(hours=hours)
        records: List[Dict[str, Any]] = []

        with self._lock:
            buf = self._ambient_buffers.get(app_name)
            if buf:
                for item in buf:
                    try:
                        ts = datetime.datetime.fromisoformat(item["timestamp"].rstrip("Z"))
                        if ts >= cutoff:
                            records.append(item)
                    except Exception:
                        records.append(item)

        if len(records) < 5:
            db = SessionLocal()
            try:
                db_recs = db.query(AmbientMetric).filter(
                    AmbientMetric.app_name == app_name,
                    AmbientMetric.timestamp >= cutoff
                ).order_by(AmbientMetric.timestamp.asc()).all()

                records = [{
                    "app_name": r.app_name,
                    "timestamp": r.timestamp.isoformat() + "Z" if not r.timestamp.isoformat().endswith("Z") else r.timestamp.isoformat(),
                    "page_scope": r.page_scope,
                    "dom_count": r.dom_count or 0,
                    "listeners_count": r.listeners_count or 0,
                    "js_heap_mb": r.js_heap_mb or 0.0,
                    "js_heap_total_mb": r.js_heap_total_mb or 0.0,
                    "echarts_instances": r.echarts_instances or 0,
                    "canvas_count": r.canvas_count or 0,
                    "video_instances": r.video_instances or 0,
                    "webrtc_fps": r.webrtc_fps,
                    "chrome_pid": r.chrome_pid,
                    "chrome_cpu_percent": r.chrome_cpu_percent,
                    "chrome_memory_mb": r.chrome_memory_mb,
                    "ue_pid": r.ue_pid,
                    "ue_cpu_percent": r.ue_cpu_percent,
                    "ue_memory_mb": r.ue_memory_mb,
                    "ue_commit_mb": r.ue_commit_mb,
                    "host_ram_load_percent": r.host_ram_load_percent,
                    "host_commit_load_percent": r.host_commit_load_percent,
                    "host_commit_avail_gb": r.host_commit_avail_gb,
                    "gpu_usage_percent": r.gpu_usage_percent,
                    "gpu_memory_mb": r.gpu_memory_mb,
                } for r in db_recs]
            finally:
                db.close()

        total_count = len(records)
        if total_count == 0:
            return []

        if downsample and total_count > limit:
            step = (total_count - 1) / (limit - 1)
            sampled_indices = {int(round(i * step)) for i in range(limit)}
            sampled_indices.add(0)
            sampled_indices.add(total_count - 1)
            return [records[i] for i in sorted(sampled_indices) if i < total_count]

        return records

    def get_all_apps_live_status(self) -> List[Dict[str, Any]]:
        """获取所有已配置应用的即时运行状态与专用提交量 (分项目独立检测)"""
        apps_cfg = getattr(settings, "apps", {}) or {}
        friendly_titles = {
            "tianrui": "四川天瑞",
            "zhaiwan": "寨湾矿山",
            "liwutong": "里伍铜矿山"
        }
        target_keys = ["tianrui", "zhaiwan", "liwutong"]
        for k in apps_cfg.keys():
            if k not in target_keys:
                target_keys.append(k)

        result = []
        for app_name in target_keys:
            cfg = apps_cfg.get(app_name, {})
            ue_metrics = self.collect_ue_metrics(app_name, allow_fallback=False)
            cdp_metrics = self.collect_cdp_metrics(app_name)
            title = friendly_titles.get(app_name) or cfg.get("name") or cfg.get("title") or app_name
            is_online = bool(ue_metrics.get("ue_pid")) or cdp_metrics.get("cdp_online", False)
            result.append({
                "app_name": app_name,
                "title": title,
                "online": is_online,
                "ue_pid": ue_metrics.get("ue_pid"),
                "ue_memory_mb": ue_metrics.get("ue_memory_mb"),
                "ue_commit_mb": ue_metrics.get("ue_commit_mb"),
                "ue_cpu_percent": ue_metrics.get("ue_cpu_percent"),
                "cdp_online": cdp_metrics.get("cdp_online", False)
            })
        return result

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
