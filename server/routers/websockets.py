"""
WebSocket 实时长连接管道与广播通道
- /ws/tasks/{task_id}/logs: 终端控制台实时日志流
- /ws/tasks/{task_id}/metrics: ECharts 实时性能指标流
- /ws/platform: 平台全局事件与广播通道
"""

import asyncio
import datetime
import json
import logging
from typing import Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..task_manager import task_manager
from ..performance_monitor import performance_monitor

logger = logging.getLogger("server.websockets")
router = APIRouter()

# 全局活跃 WebSocket 连接池（用于 shutdown/reload 时主动断开，彻底杜绝 uvicorn 卡死）
active_websockets: Set[WebSocket] = set()
platform_subscribers: Set[WebSocket] = set()

@router.websocket("/ws/tasks/{task_id}/logs")
async def websocket_task_logs(websocket: WebSocket, task_id: str):
    """

    WebSocket 实时终端控制台日志推流频道

    前端连接后先接收最近 50 行历史日志，随后以长连接极低时延实时推送每一行子进程标准输出。

    """

    await websocket.accept()
    active_websockets.add(websocket)

    queue = task_manager.subscribe_logs(task_id)

    try:
        recent = task_manager.get_logs(task_id, tail=50)

        for line in recent:
            await websocket.send_text(line)

        while True:
            line = await queue.get()

            await websocket.send_text(line)

    except (WebSocketDisconnect, asyncio.CancelledError):
        pass

    except Exception as e:
        logger.debug(f"[WS-Logs] 任务 [{task_id}] 推流通道安全关闭: {e}")

    finally:
        active_websockets.discard(websocket)
        task_manager.unsubscribe_logs(task_id, queue)




@router.websocket("/ws/tasks/{task_id}/metrics")
async def websocket_task_metrics(websocket: WebSocket, task_id: str):
    """

    WebSocket 实时时序性能推流频道

    专供前端 ECharts 动态折线大屏实时渲染，任务后台探针每完成一次 5 秒采样便自动向当前频道广播一条最新的指标 JSON。

    """

    await websocket.accept()
    active_websockets.add(websocket)

    queue = performance_monitor.subscribe_metrics(task_id)

    try:
        while True:
            metric_dict = await queue.get()

            await websocket.send_json(metric_dict)

    except (WebSocketDisconnect, asyncio.CancelledError):
        pass

    except Exception as e:
        logger.debug(f"[WS-Metrics] 任务 [{task_id}] 性能推流通道安全关闭: {e}")

    finally:
        active_websockets.discard(websocket)
        performance_monitor.unsubscribe_metrics(task_id, queue)




@router.websocket("/ws/platform")
async def websocket_platform(websocket: WebSocket):
    """全平台全局多端实时数据同步 WebSocket 通道"""

    await websocket.accept()
    active_websockets.add(websocket)

    platform_subscribers.add(websocket)

    try:
        while True:
            data = await websocket.receive_text()

            if data == "ping":
                await websocket.send_text("pong")

    except (WebSocketDisconnect, asyncio.CancelledError):
        pass

    finally:
        active_websockets.discard(websocket)
        platform_subscribers.discard(websocket)


