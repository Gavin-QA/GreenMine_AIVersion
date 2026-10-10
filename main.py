import argparse
import logging
import sys
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from core.browser import ElectronDriver
from core.vision.agent import VisionAgent
from core.action_runner import ActionRunner
from core.explorer_agent import ExplorerAgent
from utils.logger import LoggerManager
from config.settings import settings


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description="Electron AI Vision 纯视觉自动化巡检框架")
    parser.add_argument("--case", type=str, help="指定要运行的单一 YAML 用例路径 (例如 test_cases/check_production.yaml)")
    parser.add_argument("--all", action="store_true", help="运行 test_cases 目录下的所有用例")
    parser.add_argument("--ignore-errors", action="store_true", help="全局忽略步骤报错，继续执行后续步骤")
    parser.add_argument("--explore", type=str, help="开启自主探索模式，并指定宏观探索目标")
    parser.add_argument("--tour", "--smoke", dest="tour", action="store_true", help="33个二级菜单全量冒烟巡检模式：单次启动依次遍历所有二级菜单，验证两级跳转与页面轻量交互（纯日志，不生成Mermaid架构图）")
    parser.add_argument("--explore-context", type=str, action="append", help="指定针对探索模式的项目背景知识或交互规则，可多次使用，支持纯文本或文件路径")
    parser.add_argument("--resume-from", type=str, help="指定上一次探索的运行目录（如 reports/runs/explore_xxx 或旧 logs/xxx），以实现断点续传（继承记忆与页面架构树）")
    parser.add_argument("--reexplore", type=str, nargs="?", const="auto", help="强制重新探索指定模块（即使已在架构树中存在）。可指定模块名（如 智能通风），若不带参数则自动从 --explore 提示词中提取")
    parser.add_argument("--max-steps", type=int, default=20, help="自主探索的最大步数限制（默认: 20）")
    parser.add_argument("--max-times", type=int, default=10, help="自主探索的最大时间限制(分钟，默认: 10)")
    parser.add_argument("--start-delay", type=float, default=getattr(settings, "start_delay", 15.0), help="启动应用后的等待时间(秒)，确保引擎和UI完全加载（默认从 config.yaml 读取）")
    parser.add_argument("--wait-ready", type=str, help="【智能视觉等待】指定自然语言条件，持续轮询截屏直到满足条件")
    parser.add_argument("--wait-timeout", type=float, default=60.0, help="智能视觉等待的最大超时时间(秒) (默认: 60.0)")
    return parser.parse_args()


def collect_yaml_cases(args, logger: logging.Logger) -> list:
    """收集并去重待执行的 YAML 用例"""
    if args.explore or getattr(args, "tour", False):
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
        
        logger.info(f"🔄 画面尚未就绪，4秒后重试 (第 {attempt} 次检测)...")
        time.sleep(4.0)
        attempt += 1


def extract_target_module(prompt: str) -> Optional[str]:
    """从提示词中智能匹配已知的一级或二级业务模块名称"""
    if not prompt:
        return None
    try:
        from core.explorer_agent.page_map_builder import PageMapBuilder
        base_tree = PageMapBuilder.parse_base_rules()
        
        all_l2 = []
        all_l1 = list(base_tree.keys())
        for l2_dict in base_tree.values():
            all_l2.extend(list(l2_dict.keys()))
            
        # 优先匹配二级业务菜单（颗粒度更细，如“智能通风”、“采掘设备”）
        for l2 in sorted(all_l2, key=len, reverse=True):
            if l2 in prompt:
                return l2
                
        # 次优匹配一级主模块（如“智控管理”）
        for l1 in sorted(all_l1, key=len, reverse=True):
            if l1 in prompt:
                return l1
    except Exception as e:
        logging.getLogger("main").warning(f"从提示词解析目标模块失败: {e}")
        
    return None


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
        
    reexplore_module = None
    # 1. 显式传入了 --reexplore 参数
    if getattr(args, "reexplore", None):
        if args.reexplore != "auto":
            reexplore_module = args.reexplore.strip()
        else:
            reexplore_module = extract_target_module(args.explore)
    # 2. 虽未传 --reexplore，但 explore 文本中含有重新探索自然语言意图
    elif args.explore and any(k in args.explore for k in ["重新", "重探", "再次", "重做", "重跑"]):
        reexplore_module = extract_target_module(args.explore)

    if reexplore_module:
        logging.getLogger("main").info(f"🎯 [Re-explore] 识别到模块重探需求，锁定目标模块: 【{reexplore_module}】")

    explorer.start_exploration(
        objective=args.explore,
        max_steps=args.max_steps,
        max_time_mins=args.max_times,
        context=context_str,
        resume_from=args.resume_from,
        reexplore_module=reexplore_module
    )


def run_smoke_tour_mode(driver: ElectronDriver, vision_agent: VisionAgent, args):
    """运行 33 个二级菜单全量冒烟巡检模式"""
    LoggerManager().switch_file_handler("smoke_tour")
    explorer = ExplorerAgent(driver, vision_agent)
    
    # 自动加载先验规则（优先使用命令行指定的 context，默认自动加载 docs/explore_rules.md）
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
    else:
        default_rules = Path("docs") / "explore_rules.md"
        if default_rules.exists():
            try:
                context_str = default_rules.read_text(encoding="utf-8").strip()
            except Exception:
                pass
            
    explorer.start_smoke_tour(context=context_str)


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
    
    try:
        from utils.report_generator import ReportGenerator
        from utils.paths import get_run_dir
        
        # 导出接口大盘供报告渲染
        api_file = get_run_dir() / "api_registry.json"
        try:
            driver.dump_api_registry(str(api_file))
        except Exception as api_err:
            logger.warning(f"⚠️ 导出接口大盘异常: {api_err}")
            
        ReportGenerator(get_run_dir()).generate_html()
    except Exception as e:
        logger.error(f"❌ 生成 YAML 测试报告失败: {e}")

    if success_count < len(cases_to_run):
        sys.exit(1)


def main():
    args = parse_args()

    # 隔离不同模式的运行日志目录
    if getattr(args, "tour", False):
        os.environ["REPORT_RUN_ID"] = "smoke_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    elif args.explore:
        os.environ["REPORT_RUN_ID"] = "explore_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    else:
        os.environ["REPORT_RUN_ID"] = "yaml_" + datetime.now().strftime("%Y%m%d_%H%M%S")

    # 初始化全局日志
    logger_manager = LoggerManager()
    logger_manager.switch_file_handler("startup")
    logger = logger_manager.logger
    logger.name = "main"

    cases_to_run = collect_yaml_cases(args, logger)
    if not cases_to_run and not args.explore and not getattr(args, "tour", False):
        logger.warning("没有找到可执行的用例文件。查看 --help 获取帮助。")
        sys.exit(0)

    if getattr(args, "tour", False):
        mode_name = "33个二级菜单全量冒烟巡检 (Smoke Tour)"
    elif args.explore:
        mode_name = "自主探索"
    else:
        mode_name = f"YAML 用例 (共 {len(cases_to_run)} 个)"
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
        if getattr(args, "tour", False):
            run_smoke_tour_mode(driver, vision_agent, args)
        elif args.explore:
            run_explore_mode(driver, vision_agent, args)
        else:
            run_yaml_mode(driver, vision_agent, cases_to_run, args, logger)


if __name__ == "__main__":
    main()
