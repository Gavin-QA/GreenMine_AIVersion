"""
多核全栈性能监控 (Chromium CDP、UE5 进程、GPU、实时心电图与时序归档)
"""

import datetime
import logging
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Path as FastPath
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import TaskRun, PerformanceMetric
from ..schemas import (
    LivePerformanceSnapshotResponse,
    AmbientMetricPointResponse,
    AppLiveStatusItem,
    PerformanceMetricResponse,
    PerformanceSummaryResponse,
    MetricsCleanupResponse,
)
from ..performance_monitor import performance_monitor

logger = logging.getLogger("server.performance")
router = APIRouter()

@router.get(
    "/api/metrics/live/snapshot",
    response_model=LivePerformanceSnapshotResponse,
    tags=["4. 多核全栈性能监控"],
    summary="即时采集当前大屏物理环境性能快照",
    description="无需启动任何测试任务，即时对本机运行的 UE5 引擎、Chromium CDP 协议端口以及 NVIDIA GPU 进行只读探针采样并返回即时切片。",
)
def get_live_performance_snapshot(
    app_name: str = Query(
        default="zhaiwan", description="矿山应用系统代号 (zhaiwan / liwutong)"
    ),
):

    snapshot = performance_monitor.collect_full_snapshot(app_name=app_name)

    return LivePerformanceSnapshotResponse(**snapshot)


@router.get(
    "/api/metrics/live/history",
    response_model=List[AmbientMetricPointResponse],
    tags=["4. 多核全栈性能监控"],
    summary="获取指定矿山应用最近 24 小时内的环境实时心电图历史时序",
    description="支持指定矿山应用（如 tianrui / zhaiwan），返回过去 15 分钟 ~ 24 小时的高保真连续时序数据。进入页面时瞬间灌满 ECharts 图表，彻底告别从零开始。",
)
def get_ambient_metrics_history(
    app_name: str = Query(
        default="tianrui", description="矿山应用代码 (tianrui / zhaiwan / liwutong)"
    ),
    hours: float = Query(
        default=24.0, ge=0.1, le=48.0, description="回溯时长 (小时，默认24小时)"
    ),
    limit: int = Query(default=1000, ge=50, le=5000, description="最大返回点数 (达到上限自动触发等间距降采样)"),
    downsample: bool = Query(default=True, description="是否启用智能等间距降采样保障前端秒开"),
):
    """
    拉取指定矿山应用的常驻环境性能监控时序历史数据点。

    Args:
        app_name: 矿山应用代号
        hours: 回溯时间范围小时数
        limit: 最大返回采样点数
        downsample: 是否启用等间距降采样

    Returns:
        List[AmbientMetricPointResponse]: 包含 DOM、堆内存、CPU、UE5 内存与 WebRTC 帧率的时序列表
    """
    return performance_monitor.get_ambient_history(
        app_name=app_name, hours=hours, limit=limit, downsample=downsample
    )


@router.get(
    "/api/metrics/live/apps_status",
    response_model=List[AppLiveStatusItem],
    tags=["4. 多核全栈性能监控"],
    summary="获取所有矿山应用的实时运行与内存状态列表",
    description="返回各应用当前伴生 UE 是否在线、专用提交量(Commit)及物理内存，供前端展示状态微标。",
)
def get_all_apps_live_status():
    """
    获取系统中所有已注册矿山大屏应用的即时存活与资源开销状态。

    Returns:
        List[AppLiveStatusItem]: 各矿山系统状态条目列表
    """
    return performance_monitor.get_all_apps_live_status()


