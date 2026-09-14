import argparse
import logging
import sys
from pathlib import Path

from core.browser import ElectronDriver
from core.vision_agent import VisionAgent
from core.action_runner import ActionRunner
from utils.logger import LoggerManager

# 初始化基础日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

def run_case(runner: ActionRunner, case_path: str, logger: logging.Logger) -> bool:
    try:
        runner.run_yaml_case(case_path)
        return True
    except Exception as e:
        logger.error(f"❌ 运行用例 {case_path} 失败: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="Electron AI Vision 纯视觉自动化巡检框架")
    parser.add_argument("--case", type=str, help="指定要运行的单一 YAML 用例路径 (例如 test_cases/check_production.yaml)")
    parser.add_argument("--all", action="store_true", help="运行 test_cases 目录下的所有用例")
    args = parser.parse_args()

    # 获取彩色配置的全局日志实例
    logger = LoggerManager().logger
    logger.name = "main"

    if not args.case and not args.all:
        parser.print_help()
        sys.exit(1)

    # 收集待执行的用例
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

    if not cases_to_run:
        logger.warning("没有找到可执行的用例文件。")
        sys.exit(0)

    # 去重
    cases_to_run = list(dict.fromkeys(cases_to_run))

    logger.info(f"🚀 初始化 Electron 视觉巡检引擎，共加载 {len(cases_to_run)} 个用例...")
    
    # 启动框架核心组件
    vision_agent = VisionAgent()
    
    success_count = 0
    with ElectronDriver() as driver:
        # 等待客户端彻底加载就绪
        logger.info("等待客户端应用界面加载...")
        driver.wait(3.0)
        
        runner = ActionRunner(driver, vision_agent)
        
        for idx, case_path in enumerate(cases_to_run, 1):
            logger.info(f"\n[{idx}/{len(cases_to_run)}] 准备执行用例: {case_path}")
            if run_case(runner, case_path, logger):
                success_count += 1
                
    logger.info("=" * 60)
    logger.info(f"🎯 巡检报告: 总计 {len(cases_to_run)} | 成功 {success_count} | 失败 {len(cases_to_run) - success_count}")
    logger.info("=" * 60)
    
    if success_count < len(cases_to_run):
        sys.exit(1)

if __name__ == "__main__":
    main()
