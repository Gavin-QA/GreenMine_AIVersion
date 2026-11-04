# -*- coding: utf-8 -*-
"""
通用系统级物理内存与伴生进程守护探针 (Universal System Memory & Process Guard)

核心定位：
1. 完全通用，零项目特殊硬编码 (适用于 zhaiwan, liwutong, tianrui 以及未来任何大屏应用)；
2. 纯 Windows 原生底层系统调用 (ctypes.windll.kernel32.GlobalMemoryStatusEx)，零第三方包依赖；
3. 动态从 settings.ue_process_name 与 settings.app_path 嗅探伴生 UE 渲染引擎与主启动器的真实物理工作集；
4. 提供宿主机全局物理内存安全水位探针，守护主机远离 OOM 崩溃/蓝屏。
"""

import os
import sys
import ctypes
import logging
from ctypes import wintypes
from typing import Optional, Dict, Any

logger = logging.getLogger("utils.system_guard")


class SystemMemoryGuard:
    """通用系统物理内存与伴生渲染引擎守护探针"""

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

    @classmethod
    def get_host_memory_status(cls) -> Dict[str, Any]:
        """获取当前 Windows 宿主机整体物理内存与负载情况"""
        try:
            stat = cls._MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(cls._MEMORYSTATUSEX)
            success = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            if not success:
                return {"available": False}
            total_mb = stat.ullTotalPhys / (1024 * 1024)
            avail_mb = stat.ullAvailPhys / (1024 * 1024)
            used_mb = total_mb - avail_mb
            return {
                "available": True,
                "load_percent": int(stat.dwMemoryLoad),
                "total_mb": round(total_mb, 1),
                "used_mb": round(used_mb, 1),
                "avail_mb": round(avail_mb, 1),
                "total_gb": round(total_mb / 1024.0, 2),
                "avail_gb": round(avail_mb / 1024.0, 2),
            }
        except Exception as e:
            logger.debug(f"[SystemMemoryGuard] 宿主机内存状态采集异常: {e}")
            return {"available": False}

    @staticmethod
    def get_companion_process_info(process_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
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
                mem_kb = float(info.get("mem_kb", 0.0))
                info["mem_mb"] = round(mem_kb / 1024.0, 2)
            return info
        except Exception as e:
            logger.debug(f"[SystemMemoryGuard] 伴生进程 {target_name} 采集异常: {e}")
            return None

    @staticmethod
    def get_launcher_process_info(launcher_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
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
                mem_kb = float(info.get("mem_kb", 0.0))
                info["mem_mb"] = round(mem_kb / 1024.0, 2)
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
            "companion_name": comp.get("name") if comp else None,
            "companion_pid": comp.get("pid") if comp else None,
            "companion_mem_mb": comp.get("mem_mb", 0.0) if comp else 0.0,
            "launcher_name": launch.get("name") if launch else None,
            "launcher_pid": launch.get("pid") if launch else None,
            "launcher_mem_mb": launch.get("mem_mb", 0.0) if launch else 0.0,
        }
