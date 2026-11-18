"""
FastAPI 路由聚合导出模块
"""

from .system import router as system_router
from .presets import router as presets_router
from .queue import router as queue_router
from .tasks import router as tasks_router
from .bugs import router as bugs_router
from .performance import router as performance_router
from .cases import router as cases_router
from .zentao import router as zentao_router
from .websockets import (
    router as websockets_router,
    active_websockets,
    platform_subscribers,
)

__all__ = [
    "system_router",
    "presets_router",
    "queue_router",
    "tasks_router",
    "bugs_router",
    "performance_router",
    "cases_router",
    "zentao_router",
    "websockets_router",
    "active_websockets",
    "platform_subscribers",
]
