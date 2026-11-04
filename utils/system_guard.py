# -*- coding: utf-8 -*-
"""
通用系统级物理与虚拟内存全景守护探针 (Universal System Memory & Process Guard)

核心定位：
1. 完全通用，零项目特殊硬编码 (适用于 zhaiwan, liwutong, tianrui 以及未来任何大屏应用)；
2. 纯 Windows 原生底层系统调用 (ctypes.windll.kernel32 & psapi)，零第三方包依赖；
3. 双重穿透采样：同时采集物理工作集 (WorkingSet/RAM) 与 专用提交量 (Private Bytes/Commit Charge)，
   彻底杜绝因 Windows 内存换页 (Pagefile) 造成的内存虚假回落表象；
4. 全景宿主机 Commit 额度与物理水线双重探针，彻底守护测试机远离 OOM 崩溃/蓝屏。
"""

import os
import sys
import ctypes
import logging
from ctypes import wintypes
from typing import Optional, Dict, Any

logger = logging.getLogger("utils.system_guard")


class SystemMemoryGuard:
    """通用系统物理内存、虚拟提交量与伴生渲染引擎守护探针"""

    class _MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    class _PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
            ("PrivateUsage", ctypes.c_size_t),
        ]

    @classmethod
    def get_host_memory_status(cls) -> Dict[str, Any]:
        """获取当前 Windows 宿主机物理内存与 Commit 提交量整体状态"""
        try:
            stat = cls._MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(cls._MEMORYSTATUSEX)
            success = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            if not success:
                return {"available": False}

            total_phys_mb = stat.ullTotalPhys / (1024 * 1024)
            avail_phys_mb = stat.ullAvailPhys / (1024 * 1024)
            used_phys_mb = total_phys_mb - avail_phys_mb

            total_commit_mb = stat.ullTotalPageFile / (1024 * 1024)
            avail_commit_mb = stat.ullAvailPageFile / (1024 * 1024)
            used_commit_mb = total_commit_mb - avail_commit_mb
            commit_load = int(used_commit_mb / total_commit_mb * 100) if total_commit_mb > 0 else 0

            return {
                "available": True,
                "load_percent": int(stat.dwMemoryLoad),
                "total_mb": round(total_phys_mb, 1),
                "used_mb": round(used_phys_mb, 1),
                "avail_mb": round(avail_phys_mb, 1),
                "total_gb": round(total_phys_mb / 1024.0, 2),
                "avail_gb": round(avail_phys_mb / 1024.0, 2),
                # 虚拟内存 Commit 指标
                "commit_total_gb": round(total_commit_mb / 1024.0, 2),
                "commit_avail_gb": round(avail_commit_mb / 1024.0, 2),
                "commit_load_percent": commit_load,
            }
        except Exception as e:
            logger.debug(f"[SystemMemoryGuard] 宿主机内存状态采集异常: {e}")
            return {"available": False}

    @classmethod
    def get_process_detailed_memory(cls, pid: int) -> Dict[str, float]:
        """穿透采集指定 PID 进程的 WorkingSet (物理RAM) 与 PrivateBytes (专用提交量)"""
        if not pid or pid <= 0:
            return {"ws_mb": 0.0, "private_mb": 0.0, "pagefile_mb": 0.0}
        try:
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if not h:
                return {"ws_mb": 0.0, "private_mb": 0.0, "pagefile_mb": 0.0}

            pmc = cls._PROCESS_MEMORY_COUNTERS_EX()
            pmc.cb = ctypes.sizeof(cls._PROCESS_MEMORY_COUNTERS_EX)
            success = ctypes.windll.psapi.GetProcessMemoryInfo(h, ctypes.byref(pmc), pmc.cb)
            ctypes.windll.kernel32.CloseHandle(h)

            if success:
                ws_mb = round(pmc.WorkingSetSize / (1024 * 1024), 2)
                priv_mb = round(pmc.PrivateUsage / (1024 * 1024), 2)
                pf_mb = round(pmc.PagefileUsage / (1024 * 1024), 2)
                return {
                    "ws_mb": ws_mb,
                    "private_mb": priv_mb,
                    "pagefile_mb": pf_mb,
                }
        except Exception as e:
            logger.debug(f"[SystemMemoryGuard] 采集 PID {pid} 详细内存异常: {e}")
        return {"ws_mb": 0.0, "private_mb": 0.0, "pagefile_mb": 0.0}

    @classmethod
    def get_companion_process_info(cls, process_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """获取当前激活应用的伴生 UE 引擎进程运行指标"""
        target_name = process_name
        if not target_name:
            try:
                from config.settings import settings
                target_name = getattr(settings, "ue_process_name", "")
            except Exception:
                target_name = ""

        if not target_name:
            return None

        try:
            from utils.electron_launcher import ElectronLauncher
            info = ElectronLauncher.get_process_info(target_name)
            if info:
                pid = info.get("pid", 0)
                details = cls.get_process_detailed_memory(pid)
                info["mem_mb"] = details["ws_mb"] if details["ws_mb"] > 0 else round(info.get("mem_kb", 0.0) / 1024.0, 2)
                info["private_mb"] = details["private_mb"]
                info["pagefile_mb"] = details["pagefile_mb"]
            return info
        except Exception as e:
            logger.debug(f"[SystemMemoryGuard] 伴生进程 {target_name} 采集异常: {e}")
            return None

    @classmethod
    def get_launcher_process_info(cls, launcher_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """获取当前激活应用的主启动器进程运行指标"""
        target_path = launcher_path
        if not target_path:
            try:
                from config.settings import settings
                target_path = getattr(settings, "app_path", "")
            except Exception:
                target_path = ""

        if not target_path:
            return None

        launcher_name = os.path.basename(target_path)
        try:
            from utils.electron_launcher import ElectronLauncher
            info = ElectronLauncher.get_process_info(launcher_name)
            if info:
                pid = info.get("pid", 0)
                details = cls.get_process_detailed_memory(pid)
                info["mem_mb"] = details["ws_mb"] if details["ws_mb"] > 0 else round(info.get("mem_kb", 0.0) / 1024.0, 2)
                info["private_mb"] = details["private_mb"]
            return info
        except Exception as e:
            logger.debug(f"[SystemMemoryGuard] 启动器进程 {launcher_name} 采集异常: {e}")
            return None

    @classmethod
    def sample_all_memory(cls) -> Dict[str, Any]:
        """一站式聚合采样宿主机、伴生引擎与启动器全景内存快照"""
        host = cls.get_host_memory_status()
        comp = cls.get_companion_process_info()
        launch = cls.get_launcher_process_info()

        return {
            "host_load_percent": host.get("load_percent", 0) if host.get("available") else 0,
            "host_avail_mb": host.get("avail_mb", 0.0) if host.get("available") else 0.0,
            "host_total_gb": host.get("total_gb", 0.0) if host.get("available") else 0.0,
            "host_commit_load_percent": host.get("commit_load_percent", 0),
            "host_commit_avail_gb": host.get("commit_avail_gb", 0.0),
            "companion_name": comp.get("name") if comp else None,
            "companion_pid": comp.get("pid") if comp else None,
            "companion_mem_mb": comp.get("mem_mb", 0.0) if comp else 0.0,
            "companion_private_mb": comp.get("private_mb", 0.0) if comp else 0.0,
            "launcher_name": launch.get("name") if launch else None,
            "launcher_pid": launch.get("pid") if launch else None,
            "launcher_mem_mb": launch.get("mem_mb", 0.0) if launch else 0.0,
            "launcher_private_mb": launch.get("private_mb", 0.0) if launch else 0.0,
        }
