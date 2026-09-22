import argparse
import logging
import sys
import os
import time
from datetime import datetime
from pathlib import Path

from core.browser import ElectronDriver
from core.vision.agent import VisionAgent
from core.action_runner import ActionRunner
from core.explorer_agent import ExplorerAgent
from utils.logger import LoggerManager


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description="Electron AI Vision 纯视觉自动化巡检框架")
    parser.add_argument("--case", type=str, help="指定要运行的单一 YAML 用例路径 (例如 test_cases/check_production.yaml)")
    parser.add_argument("--all", action="store_true", help="运行 test_cases 目录下的所有用例")
    parser.add_argument("--ignore-errors", action="store_true", help="全局忽略步骤报错，继续执行后续步骤")
    parser.add_argument("--explore", type=str, help="开启自主探索模式，并指定宏观探索目标")
    parser.add_argument("--explore-context", type=str, action="append", help="指定针对探索模式的项目背景知识或交互规则，可多次使用，支持纯文本或文件路径")
    parser.add_argument("--resume-from", type=str, help="指定上一次探索的 log 目录（例如 logs/explore_xxx），以实现断点续传（继承记忆与页面架构树）")
    parser.add_argument("--max-steps", type=int, default=20, help="自主探索的最大步数限制（默认: 20）")
    parser.add_argument("--start-delay", type=float, default=15.0, help="启动应用后的等待时间(秒)，确保引擎和UI完全加载（默认: 15.0）")
    parser.add_argument("--wait-ready", type=str, help="【智能视觉等待】指定自然语言条件，持续轮询截屏直到满足条件")
    parser.add_argument("--wait-timeout", type=float, default=60.0, help="智能视觉等待的最大超时时间(秒) (默认: 60.0)")
    return parser.parse_args()


def collect_yaml_cases(args, logger: logging.Logger) -> list:
    """收集并去重待执行的 YAML 用例"""
    if args.explore:
        return []

    if not args.case and not args.all:
        logger.error("请通过 --case 或 --all 指定用例，或使用 --explore 开启探索模式。查看 --help 获取帮助。")
        sys.exit(1)

    cases_to_run = []
    if args.case:
        cases_to_run.append(args.case)
    if args.all:
        cases_dir = Path("test_cases")
        if cases_dir.exists():
            cases_to_run.extend([str(p) for p in cases_dir.glob("*.yaml")])
        else:
            logger.error("未找到 test_cases 目录！")
            sys.exit(1)

    return list(dict.fromkeys(cases_to_run))


def perform_visual_wait(driver: ElectronDriver, vision_agent: VisionAgent, prompt: str, timeout: float, logger: logging.Logger):
    """执行全局智能视觉等待，确保应用界面完全就绪"""
    logger.info("=" * 50)
    logger.info(f"👀 启动智能视觉等待: {prompt}")
    logger.info("=" * 50)
    
    start_t = time.time()
    attempt = 1
    while True:
        elapsed = time.time() - start_t
        if elapsed > timeout:
            logger.error(f"❌ 智能视觉等待超时 ({timeout}s)！")
            sys.exit(1)
        
        b64_img = driver.capture_screenshot_base64()
        passed, _ = vision_agent.check_assertion(prompt, b64_img)
        if passed:
            logger.info(f"✅ 视觉条件满足，画面已就绪 (耗时: {elapsed:.1f}s)！")
            break
        
        logger.info(f"🔄 画面尚未就绪，3秒后重试 (第 {attempt} 次检测)...")
        time.sleep(3.0)
        attempt += 1


def run_explore_mode(driver: ElectronDriver, vision_agent: VisionAgent, args):
    """运行自主探索模式"""
    LoggerManager().switch_file_handler("explorer")
    explorer = ExplorerAgent(driver, vision_agent)
    
    # 解析并拼接探索模式的先验知识
    context_str = ""
    if args.explore_context:
        contexts = []
        for ctx in args.explore_context:
            ctx_path = Path(ctx)
            if ctx_path.is_file():
                try:
                    contexts.append(ctx_path.read_text(encoding="utf-8").strip())
                except Exception as e:
                    logging.getLogger("main").error(f"读取 context 文件失败: {ctx} ({e})")
            else:
                contexts.append(ctx.strip())
        context_str = "\n".join(contexts)
        
    explorer.start_exploration(objective=args.explore, max_steps=args.max_steps, context=context_str, resume_from=args.resume_from)


def run_yaml_mode(driver: ElectronDriver, vision_agent: VisionAgent, cases_to_run: list, args, logger: logging.Logger):
    """运行确定性用例模式"""
    runner = ActionRunner(driver, vision_agent)
    success_count = 0
    
    for idx, case_path in enumerate(cases_to_run, 1):
        case_name = Path(case_path).stem
        LoggerManager().switch_file_handler(case_name)
        logger.info(f"\n[{idx}/{len(cases_to_run)}] 准备执行用例: {case_path}")
        
        try:
            runner.run_yaml_case(case_path, global_ignore_errors=args.ignore_errors)
            success_count += 1
        except Exception as e:
            logger.error(f"❌ 运行用例 {case_path} 失败: {e}")
            
    LoggerManager().switch_file_handler("summary")
    logger.info("=" * 60)
    logger.info(f"🎯 巡检报告: 总计 {len(cases_to_run)} | 成功 {success_count} | 失败 {len(cases_to_run) - success_count}")
    logger.info("=" * 60)
    
    if success_count < len(cases_to_run):
        sys.exit(1)


def main():
    args = parse_args()

    # 隔离探索模式的运行日志目录
    if args.explore:
        os.environ["REPORT_RUN_ID"] = "explore_" + datetime.now().strftime("%Y%m%d_%H%M%S")

    # 初始化全局日志
    logger_manager = LoggerManager()
    logger_manager.switch_file_handler("startup")
    logger = logger_manager.logger
    logger.name = "main"

    cases_to_run = collect_yaml_cases(args, logger)
    if not cases_to_run and not args.explore:
        logger.warning("没有找到可执行的用例文件。")
        sys.exit(0)

    mode_name = "自主探索" if args.explore else f"YAML 用例 (共 {len(cases_to_run)} 个)"
    logger.info(f"🚀 初始化 Electron 视觉巡检引擎 | 模式: {mode_name}")
    
    vision_agent = VisionAgent()
    
    with ElectronDriver() as driver:
        # 底层就绪后，做基本的物理等待
        logger.info(f"等待客户端应用界面初步缓冲 ({args.start_delay}秒)...")
        driver.wait(args.start_delay)
        
        # 智能视觉等待（如果指定）
        if args.wait_ready:
            perform_visual_wait(driver, vision_agent, args.wait_ready, args.wait_timeout, logger)

        # 路由到对应的执行引擎
        if args.explore:
            run_explore_mode(driver, vision_agent, args)
        else:
            run_yaml_mode(driver, vision_agent, cases_to_run, args, logger)


if __name__ == "__main__":
    main()
