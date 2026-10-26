"""
==============================================================================
.agents/skills/zentao_sync/zentao_client.py
==============================================================================
此脚本委托给 utils/zentao_sync.py 核心模块，支持技能直接调用或独立 CLI 执行。
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from utils.zentao_sync import ZenTaoClient, main

if __name__ == "__main__":
    main()
