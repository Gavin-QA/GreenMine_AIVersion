import os
import sys
from pathlib import Path
import uvicorn
import logging

# 确保项目根目录加入 sys.path，无论从何处执行脚本都能正确加载 server 模块
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if __name__ == "__main__":
    logging.info("🚀 启动 Electron AI Vision Testing Platform 服务 (启用热重载)...")
    try:
        reload_dirs = [str(PROJECT_ROOT / "server"), str(PROJECT_ROOT / "utils")]
        uvicorn.run("server.main:app", host="127.0.0.1", port=8000, reload=True, reload_dirs=reload_dirs, timeout_graceful_shutdown=2, log_level="info")
    except KeyboardInterrupt:
        print("\n🛑 收到退出信号，平台服务已优雅退出。")