@router.get(
    "/api/metrics/{task_id}",
    response_model=List[PerformanceMetricResponse],
    tags=["4. 多核全栈性能监控"],
    summary="获取任务的时序性能指标数据列表 (支持自适应等间距智能降采样与全周期保真)",
    description="返回指定任务运行期间采集的所有性能时序打点。当点数超过 limit 时自动启用均匀等间距降采样算法，确保起点与终点 100% 完整覆盖，完美支撑数小时乃至通宵压测的全量 ECharts 渲染与 DataZoom 缩放。",
)
def get_task_metrics(
    task_id: str = FastPath(..., description="巡检任务全局标识码"),
    limit: int = Query(default=1000, ge=10, le=5000, description="最大返回时序点数量"),
    downsample: bool = Query(
        default=True,
        description="超出 limit 时是否进行自适应等间距降采样保留全周期跨度",
    ),
    db: Session = Depends(get_db),
):

    query = (
        db.query(PerformanceMetric)
        .filter(PerformanceMetric.task_id == task_id)
        .order_by(PerformanceMetric.timestamp.asc())
    )

    total_count = query.count()

    # 若尚未入库，尝试从历史 reports/runs/**/memory_timeline.json 中自动回填历史数据

    if total_count == 0:
        task = db.query(TaskRun).filter(TaskRun.id == task_id).first()

        if task and task.run_dir:
            tl_path = (
                PROJECT_ROOT
                / "reports"
                / "runs"
                / task.run_dir
                / "screenshots"
                / "memory_timeline.json"
            )

            if tl_path.exists():
                try:
                    with open(tl_path, "r", encoding="utf-8") as f:
                        data = json.load(f)

                    timeline = data.get("timeline", [])

                    new_records = []

                    for item in timeline:
                        ts = datetime.datetime.fromtimestamp(item.get("timestamp", 0))

                        pm = PerformanceMetric(
                            task_id=task_id,
                            timestamp=ts,
                            step_number=None,
                            page_scope=item.get("page_scope"),
                            dom_count=item.get("dom_nodes", 0),
                            listeners_count=item.get("js_event_listeners", 0),
                            js_heap_mb=item.get("js_heap_used_mb", 0.0),
                            js_heap_total_mb=item.get("js_heap_total_mb", 0.0),
                            echarts_instances=item.get("echarts_instances", 0),
                            canvas_count=item.get("canvas_count", 0),
                            video_instances=item.get("video_count", 0),
                        )

                        db.add(pm)

                        new_records.append(pm)

                    db.commit()

                    query = (
                        db.query(PerformanceMetric)
                        .filter(PerformanceMetric.task_id == task_id)
                        .order_by(PerformanceMetric.timestamp.asc())
                    )

                    total_count = len(new_records)

                except Exception as e:
                    logger.debug(f"回填历史 memory_timeline.json 异常: {e}")

    if total_count == 0:
        return []

    # 智能等间距降采样：如果数据点数量超过 limit，保留起点、终点和中间均匀分布的点，确保跨度 100% 完整

    if downsample and total_count > limit:
        all_records = query.all()

        step = (total_count - 1) / (limit - 1)

        sampled_indices = {int(round(i * step)) for i in range(limit)}

        sampled_indices.add(0)

        sampled_indices.add(total_count - 1)

        return [all_records[i] for i in sorted(sampled_indices) if i < total_count]

    return query.limit(limit).all()


