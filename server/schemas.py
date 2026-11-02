from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
import datetime


class TaskCreate(BaseModel):
    name: Optional[str] = "自动化探索巡检任务"
    app_name: str = Field(default="zhaiwan", description="矿山应用: zhaiwan / liwutong")
    mode: str = Field(default="explore", description="模式: explore, smoke, case, all")
    macro_objective: Optional[str] = Field(
        default="开启全栈地毯式扫荡：深度遍历所有顶级菜单与二级业务菜单，全量探测核心业务组件与弹窗抽屉，寻找白屏、数据不一致或深层状态丢失 Bug，确保 100% 页面全覆盖度！",
        description="宏观探索目标"
    )
    max_steps: int = Field(default=200, ge=5, le=5000, description="最大探索步数")
    max_times: int = Field(default=60, ge=1, le=1440, description="最大时间限制 (分钟)")
    reset_memory: bool = Field(default=False, description="是否清空长期拓扑记忆从零开始")
    ignore_errors: bool = Field(default=True, description="步骤报错时是否全局忽略继续探索")
    explore_context: Optional[str] = Field(default="docs/explore_rules_zhaiwan.md", description="项目背景规则文件路径")
    case_path: Optional[str] = Field(default=None, description="单一 YAML 用例路径 (仅 case 模式生效)")


class TaskResponse(BaseModel):
    id: str
    name: str
    app_name: str
    mode: str
    status: str
    macro_objective: Optional[str] = None
    max_steps: int
    max_times: int
    pid: Optional[int] = None
    start_time: Optional[datetime.datetime] = None
    end_time: Optional[datetime.datetime] = None
    duration: Optional[str] = None
    total_steps: int = 0
    planner_phases: int = 0
    coverage_rate: float = 0.0
    bugs_count: int = 0
    apis_count: int = 0
    yaml_steps_count: int = 0
    report_url: Optional[str] = None
    exit_code: Optional[int] = None
    error_message: Optional[str] = None

    class Config:
        from_attributes = True


class BugResponse(BaseModel):
    id: str
    task_id: Optional[str] = None
    title: str
    severity: str
    status: str
    assignee: str
    zentao_id: Optional[str] = None
    ui_path: Optional[str] = None
    target_element: Optional[str] = None
    actual_error: Optional[str] = None
    analysis_notes: Optional[str] = None
    screenshot_path: Optional[str] = None
    occurrences: int = 1
    first_seen: Optional[datetime.datetime] = None
    last_seen: Optional[datetime.datetime] = None

    class Config:
        from_attributes = True


class PerformanceMetricResponse(BaseModel):
    id: int
    task_id: str
    timestamp: datetime.datetime
    step_number: Optional[int] = None
    page_scope: Optional[str] = None
    dom_count: int = 0
    listeners_count: int = 0
    js_heap_mb: float = 0.0
    js_heap_total_mb: float = 0.0
    echarts_instances: int = 0
    canvas_count: int = 0
    video_instances: int = 0
    webrtc_fps: Optional[float] = None
    chrome_pid: Optional[int] = None
    chrome_cpu_percent: Optional[float] = None
    chrome_memory_mb: Optional[float] = None
    ue_pid: Optional[int] = None
    ue_cpu_percent: Optional[float] = None
    ue_memory_mb: Optional[float] = None
    gpu_usage_percent: Optional[float] = None
    gpu_memory_mb: Optional[float] = None

    class Config:
        from_attributes = True


class LivePerformanceSnapshotResponse(BaseModel):
    app_name: str
    timestamp: datetime.datetime
    cdp_online: bool = False
    ue_online: bool = False
    gpu_online: bool = False
    page_scope: Optional[str] = None
    dom_count: int = 0
    listeners_count: int = 0
    js_heap_mb: float = 0.0
    js_heap_total_mb: float = 0.0
    echarts_instances: int = 0
    canvas_count: int = 0
    video_instances: int = 0
    webrtc_fps: Optional[float] = None
    chrome_pid: Optional[int] = None
    chrome_cpu_percent: Optional[float] = None
    chrome_memory_mb: Optional[float] = None
    ue_pid: Optional[int] = None
    ue_cpu_percent: Optional[float] = None
    ue_memory_mb: Optional[float] = None
    gpu_usage_percent: Optional[float] = None
    gpu_memory_mb: Optional[float] = None


class PerformanceSummaryResponse(BaseModel):
    task_id: str
    sample_count: int = 0
    peak_dom_count: int = 0
    avg_dom_count: float = 0.0
    latest_dom_count: int = 0
    peak_listeners_count: int = 0
    latest_listeners_count: int = 0
    peak_js_heap_mb: float = 0.0
    avg_js_heap_mb: float = 0.0
    latest_js_heap_mb: float = 0.0
    avg_webrtc_fps: Optional[float] = None
    min_webrtc_fps: Optional[float] = None
    peak_chrome_cpu_percent: Optional[float] = None
    peak_chrome_memory_mb: Optional[float] = None
    peak_ue_cpu_percent: Optional[float] = None
    avg_ue_cpu_percent: Optional[float] = None
    peak_ue_memory_mb: Optional[float] = None
    peak_gpu_usage_percent: Optional[float] = None
    peak_gpu_memory_mb: Optional[float] = None
    health_alerts: List[str] = Field(default_factory=list)


class ConfigOptionsResponse(BaseModel):
    apps: List[Dict[str, str]]
    modes: List[Dict[str, str]]
    prompt_templates: List[Dict[str, str]]
    zentao_configured: bool

