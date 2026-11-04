# -*- coding: utf-8 -*-
"""
通用伴生引擎与宿主机内存守护探针验证测试
用于验证：
1. 宿主机全局物理内存与负载率的无损秒级采集 (Windows ctypes 原生 API)
2. 伴生引擎进程 (settings.ue_process_name) 物理工作集的动态感知与采集
3. 主启动器进程 (settings.app_path) 物理工作集的动态感知与采集
4. 全面适用于 zhaiwan / liwutong / tianrui 等任意项目，零硬编码
"""

import sys
import os
import ctypes
from pathlib import Path
from ctypes import wintypes
from typing import Optional, Dict, Any

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 确保项目根目录在 sys.path
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import settings


class SystemMemoryProbe:
    """通用宿主机与伴生进程系统级内存探针 (无第三方库依赖)"""

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

    @staticmethod
    def get_process_memory_by_name(process_name: str) -> Optional[Dict[str, Any]]:
        """获取指定名称进程的物理工作集内存 (支持伴生 UE 进程与 Launcher)"""
        if not process_name:
            return None
        from utils.electron_launcher import ElectronLauncher
        return ElectronLauncher.get_process_info(process_name)


def test_system_memory_probe():
    print("\n" + "=" * 70)
    print("🔍 [Universal Memory Guard Test] 开始执行通用系统内存探针测试")
    print("=" * 70)

    # 1. 采集宿主机全局物理内存
    host_mem = SystemMemoryProbe.get_host_memory_status()
    assert host_mem.get("available") is True
    print(f"✅ 1. 宿主机全局物理内存状态采集成功:")
    print(f"   - 内存使用率: {host_mem['load_percent']}%")
    print(f"   - 总物理内存: {host_mem['total_gb']} GB ({host_mem['total_mb']} MB)")
    print(f"   - 已用物理内存: {host_mem['used_mb']} MB")
    print(f"   - 剩余可用内存: {host_mem['avail_gb']} GB ({host_mem['avail_mb']} MB)")

    # 2. 动态读取当前配置的伴生 UE 进程和 Launcher 路径
    active_app = getattr(settings, "active_app", "unknown")
    ue_name = getattr(settings, "ue_process_name", "")
    app_path = getattr(settings, "app_path", "")
    launcher_name = os.path.basename(app_path) if app_path else ""

    print(f"\n✅ 2. 当前环境配置解析 (完全通用，零硬编码):")
    print(f"   - 当前激活应用 (active_app): {active_app}")
    print(f"   - 伴生 UE 进程名 (ue_process_name): {ue_name or '未配置'}")
    print(f"   - 启动器可执行文件 (app_path): {launcher_name or '未配置'}")

    # 3. 伴生进程与启动器探针采样
    if ue_name:
        ue_info = SystemMemoryProbe.get_process_memory_by_name(ue_name)
        if ue_info:
            print(f"   👉 伴生引擎进程 [{ue_name}] 正在运行:")
            print(f"      PID: {ue_info['pid']}, 物理内存 (WorkingSet): {ue_info['mem_kb'] / 1024.0:.1f} MB")
        else:
            print(f"   👉 伴生引擎进程 [{ue_name}] 当前未运行 (待命状态)")

    if launcher_name:
        launcher_info = SystemMemoryProbe.get_process_memory_by_name(launcher_name)
        if launcher_info:
            print(f"   👉 启动器进程 [{launcher_name}] 正在运行:")
            print(f"      PID: {launcher_info['pid']}, 物理内存 (WorkingSet): {launcher_info['mem_kb'] / 1024.0:.1f} MB")
        else:
            print(f"   👉 启动器进程 [{launcher_name}] 当前未运行 (待命状态)")

    print("\n" + "=" * 70)
    print("🎉 通用内存守护探针测试验证通过！")
    print("=" * 70)


if __name__ == "__main__":
    test_system_memory_probe()