@router.get(
    "/api/metrics/{task_id}/summary",
    response_model=PerformanceSummaryResponse,
    tags=["4. 多核全栈性能监控"],
    summary="聚合计算任务全生命周期性能峰值与健康预警",
    description="自动聚合 DOM 峰值、平均值、JSHeap 峰值、UE5 内存峰值与 WebRTC 最低谷底掉帧点，并输出智能性能告警建议（如 DOM 泄漏爆炸预警）。",
)
def get_task_metrics_summary(
    task_id: str = FastPath(..., description="巡检任务识别码"),
    db: Session = Depends(get_db),
):

    records = (
        db.query(PerformanceMetric)
        .filter(PerformanceMetric.task_id == task_id)
        .order_by(PerformanceMetric.timestamp.asc())
        .all()
    )

    if not records:
        return PerformanceSummaryResponse(task_id=task_id, sample_count=0)

    count = len(records)

    doms = [r.dom_count for r in records if r.dom_count]

    listeners = [r.listeners_count for r in records if r.listeners_count]

    heaps = [r.js_heap_mb for r in records if r.js_heap_mb]

    fps_list = [r.webrtc_fps for r in records if r.webrtc_fps is not None]

    ue_cpus = [r.ue_cpu_percent for r in records if r.ue_cpu_percent is not None]

    ue_mems = [r.ue_memory_mb for r in records if r.ue_memory_mb is not None]

    ue_commits = [r.ue_commit_mb for r in records if r.ue_commit_mb is not None]

    host_commits = [
        r.host_commit_load_percent
        for r in records
        if r.host_commit_load_percent is not None
    ]

    chrome_cpus = [
        r.chrome_cpu_percent for r in records if r.chrome_cpu_percent is not None
    ]

    chrome_mems = [
        r.chrome_memory_mb for r in records if r.chrome_memory_mb is not None
    ]

    gpus = [r.gpu_usage_percent for r in records if r.gpu_usage_percent is not None]

    gpu_mems = [r.gpu_memory_mb for r in records if r.gpu_memory_mb is not None]

    alerts: List[str] = []

    peak_dom = max(doms) if doms else 0

    latest_dom = doms[-1] if doms else 0

    peak_listeners = max(listeners) if listeners else 0

    latest_listeners = listeners[-1] if listeners else 0

    peak_heap = max(heaps) if heaps else 0.0

    latest_heap = heaps[-1] if heaps else 0.0

    peak_ue_commit = max(ue_commits) if ue_commits else None

    peak_host_commit = max(host_commits) if host_commits else None

    if peak_dom > 50000:
        alerts.append(
            f"⚠️ DOM 节点数发生严重泄漏膨胀！峰值达到 {peak_dom} 个节点（健康阈值: <30,000）"
        )

    if peak_listeners > 10000:
        alerts.append(
            f"⚠️ JS 事件监听器累积过多！峰值达到 {peak_listeners} 个，可能未注销事件销毁钩子"
        )

    if peak_heap > 800.0:
        alerts.append(f"⚠️ Chromium V8 堆内存超标！峰值达到 {peak_heap} MB")

    if fps_list and min(fps_list) < 15.0:
        alerts.append(f"⚠️ WebRTC 像素流出现明显掉帧！最低帧率仅 {min(fps_list)} FPS")

    if peak_ue_commit and peak_ue_commit > 12288.0:
        alerts.append(
            f"⚠️ UE5 引擎专用提交量 (Commit) 严重膨胀！峰值达到 {round(peak_ue_commit / 1024, 2)} GB (健康阈值: 小于 12 GB)"
        )

    if peak_host_commit and peak_host_commit > 85.0:
        alerts.append(
            f"⚠️ 宿主机专用虚拟提交负荷过高！峰值达到 {peak_host_commit}% (OOM 崩溃风险预警)"
        )

    return PerformanceSummaryResponse(
        task_id=task_id,
        sample_count=count,
        peak_dom_count=peak_dom,
        avg_dom_count=round(sum(doms) / len(doms), 1) if doms else 0.0,
        latest_dom_count=latest_dom,
        peak_listeners_count=peak_listeners,
        latest_listeners_count=latest_listeners,
        peak_js_heap_mb=peak_heap,
        avg_js_heap_mb=round(sum(heaps) / len(heaps), 2) if heaps else 0.0,
        latest_js_heap_mb=latest_heap,
        avg_webrtc_fps=round(sum(fps_list) / len(fps_list), 1) if fps_list else None,
        min_webrtc_fps=min(fps_list) if fps_list else None,
        peak_chrome_cpu_percent=max(chrome_cpus) if chrome_cpus else None,
        peak_chrome_memory_mb=max(chrome_mems) if chrome_mems else None,
        peak_ue_cpu_percent=max(ue_cpus) if ue_cpus else None,
        avg_ue_cpu_percent=round(sum(ue_cpus) / len(ue_cpus), 1) if ue_cpus else None,
        peak_ue_memory_mb=max(ue_mems) if ue_mems else None,
        peak_ue_commit_mb=peak_ue_commit,
        peak_host_commit_load_percent=peak_host_commit,
        peak_gpu_usage_percent=max(gpus) if gpus else None,
        peak_gpu_memory_mb=max(gpu_mems) if gpu_mems else None,
        health_alerts=alerts,
    )




@router.post(
    "/api/metrics/cleanup",
    response_model=MetricsCleanupResponse,
    tags=["4. 多核全栈性能监控"],
    summary="手动触发滚动清理历史过期性能打点数据",
    description="支持指定保留天数（默认 7 天），滚动清理超期性能打点，释放存储空间保障极速读写。",
)
def trigger_metrics_cleanup(
    retention_days: int = Query(
        default=7, ge=1, le=90, description="性能时序数据保留天数"
    ),
):
    """
    手动或定时滚动清理过期的性能打点时序数据。

    Args:
        retention_days: 保留天数上限

    Returns:
        MetricsCleanupResponse: 清理统计与状态
    """
    deleted = performance_monitor.cleanup_expired_metrics(retention_days=retention_days)

    return {
        "code": 200,
        "message": f"成功清理 {deleted} 条超过 {retention_days} 天的历史性能时序数据",
        "deleted_count": deleted,
        "retention_days": retention_days,
    }


