# -*- coding: utf-8 -*-
"""
utils/env_checker.py —— 启动前置环境准入巡检与版本一致性校验器

核心职责：
1. 后端接口基地址校验：解析 Electron 启动器配置文件中的 nplusoneUrl，判断当前处于生产环境(prod)还是测试环境(test)。
2. 前端代码包版本校验：提取前端分发静态资源目录与包名特征，校验前端包是否过期。
3. 严格准入拦截(strict)：若环境与预期基线不符，按配置直接熔断退出，杜绝在过期前端包或错误环境中通宵盲跑。
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger("env_checker")

# 已知环境映射表
KNOWN_ENVIRONMENTS = {
    "http://221.234.48.197:8808": {
        "name": "生产环境 (Production)",
        "key": "prod"
    },
    "http://121.43.58.203:8783": {
        "name": "测试环境 (Testing)",
        "key": "test"
    }
}

# 全局环境快照缓存，便于报告和日志追溯
CURRENT_LAUNCHER_ENV: Dict[str, Any] = {}


def detect_environment_type(nplusone_url: str, custom_environments: Optional[Dict[str, str]] = None) -> Tuple[str, str]:
    """
    根据 nplusoneUrl 判定当前环境类型
    优先匹配 config.yaml 中配置的 custom_environments，其次匹配内置字典
    返回: (env_key, env_display_name)
    """
    if not nplusone_url:
        return "unknown", "未配置后端地址 (Unknown)"

    clean_url = nplusone_url.strip().rstrip("/")

    # 1. 优先根据当前应用配置中的 environments 匹配
    if custom_environments and isinstance(custom_environments, dict):
        for env_k, env_val in custom_environments.items():
            if env_val and (env_val.rstrip("/") in clean_url or clean_url in env_val.rstrip("/")):
                name_map = {"prod": "生产环境 (Production)", "test": "测试环境 (Testing)"}
                display_name = name_map.get(env_k.lower(), f"{env_k.upper()} 环境")
                return env_k.lower(), display_name

    # 2. 兜底已知环境映射表
    for url, info in KNOWN_ENVIRONMENTS.items():
        if url.rstrip("/") in clean_url or clean_url in url.rstrip("/"):
            return info["key"], info["name"]

    return "custom", f"自定义/其他环境 ({clean_url})"


def resolve_launcher_config_path(app_name: str, custom_path: Optional[str] = None) -> Path:
    """获取目标 Launcher 的 config.json 物理路径"""
    if custom_path:
        p = Path(custom_path)
        if p.is_file():
            return p

    app_data = os.getenv("APPDATA")
    if not app_data:
        app_data = str(Path.home() / "AppData" / "Roaming")

    # 规范化应用目录名，如 zhaiwan -> se-launcher-zhaiwan
    launcher_dir_name = app_name if app_name.startswith("se-launcher-") else f"se-launcher-{app_name}"
    candidate = Path(app_data) / launcher_dir_name / "config.json"
    return candidate


def load_launcher_config(config_path: Path) -> Optional[Dict[str, Any]]:
    """安全读取 Launcher 的 config.json"""
    if not config_path.exists() or not config_path.is_file():
        return None
    try:
        content = config_path.read_text(encoding="utf-8")
        return json.loads(content)
    except Exception as e:
        logger.warning(f"读取或解析 Launcher 配置文件失败 [{config_path}]: {e}")
        return None


def check_launcher_environment(settings: Any, ignore_check: bool = False, custom_logger: Optional[logging.Logger] = None) -> bool:
    """
    在启动测试前执行前置环境准入巡检 (Pre-flight Environment Check)
    返回: True (准入通过 / 允许执行), False (准入失败 / 阻断终止)
    """
    log = custom_logger or logger
    global CURRENT_LAUNCHER_ENV

    env_check_cfg = getattr(settings, "env_check_cfg", {})
    if not env_check_cfg:
        env_check_cfg = {}

    enabled = env_check_cfg.get("enabled", True)
    if not enabled:
        log.info("ℹ️ [Pre-flight] 环境前置准入校验已禁用 (enabled: false)，跳过检测。")
        return True

    active_app = getattr(settings, "active_app", "zhaiwan")
    custom_path = env_check_cfg.get("config_path")
    config_file = resolve_launcher_config_path(active_app, custom_path)

    if not config_file.exists():
        msg = f"未找到 Launcher 配置文件: {config_file}"
        if env_check_cfg.get("strict", False) and not ignore_check:
            log.error(f"❌ [Pre-flight 拦截] {msg}")
            return False
        else:
            log.warning(f"⚠️ [Pre-flight] {msg}，已跳过环境检测。")
            return True

    data = load_launcher_config(config_file)
    if not data:
        log.warning(f"⚠️ [Pre-flight] 无法解析 Launcher 配置内容: {config_file}")
        return True

    # 提取关键字段
    nplusone_url = str(data.get("nplusoneUrl", "")).strip()
    big_screen_dist = str(data.get("BIG_SCREEN_DIST", "")).strip()
    ue_dist = str(data.get("UE_DIST", "")).strip()
    nats_ws_url = str(data.get("natsWsUrl", "")).strip()
    ue_name = str(data.get("UEName", active_app)).strip()
    start_port = data.get("startPort", "")

    custom_envs = env_check_cfg.get("environments", {})
    env_key, env_name = detect_environment_type(nplusone_url, custom_envs)

    CURRENT_LAUNCHER_ENV = {
        "app_name": active_app,
        "config_file": str(config_file),
        "env_key": env_key,
        "env_name": env_name,
        "nplusone_url": nplusone_url,
        "big_screen_dist": big_screen_dist,
        "ue_dist": ue_dist,
        "nats_ws_url": nats_ws_url,
        "start_port": start_port
    }

    # 持久化环境快照至当前运行目录，供测试报告和追溯
    try:
        from utils.paths import get_run_dir
        run_dir = get_run_dir()
        env_dump_path = run_dir / "env_info.json"
        env_dump_path.write_text(json.dumps(CURRENT_LAUNCHER_ENV, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

    expected_env = str(env_check_cfg.get("expected_env", "prod")).strip().lower()
    expected_frontend = str(env_check_cfg.get("expected_frontend", "")).strip()
    strict = env_check_cfg.get("strict", True)

    # 判定校验结果
    env_matches = (expected_env == "any") or (env_key == expected_env)
    frontend_matches = (not expected_frontend) or (expected_frontend.lower() in big_screen_dist.lower())

    passed = env_matches and frontend_matches

    # 打印巡检看板
    divider = "=" * 80
    log.info(divider)
    if passed:
        log.info("🔍 [Pre-flight 环境准入巡检] ✅ 校验通过")
    else:
        log.info("🔍 [Pre-flight 环境准入巡检] ⚠️ 环境与预期不符！")
    log.info(f"   - 目标客户端: {active_app} (UEName: {ue_name}, 启动端口: {start_port})")
    log.info(f"   - 配置文件:   {config_file}")
    log.info(f"   - 当前环境:   {env_name} [{nplusone_url}]")
    log.info(f"   - 前端包目录: {big_screen_dist}")
    log.info(f"   - UE 引擎包:  {ue_dist}")
    if nats_ws_url:
        log.info(f"   - 告警推流:   {nats_ws_url} (大屏顶层人员告警弹窗)")
    else:
        log.info("   - 告警推流:   未配置")
    log.info(divider)

    if passed:
        return True

    # 未通过处理
    exp_url = custom_envs.get(expected_env, "")
    expected_name_map = {
        "prod": f"生产环境 ({exp_url})" if exp_url else "生产环境 (Production)",
        "test": f"测试环境 ({exp_url})" if exp_url else "测试环境 (Testing)"
    }
    exp_display = expected_name_map.get(expected_env, f"{expected_env} 环境 ({exp_url})" if exp_url else expected_env)

    err_msgs = []
    if not env_matches:
        err_msgs.append(f"期望环境: 【{exp_display}】，当前实际连接: 【{env_name}】")
    if not frontend_matches:
        err_msgs.append(f"期望前端包含: 【{expected_frontend}】，当前实际目录: 【{big_screen_dist}】")

    for m in err_msgs:
        log.warning(f"⚠️ [环境不符] {m}")

    if ignore_check:
        log.warning("🚩 检测到 --ignore-env-check 参数，已强制绕过环境阻断，继续执行！")
        return True

    if strict:
        log.error(divider)
        log.error("🚫 【安全阻断】目标客户端当前环境与预期不符！")
        log.error("   为了避免在错误环境下通宵跑测产生大量无效缺陷与截图，测试已安全终止。")
        log.error("   👉 解决方法:")
        log.error(f"      1. 打开 Launcher 启动器并将环境切换至目标环境: {exp_display}")
        log.error("      2. 或者修改 config.yaml 中的 env_check.expected_env")
        log.error("      3. 如需强制在当前环境下执行，请追加参数: --ignore-env-check")
        log.error(divider)
        return False
    else:
        log.warning("⚠️ env_check.strict 为 false，仅做告警提示，继续执行测试...")
        return True
