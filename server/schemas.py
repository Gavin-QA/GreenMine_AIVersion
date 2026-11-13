"""
=============================================================================
Electron Vision AI - 服务端 API 数据契约与 Pydantic 校验模型集 (Schemas)
=============================================================================
本模块定义了所有供 FastAPI 路由层、前端大盘工作台及第三方系统交互的请求体 (Request)
与响应体 (Response) Pydantic 数据契约模型。

模型特性：
1. 全字段 Field 装饰：提供详尽的 description 中文业务说明与 examples 样例，直通 Swagger / OpenAPI。
2. UTC 时间规范化序列化：统一无时区时间为带 'Z' 后缀的 ISO 8601 标准格式。
3. ORM 自动解包支持：全面启用 from_attributes = True。
"""

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_serializer, field_validator
import datetime


def _serialize_datetime_utc(v: Optional[datetime.datetime]) -> Optional[str]:
    """统一将无时区 UTC 时间序列化为标准带有 'Z' 后缀的 ISO 8601 字符串"""
    if v is None:
        return None
    if v.tzinfo is None:
        return v.strftime('%Y-%m-%dT%H:%M:%S.%f') + 'Z'
    return v.isoformat()


class TaskCreate(BaseModel):
    """创建巡检任务请求体"""
    name: Optional[str] = Field(
        default="自动化探索巡检任务",
        description="任务友好展示名称，如：【寨湾】首页与生产管理深度巡检",
        examples=["【寨湾】地毯式扫荡任务"]
    )
    app_name: str = Field(
        default="zhaiwan",
        description="矿山应用系统代号 (zhaiwan: 寨湾矿山 / liwutong: 里伍铜矿山)",
        examples=["zhaiwan"]
    )
    mode: str = Field(
        default="explore",
        description="运行模式：explore (AI自主探索黑客模式) / smoke (二级菜单冒烟) / case (单用例) / all (批量回归)",
        examples=["explore"]
    )
    macro_objective: Optional[str] = Field(
        default="开启全栈地毯式扫荡：深度遍历所有顶级菜单与二级业务菜单，全量探测核心业务组件与弹窗抽屉，寻找白屏、数据不一致或深层状态丢失 Bug，确保 100% 页面全覆盖度！",
        description="宏观探索目标提示词 (Macro Objective Prompt)，直接引导大模型探索规划方向",
        examples=["全面探测中央 3D 矿山数字孪生模型健康度，重点执行视口旋转与抗压甩动"]
    )
    max_steps: Optional[int] = Field(
        default=0,
        ge=0,
        le=5000,
        description="最大允许执行的动作步数上限 (Steps)，0 表示不限制",
        examples=[200]
    )
    max_times: Optional[int] = Field(
        default=60,
        ge=1,
        le=1440,
        description="最大运行时间限制 (单位：分钟)，超时自动安全退出",
        examples=[60]
    )

    @field_validator('max_steps', mode='before')
    @classmethod
    def normalize_max_steps(cls, v: Any) -> int:
        if v is None or v == "":
            return 0
        try:
            val = int(v)
            return val if val >= 0 else 0
        except (ValueError, TypeError):
            return 0

    @field_validator('max_times', mode='before')
    @classmethod
    def normalize_max_times(cls, v: Any) -> int:
        if v is None or v == "":
            return 60
        try:
            val = int(v)
            return val if val >= 1 else 60
        except (ValueError, TypeError):
            return 60
    reset_memory: bool = Field(
        default=False,
        description="是否清空长期拓扑与探索历史记忆从零开始 (默认为 False，继承已有记忆拓扑)",
        examples=[False]
    )
    ignore_errors: bool = Field(
        default=True,
        description="单步报错时是否忽略软错误继续往下执行探索 (True: 容错继续; False: 遇错立刻阻断退出)",
        examples=[True]
    )
    explore_context: Optional[str] = Field(
        default="docs/explore_rules_zhaiwan.md",
        description="业务背景规则上下文 markdown 文件路径",
        examples=["docs/explore_rules_zhaiwan.md"]
    )
    case_path: Optional[str] = Field(
        default=None,
        description="单一 YAML 用例路径 (仅在 mode='case' 确定性用例模式下生效)",
        examples=["test_cases/case_zhaiwan_smoke.yaml"]
    )
    tour: bool = Field(default=False, description="是否启用二级菜单全量冒烟巡检策略 (--tour)")
    resume_from: Optional[str] = Field(default=None, description="断点续传历史运行目录 (--resume-from)")
    reexplore: Optional[str] = Field(default=None, description="强制重新探索指定业务模块 (--reexplore)")
    start_delay: Optional[float] = Field(default=None, description="启动等待时间秒数 (--start-delay)")
    wait_ready: Optional[str] = Field(default=None, description="视觉智能就绪自然语言判定条件 (--wait-ready)")
    wait_timeout: Optional[float] = Field(default=60.0, description="视觉智能就绪超时秒数 (--wait-timeout)")
    ignore_env_check: bool = Field(default=False, description="是否忽略 Launcher 客户端环境前置校验 (--ignore-env-check)")


class TaskResponse(BaseModel):
    """巡检任务信息响应模型"""
    id: str = Field(description="任务全局唯一识别码 (如 task_20261102_153022)")
    name: str = Field(description="任务展示名称")
    app_name: str = Field(description="目标矿山系统代号")
    mode: str = Field(description="执行模式 (explore/smoke/case/all)")
    status: str = Field(description="当前状态：pending(待运行) / running(执行中) / completed(成功完成) / stopped(手动终止) / failed(异常退出)")
    macro_objective: Optional[str] = Field(default=None, description="任务执行的宏观意图提示词")
    max_steps: int = Field(description="配置的最大步数")
    max_times: int = Field(description="配置的最大超时时间(分钟)")
    tour: bool = Field(default=False, description="是否开启二级菜单冒烟巡检策略")
    resume_from: Optional[str] = Field(default=None, description="断点续传历史运行目录")
    reexplore: Optional[str] = Field(default=None, description="强制重探模块名")
    start_delay: Optional[float] = Field(default=None, description="启动缓冲等待秒数")
    wait_ready: Optional[str] = Field(default=None, description="视觉就绪条件")
    wait_timeout: Optional[float] = Field(default=60.0, description="视觉就绪超时时间")
    ignore_env_check: bool = Field(default=False, description="是否跳过环境前置校验")
    pid: Optional[int] = Field(default=None, description="后台执行子进程物理 PID")
    trigger_type: Optional[str] = Field(default="manual", description="触发来源: manual(手动创建) / scheduled(计划下发)")
    start_time: Optional[datetime.datetime] = Field(default=None, description="任务启动时间戳 (UTC)")
    end_time: Optional[datetime.datetime] = Field(default=None, description="任务结束时间戳 (UTC)")
    duration: Optional[str] = Field(default=None, description="实际运行时长 (如 '3h 25m 5s')")
    total_steps: int = Field(default=0, description="最终实际执行的总步数")
    planner_phases: int = Field(default=0, description="Planner 宏观规划轮次数")
    coverage_rate: float = Field(default=0.0, description="大屏菜单与业务视图全景覆盖率 (百分比 0.0 ~ 100.0)")
    bugs_count: int = Field(default=0, description="本轮任务捕获到的有效缺陷总数")
    apis_count: int = Field(default=0, description="本轮底层网络包静默拦截解析的接口总数")
    yaml_steps_count: int = Field(default=0, description="本轮自动逆向生成的确定性 YAML 步骤总数")
    report_url: Optional[str] = Field(default=None, description="本次运行专属单次全景 HTML 报告相对链接")
    exit_code: Optional[int] = Field(default=None, description="子进程物理退出码 (0 为正常退出)")
    error_message: Optional[str] = Field(default=None, description="异常失败退出时的具体错误信息")

    @field_serializer('start_time', 'end_time', when_used='json')
    def serialize_task_times(self, v: Optional[datetime.datetime]):
        return _serialize_datetime_utc(v)

    class Config:
        from_attributes = True


class BugUpdate(BaseModel):
    """缺陷信息在线编辑请求模型"""
    title: Optional[str] = Field(default=None, description="缺陷标题与摘要")
    severity: Optional[str] = Field(default=None, description="严重程度: High / Medium / Low")
    status: Optional[str] = Field(default=None, description="状态: 激活 / 已提单 / 误报 / 已解决 / 已关闭")
    assignee: Optional[str] = Field(default=None, description="责任人: 陈贻雄 / 梅本霞 等")
    zentao_id: Optional[str] = Field(default=None, description="禅道系统关联单号")
    analysis_notes: Optional[str] = Field(default=None, description="AI 智能初诊分析与排查指引说明")
    remark: Optional[str] = Field(default=None, description="人工复核备注或关闭原因说明 (非必填)")
    ui_path: Optional[str] = Field(default=None, description="页面层级路径")


class BugResponse(BaseModel):
    """缺陷资产记录响应模型"""
    id: str = Field(description="全局统一缺陷编号 (格式如 BUG-20261030-001)")
    task_id: Optional[str] = Field(default=None, description="首次发现或最近复现该缺陷的任务 ID")
    run_id: Optional[str] = Field(default=None, description="首次发现或最近复现的运行批次编号 (如 explore_20261103_183408)")
    app_name: Optional[str] = Field(default="zhaiwan", description="归属矿山应用代号 (zhaiwan / tianrui / liwutong)")
    title: str = Field(description="缺陷标题与摘要描述")
    severity: str = Field(description="严重等级：High(高) / Medium(中) / Low(低)")
    status: str = Field(description="缺陷生命周期状态：激活 / 已提单 / 误报 / 已关闭 / 已解决")
    assignee: str = Field(description="根据前后端责任人智能分流指派的人员 (陈贻雄 / 梅本霞)")
    zentao_id: Optional[str] = Field(default=None, description="已提交至禅道系统的关联 Bug 编号 (如 1188)")
    ui_path: Optional[str] = Field(default=None, description="缺陷发生的页面导航路径与层级结构")
    target_element: Optional[str] = Field(default=None, description="案发时正在交互的目标 UI 元素自然语言描述")
    actual_error: Optional[str] = Field(default=None, description="现场捕获到的底层异常原始报错文本或堆栈")
    analysis_notes: Optional[str] = Field(default=None, description="大模型生成的智能初诊分析、根因推断与排查指引")
    remark: Optional[str] = Field(default=None, description="人工复核备注或关闭原因说明")
    screenshot_path: Optional[str] = Field(default=None, description="案发现场第一视角的无损高清截图相对路径")
    step: Optional[str] = Field(default=None, description="最新复现时的交互动作步骤描述")
    occurrences: int = Field(default=1, description="AI 语义去重累计匹配到的历史复现总次数")
    first_seen: Optional[datetime.datetime] = Field(default=None, description="该缺陷首次被捕获的时间戳")
    last_seen: Optional[datetime.datetime] = Field(default=None, description="该缺陷最近一次被复现的时间戳")
    recurrence_history: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="历史复现时间轴轨迹 (保留最近复现历史)")

    class Config:
        from_attributes = True


class BugListResponse(BaseModel):
    """缺陷资产记录物理分页响应模型"""
    total: int = Field(description="满足过滤条件的总记录数")
    page: int = Field(default=1, description="当前页码 (从1开始)")
    page_size: int = Field(default=15, description="每页最大拉取记录数")
    items: List[BugResponse] = Field(default_factory=list, description="当前页缺陷记录列表")


class PerformanceMetricResponse(BaseModel):
    """全景性能时序数据单点响应模型"""
    id: int = Field(description="自增主键序号")
    task_id: str = Field(description="所属任务全局识别码")
    timestamp: datetime.datetime = Field(description="采样时间戳")
    step_number: Optional[int] = Field(default=None, description="当前采样时刻对应的用例或探索步骤编号")
    page_scope: Optional[str] = Field(default=None, description="当前采样时刻所在的大屏页面路径哈希/路由")
    
    # Chromium / DOM / WebRTC 维度
    dom_count: int = Field(default=0, description="页面当前实时 DOM 节点总数 (Nodes)")
    listeners_count: int = Field(default=0, description="页面当前注册的 JS 事件监听器总数 (JSEventListeners)")
    js_heap_mb: float = Field(default=0.0, description="V8 引擎 JS 堆内存当前已用空间 (JSHeapUsedSize, 单位: MB)")
    js_heap_total_mb: float = Field(default=0.0, description="V8 引擎 JS 堆内存物理分配总空间 (JSHeapTotalSize, 单位: MB)")
    echarts_instances: int = Field(default=0, description="当前页面挂载的活跃 ECharts 图表实例总数")
    canvas_count: int = Field(default=0, description="页面中渲染的 HTML5 Canvas 画布标签数")
    video_instances: int = Field(default=0, description="页面中 Video 视频/WebRTC 像素流接收容器标签数")
    webrtc_fps: Optional[float] = Field(default=None, description="WebRTC 像素流实时解码渲染帧率 (FPS)")
    
    # Electron 渲染进程树系统开销
    chrome_pid: Optional[int] = Field(default=None, description="Chromium 主渲染进程 PID")
    chrome_cpu_percent: Optional[float] = Field(default=None, description="Chromium / Electron 进程树系统 CPU 占用百分比")
    chrome_memory_mb: Optional[float] = Field(default=None, description="Chromium / Electron 进程树物理常驻内存总占用 (RSS, 单位: MB)")
    
    # 伴生 UE5 引擎进程开销
    ue_pid: Optional[int] = Field(default=None, description="伴生 UE5 引擎主进程 PID")
    ue_cpu_percent: Optional[float] = Field(default=None, description="伴生 UE5 引擎进程 CPU 占用百分比")
    ue_memory_mb: Optional[float] = Field(default=None, description="伴生 UE5 引擎进程物理常驻内存占用 (RSS / Working Set, 单位: MB)")
    ue_commit_mb: Optional[float] = Field(default=None, description="伴生 UE5 引擎进程专用虚拟提交量 (Private Bytes / Commit, 单位: MB)")
    
    # 宿主机系统整体内存水位
    host_ram_load_percent: Optional[float] = Field(default=None, description="宿主机物理内存使用率百分比")
    host_commit_load_percent: Optional[float] = Field(default=None, description="宿主机虚拟内存提交量使用率百分比")
    
    # 独立 GPU 显卡开销
    gpu_usage_percent: Optional[float] = Field(default=None, description="独立显卡 GPU 3D 渲染核心负载占用百分比")
    gpu_memory_mb: Optional[float] = Field(default=None, description="独立显卡 VRAM 专用显存已用大小 (单位: MB)")

    @field_serializer('timestamp', when_used='json')
    def serialize_metric_timestamp(self, v: datetime.datetime):
        return _serialize_datetime_utc(v)

    class Config:
        from_attributes = True


class LivePerformanceSnapshotResponse(BaseModel):
    """即时物理环境性能切片响应模型"""
    app_name: str = Field(description="目标矿山应用代号")
    timestamp: datetime.datetime = Field(description="探测时间戳")
    cdp_online: bool = Field(default=False, description="Chromium CDP 调试接口连接是否在线")
    ue_online: bool = Field(default=False, description="伴生 UE5 引擎进程是否正在物理运行")
    gpu_online: bool = Field(default=False, description="独立显卡 GPU 监控探针是否正常通信")
    page_scope: Optional[str] = Field(default=None, description="当前大屏主页面路由状态")
    dom_count: int = Field(default=0, description="实时 DOM 节点总数")
    listeners_count: int = Field(default=0, description="实时 JS 事件监听器总数")
    js_heap_mb: float = Field(default=0.0, description="实时 V8 JS 堆内存 (MB)")
    js_heap_total_mb: float = Field(default=0.0, description="实时 V8 JS 堆内存总容量 (MB)")
    echarts_instances: int = Field(default=0, description="活跃 ECharts 实例数")
    canvas_count: int = Field(default=0, description="Canvas 数量")
    video_instances: int = Field(default=0, description="视频流标签数")
    webrtc_fps: Optional[float] = Field(default=None, description="WebRTC 实时帧率 (FPS)")
    chrome_pid: Optional[int] = Field(default=None, description="Chrome 主 PID")
    chrome_cpu_percent: Optional[float] = Field(default=None, description="Chrome 进程树 CPU (%)")
    chrome_memory_mb: Optional[float] = Field(default=None, description="Chrome 进程树物理内存 (MB)")
    ue_pid: Optional[int] = Field(default=None, description="UE5 进程 PID")
    ue_cpu_percent: Optional[float] = Field(default=None, description="UE5 进程归一化 CPU (%)，对齐任务管理器单进程视角")
    ue_cpu_raw_percent: Optional[float] = Field(default=None, description="UE5 进程多核累计原始算力占用率 (%)")
    ue_memory_mb: Optional[float] = Field(default=None, description="UE5 进程物理内存 (MB)")
    ue_commit_mb: Optional[float] = Field(default=None, description="UE5 进程专用虚拟提交量 (Commit, 单位: MB)")
    host_ram_load_percent: Optional[float] = Field(default=None, description="整机物理内存使用率 (%)")
    host_commit_load_percent: Optional[float] = Field(default=None, description="整机虚拟内存提交率 (%)")
    host_commit_avail_gb: Optional[float] = Field(default=None, description="整机剩余可用虚拟提交量 (GB)")
    cpu_cores: int = Field(default=12, description="本机系统逻辑处理器核心总数")
    gpu_usage_percent: Optional[float] = Field(default=None, description="GPU 3D 核心占用率 (%)")
    gpu_memory_mb: Optional[float] = Field(default=None, description="GPU 显存占用 (MB)")

    @field_serializer('timestamp', when_used='json')
    def serialize_snapshot_timestamp(self, v: datetime.datetime):
        return _serialize_datetime_utc(v)


class PerformanceSummaryResponse(BaseModel):
    """任务全生命周期性能指标汇总与健康诊断模型"""
    task_id: str = Field(description="任务全局识别码")
    sample_count: int = Field(default=0, description="全生命周期采样的性能快照样本总点数")
    peak_dom_count: int = Field(default=0, description="整个运行周期的 DOM 节点历史峰值")
    avg_dom_count: float = Field(default=0.0, description="全周期 DOM 节点平均水平")
    latest_dom_count: int = Field(default=0, description="最新一次采样的 DOM 节点数量")
    peak_listeners_count: int = Field(default=0, description="JS 事件监听器历史峰值")
    latest_listeners_count: int = Field(default=0, description="最新一次采样的事件监听器数量")
    peak_js_heap_mb: float = Field(default=0.0, description="V8 JS 堆内存历史峰值 (MB)")
    avg_js_heap_mb: float = Field(default=0.0, description="V8 JS 堆内存全周期平均占用 (MB)")
    latest_js_heap_mb: float = Field(default=0.0, description="最新一次采样的 JS 堆内存 (MB)")
    avg_webrtc_fps: Optional[float] = Field(default=None, description="WebRTC 像素流全程平均帧率")
    min_webrtc_fps: Optional[float] = Field(default=None, description="WebRTC 像素流全程最低谷底帧率 (反映卡顿跌帧)")
    peak_chrome_cpu_percent: Optional[float] = Field(default=None, description="Chrome 进程树最高 CPU 占用率 (%)")
    peak_chrome_memory_mb: Optional[float] = Field(default=None, description="Chrome 进程树最高物理内存占用 (MB)")
    peak_ue_cpu_percent: Optional[float] = Field(default=None, description="UE5 引擎最高 CPU 占用率 (%)")
    avg_ue_cpu_percent: Optional[float] = Field(default=None, description="UE5 引擎全周期平均 CPU 占用率 (%)")
    peak_ue_memory_mb: Optional[float] = Field(default=None, description="UE5 引擎最高物理内存占用 (MB)")
    peak_ue_commit_mb: Optional[float] = Field(default=None, description="UE5 引擎最高专用虚拟提交量 (MB)")
    peak_host_commit_load_percent: Optional[float] = Field(default=None, description="宿主机最高虚拟提交量负荷率 (%)")
    peak_gpu_usage_percent: Optional[float] = Field(default=None, description="独立显卡最高 3D 渲染核心负载 (%)")
    peak_gpu_memory_mb: Optional[float] = Field(default=None, description="独立显卡最高专用显存占用 (MB)")
    health_alerts: List[str] = Field(
        default_factory=list,
        description="自动化识别出的性能健康诊断告警列表 (如 DOM 泄漏爆炸预警、掉帧预警等)"
    )


class PresetTaskCreate(BaseModel):
    """保存/更新预设巡检任务请求模型"""
    id: Optional[str] = Field(default=None, description="预设 ID (空则系统自动生成)")
    title: str = Field(description="预设任务标题", examples=["【我的定制】首页重点回归"])
    app_name: str = Field(default="zhaiwan", description="矿山应用: zhaiwan / liwutong")
    mode: str = Field(default="explore", description="模式: explore / smoke / case / all")
    macro_objective: str = Field(description="预设探索目标提示词")
    max_steps: Optional[int] = Field(default=0, ge=0, le=5000, description="最大步数 (0 表示不限)")
    max_times: Optional[int] = Field(default=60, ge=1, le=1440, description="最大时间 (分钟)")

    @field_validator('max_steps', mode='before')
    @classmethod
    def normalize_preset_max_steps(cls, v: Any) -> int:
        if v is None or v == "":
            return 0
        try:
            val = int(v)
            return val if val >= 0 else 0
        except (ValueError, TypeError):
            return 0

    @field_validator('max_times', mode='before')
    @classmethod
    def normalize_preset_max_times(cls, v: Any) -> int:
        if v is None or v == "":
            return 60
        try:
            val = int(v)
            return val if val >= 1 else 60
        except (ValueError, TypeError):
            return 60
    reset_memory: bool = Field(default=False, description="是否重置长期记忆")
    ignore_errors: bool = Field(default=True, description="是否容错继续")
    case_path: Optional[str] = Field(default=None, description="用例路径 (case模式生效)")
    badge: Optional[str] = Field(default="自定义", description="标签 (推荐/抗压/冒烟/回归/自定义)")
    description: Optional[str] = Field(default=None, description="简要描述说明")
    tour: bool = Field(default=False, description="是否开启二级菜单冒烟巡检策略")
    resume_from: Optional[str] = Field(default=None, description="断点续传历史运行目录")
    reexplore: Optional[str] = Field(default=None, description="强制重探模块名")
    start_delay: Optional[float] = Field(default=None, description="启动缓冲等待秒数")
    wait_ready: Optional[str] = Field(default=None, description="视觉就绪条件")
    wait_timeout: Optional[float] = Field(default=60.0, description="视觉就绪超时时间")
    ignore_env_check: bool = Field(default=False, description="是否跳过环境前置校验")


class PresetTaskResponse(BaseModel):
    """预设巡检任务模板定义"""
    id: str = Field(description="预设任务唯一标识 (如 preset_zhaiwan_explore_full)")
    title: str = Field(description="预设任务标题")
    app_name: str = Field(description="目标矿山系统代号")
    mode: str = Field(description="运行模式 (explore/smoke/case/all)")
    macro_objective: str = Field(description="预设宏观意图提示词")
    max_steps: Optional[int] = Field(default=0, description="推荐最大执行步数")
    max_times: int = Field(description="推荐超时时间 (分钟)")
    reset_memory: bool = Field(default=False, description="是否重置记忆")
    ignore_errors: bool = Field(default=True, description="是否忽略软错误继续")
    case_path: Optional[str] = Field(default=None, description="用例文件相对路径")
    badge: str = Field(default="推荐", description="标签 (推荐/高优/抗压/冒烟/自定义)")
    description: Optional[str] = Field(default=None, description="业务场景与测试目标简要说明")
    tour: bool = Field(default=False, description="是否开启二级菜单冒烟巡检策略")
    resume_from: Optional[str] = Field(default=None, description="断点续传历史运行目录")
    reexplore: Optional[str] = Field(default=None, description="强制重探模块名")
    start_delay: Optional[float] = Field(default=None, description="启动缓冲等待秒数")
    wait_ready: Optional[str] = Field(default=None, description="视觉就绪条件")
    wait_timeout: Optional[float] = Field(default=60.0, description="视觉就绪超时时间")
    ignore_env_check: bool = Field(default=False, description="是否跳过环境前置校验")
    is_system: bool = Field(default=False, description="是否为系统只读预设")

    class Config:
        from_attributes = True


class ConfigOptionsResponse(BaseModel):
    """前端表单初始化选项字典响应模型"""
    apps: List[Dict[str, str]] = Field(description="可选矿山大屏应用清单 (key, name, desc)")
    modes: List[Dict[str, str]] = Field(description="可选运行模式清单 (key, name, desc)")
    yaml_cases: List[Dict[str, str]] = Field(default_factory=list, description="本地 test_cases 目录下的标准 YAML 用例列表")
    prompt_templates: List[Dict[str, str]] = Field(description="高质量预置探索提示词模板清单 (title, prompt)")
    zentao_configured: bool = Field(description="当前后端是否已正确配置公司禅道系统免密提单鉴权")
    zentao_base_url: Optional[str] = Field(default=None, description="公司禅道系统 Web 根地址 (用于单号超链接动态拼接)")
    report_hub_url: Optional[str] = Field(default=None, description="产物总门户统一访问地址")


class AppControlResponse(BaseModel):
    """客户端生命周期控制响应模型"""
    status: str = Field(description="执行状态 (success / error)")
    message: str = Field(description="提示消息")
    app_name: str = Field(description="目标矿山应用代号")
    debug_port: Optional[int] = Field(default=None, description="绑定的 CDP 调试端口")
    pid: Optional[int] = Field(default=None, description="拉起的主进程 PID")


class SchedulePlanCreate(BaseModel):
    """新建调度执行计划请求模型 (按应用与关联任务模板)"""
    name: Optional[str] = Field(default=None, description="调度计划自定义名称 (如留空则自动根据预设填充)")
    app_name: str = Field(description="目标矿山应用代号 (如 zhaiwan / tianrui / liwutong)")
    preset_id: str = Field(description="关联的预设巡检任务模板 ID (如 preset_user_xxx)")
    priority: int = Field(default=3, description="队列排序优先级 (1-5，数值越小越优先执行)")
    scheduled_at: Optional[datetime.datetime] = Field(default=None, description="预约定时触发时间 (留空则立即排队)")
    cron_mode: Optional[str] = Field(default="once", description="巡检周期模式: once(单次)/daily(天)/weekly(每周)/monthly(每月)")
    cron_spec: Optional[str] = Field(default="", description="周期规则说明")
    time_of_day: Optional[str] = Field(default="", description="每日执行时间点如 18:35:00")
    is_active: Optional[int] = Field(default=1, description="是否启用 (1=启用, 0=停用)")


class QueueItemCreate(BaseModel):
    """加入调度队列请求模型"""
    task_id: str = Field(description="目标关联的巡检任务 ID")
    priority: int = Field(default=100, description="队列排序优先级 (数值越小越优先执行)")
    scheduled_at: Optional[datetime.datetime] = Field(default=None, description="预约定时触发时间 (UTC ISO8601，留空则立即入队顺序执行)")
    cron_mode: Optional[str] = Field(default="once", description="巡检周期模式")
    cron_spec: Optional[str] = Field(default="", description="周期规则")
    time_of_day: Optional[str] = Field(default="", description="执行时间点")
    is_active: Optional[int] = Field(default=1, description="是否启用")


class QueueItemResponse(BaseModel):
    """队列项信息响应模型"""
    id: str = Field(description="队列记录唯一标识")
    task_id: str = Field(description="关联的任务 ID")
    task_name: Optional[str] = Field(default=None, description="关联任务名称")
    app_name: Optional[str] = Field(default=None, description="任务所属矿山应用")
    mode: Optional[str] = Field(default=None, description="任务运行模式")
    max_steps: Optional[int] = Field(default=None, description="配置最大步数")
    max_times: Optional[int] = Field(default=None, description="配置最大时长(分钟)")
    priority: int = Field(default=100, description="优先级")
    status: str = Field(description="队列状态：pending/running/completed/failed/canceled")
    scheduled_at: Optional[datetime.datetime] = Field(default=None, description="预约定时时间")
    cron_mode: Optional[str] = Field(default="once", description="巡检周期模式: once/daily/weekly/monthly")
    cron_spec: Optional[str] = Field(default="", description="周期规则")
    time_of_day: Optional[str] = Field(default="", description="执行时间点")
    is_active: Optional[int] = Field(default=1, description="是否启用")
    created_at: Optional[datetime.datetime] = Field(default=None, description="创建入队时间")
    started_at: Optional[datetime.datetime] = Field(default=None, description="开始执行时间")
    finished_at: Optional[datetime.datetime] = Field(default=None, description="结束时间")
    error_message: Optional[str] = Field(default=None, description="执行错误说明")

    @field_serializer('scheduled_at', 'created_at', 'started_at', 'finished_at', when_used='json')
    def serialize_times(self, v: Optional[datetime.datetime]):
        return _serialize_datetime_utc(v)

    class Config:
        from_attributes = True


# =============================================================================
# 6. 系统通用响应与业务子模型 (补全 Swagger 字段级元数据与中文注释)
# =============================================================================


class StandardActionResponse(BaseModel):
    """标准通用操作结果响应模型"""
    code: int = Field(default=200, description="业务状态码 (200 为成功)", examples=[200])
    message: str = Field(description="操作结果描述说明", examples=["操作执行成功"])
    data: Optional[Any] = Field(default=None, description="携带的附加业务数据")


class HealthCheckResponse(BaseModel):
    """平台健康心跳检查响应模型"""
    status: str = Field(default="healthy", description="服务健康状态 (healthy)", examples=["healthy"])
    service: str = Field(default="Electron AI Vision Platform", description="服务名称标识", examples=["Electron AI Vision Platform"])
    timestamp: str = Field(description="当前 UTC 时间戳 (ISO 8601)", examples=["2026-11-11T09:40:00.000Z"])


class BugUpdateCompatibleRequest(BaseModel):
    """兼容大盘统一门户历史调用的缺陷状态/详情编辑请求体"""
    bug_id: Optional[str] = Field(default=None, description="缺陷编号 (如 BUG-20261030-001，与 id 等效)", examples=["BUG-20261030-001"])
    id: Optional[str] = Field(default=None, description="缺陷唯一编号 (与 bug_id 等效)", examples=["BUG-20261030-001"])
    run_id: Optional[str] = Field(default=None, description="首次发现或复现的运行批次编号", examples=["explore_20261103_183408"])
    app_name: Optional[str] = Field(default=None, description="归属矿山应用代号 (zhaiwan / liwutong 等)", examples=["zhaiwan"])
    status: Optional[str] = Field(default=None, description="缺陷生命周期状态: 激活 / 已提单 / 误报 / 已解决 / 已关闭", examples=["已提单"])
    severity: Optional[str] = Field(default=None, description="严重程度: High / Medium / Low", examples=["High"])
    assignee: Optional[str] = Field(default=None, description="根据前后端责任分流指派的人员 (陈贻雄 / 梅本霞 等)", examples=["陈贻雄"])
    zentao_id: Optional[str] = Field(default=None, description="关联的禅道 Bug 编号 (如 1188)", examples=["1188"])
    analysis_notes: Optional[str] = Field(default=None, description="AI 智能初诊分析、根因推断与排查指引说明", examples=["前端三维视口容器在接收 WebRTC 视频流时未正常监听 resize 事件导致黑屏"])
    remark: Optional[str] = Field(default=None, description="人工复核备注或关闭原因说明", examples=["已在前端 2.4.1 版本修复"])
    ui_path: Optional[str] = Field(default=None, description="案发时的页面导航与层级路径", examples=["寨湾矿山/选矿看板/磨矿分级"])


class BugUpdateResultResponse(BaseModel):
    """缺陷更新操作响应模型"""
    success: bool = Field(description="更新是否成功 (True/False)", examples=[True])
    message: Optional[str] = Field(default=None, description="操作提示信息", examples=["缺陷记录更新成功"])
    error: Optional[str] = Field(default=None, description="错误详细原因 (失败时返回)")
    updated_fields: Optional[Dict[str, Any]] = Field(default=None, description="本次更新持久化的具体字段键值映射")


class PresetDeleteResponse(BaseModel):
    """预设任务模板删除响应模型"""
    code: int = Field(default=200, description="业务状态码", examples=[200])
    message: str = Field(description="操作结果描述说明", examples=["预设删除成功"])
    preset_id: str = Field(description="被删除的预设模板 ID", examples=["preset_user_20261102"])


class QueueDeleteResponse(BaseModel):
    """调度队列项移出响应模型"""
    code: int = Field(default=200, description="业务状态码", examples=[200])
    message: str = Field(description="操作结果描述说明", examples=["已从调度队列中成功移出"])
    queue_id: str = Field(description="被移出的队列项唯一标识", examples=["queue_20261111_001"])


class BugDeleteResponse(BaseModel):
    """缺陷资产删除响应模型"""
    code: int = Field(default=200, description="状态码", examples=[200])
    message: str = Field(description="删除结果提示说明", examples=["缺陷记录已成功彻底物理删除"])
    bug_id: str = Field(description="被删除的缺陷全局唯一编号", examples=["BUG-20261030-001"])
    deleted_targets: List[str] = Field(default_factory=list, description="物理清理的目标存储载体列表", examples=[["database", "global_json", "report_dir"]])


class TaskActionResponse(BaseModel):
    """巡检任务操作响应模型 (启动/终止等)"""
    code: int = Field(default=200, description="状态码 (200 为成功)", examples=[200])
    message: str = Field(description="操作结果描述说明", examples=["任务启动成功"])
    task_id: str = Field(description="操作的目标任务全局识别码", examples=["task_20261102_153022"])
    pid: Optional[int] = Field(default=None, description="启动的任务子进程物理 PID (启动成功时返回)", examples=[12348])


class TaskDeleteResponse(BaseModel):
    """巡检任务级联删除响应模型"""
    code: int = Field(default=200, description="状态码 (200 为成功)", examples=[200])
    message: str = Field(description="删除结果描述提示", examples=["任务记录已安全注销，磁盘产物与大盘已转入后台极速抹除"])
    task_id: str = Field(description="被删除的任务全局识别码", examples=["task_20261102_153022"])
    deleted_disk_path: Optional[str] = Field(default=None, description="被清理的磁盘物理运行目录相对路径")
    cleaned_bugs_count: int = Field(default=0, description="级联清理的缺陷记录总数", examples=[0])


class TaskLogsResponse(BaseModel):
    """巡检任务控制台实时运行日志响应模型"""
    task_id: str = Field(description="任务全局唯一识别码", examples=["task_20261102_153022"])
    count: int = Field(default=0, description="本次拉取的日志行数", examples=[150])
    logs: List[str] = Field(default_factory=list, description="日志文本按行切分列表", examples=[["[INFO] [ActionRunner] 正在加载自然语言用例...", "[INFO] 步骤 1 执行成功"]])


class ApiEndpointItem(BaseModel):
    """单个被测 API 接口元数据信息"""
    method: Optional[str] = Field(default="GET", description="HTTP 请求方式 (GET/POST/PUT/DELETE 等)", examples=["GET"])
    url: str = Field(description="接口完整 URL 地址或相对路径", examples=["/api/v1/production/zhaiwan/status"])
    path: Optional[str] = Field(default=None, description="接口纯路径 (不含 Query 参数)", examples=["/api/v1/production/zhaiwan/status"])
    status_code: Optional[int] = Field(default=200, description="响应 HTTP 状态码", examples=[200])
    count: int = Field(default=1, description="本次巡检中该接口被拦截触发的调用总次数", examples=[12])
    content_type: Optional[str] = Field(default=None, description="响应 Content-Type 标头", examples=["application/json;charset=UTF-8"])
    sample_query: Optional[Dict[str, Any]] = Field(default=None, description="最近一次调用的请求参数样例")
    sample_response_summary: Optional[str] = Field(default=None, description="响应体关键结构或摘要")


class TaskApisResponse(BaseModel):
    """巡检任务捕获的业务 API 接口清单模型"""
    task_id: str = Field(description="巡检任务标识码", examples=["task_20261102_153022"])
    run_dir: Optional[str] = Field(default=None, description="所属运行产物相对目录", examples=["zhaiwan/explore_20261103_183408"])
    summary: Dict[str, Any] = Field(default_factory=dict, description="接口统计摘要 (如 total_apis, unique_endpoints)")
    page_scopes: Dict[str, Any] = Field(default_factory=dict, description="按大屏业务页面划分的接口调用归属映射")
    global_flat_apis: List[Any] = Field(default_factory=list, description="本次巡检捕获的全局平铺 API 接口列表")


class TaskEnvInfoResponse(BaseModel):
    """巡检任务运行时环境基线快照模型"""
    task_id: str = Field(description="巡检任务标识码", examples=["task_20261102_153022"])
    run_dir: Optional[str] = Field(default=None, description="所属运行产物目录", examples=["zhaiwan/explore_20261103_183408"])
    exists: bool = Field(description="是否存在环境基线快照文件 env_info.json", examples=[True])
    env_info: Optional[Dict[str, Any]] = Field(default=None, description="环境基线完整结构化 JSON 数据 (包含 Launcher 版本、UE5 端口、网关配置等)")
    raw_json: Optional[str] = Field(default=None, description="格式化美化后的原始 JSON 字符串")
    message: Optional[str] = Field(default=None, description="状态补充说明")


class ZentaoSyncResponse(BaseModel):
    """禅道系统提单同步响应模型"""
    code: int = Field(default=200, description="状态码", examples=[200])
    message: str = Field(description="提示消息", examples=["禅道提交成功"])
    bug_id: str = Field(description="本地全局缺陷编号", examples=["BUG-20261030-001"])
    zentao_id: Optional[str] = Field(default=None, description="提单成功后返回的禅道 Bug 编号", examples=["1288"])
    zentao_url: Optional[str] = Field(default=None, description="禅道 Web 端缺陷详情超链接", examples=["http://zentao.example.com/index.php?m=bug&f=view&bugID=1288"])
    status: Optional[str] = Field(default="已提单", description="同步后缺陷本地更新状态", examples=["已提单"])
    assignee: Optional[str] = Field(default=None, description="提单指派责任人", examples=["陈贻雄"])


class TestCaseItem(BaseModel):
    """测试用例资产项模型"""
    id: str = Field(description="用例唯一标识 (文件名 stem)", examples=["case_zhaiwan_smoke"])
    name: str = Field(description="用例展示名称", examples=["【寨湾】全流程基础业务链路冒烟回归"])
    filename: str = Field(description="用例 YAML 物理文件名", examples=["case_zhaiwan_smoke.yaml"])
    path: str = Field(description="相对工程根目录的相对路径", examples=["test_cases/case_zhaiwan_smoke.yaml"])
    steps_count: int = Field(default=0, description="用例内包含的动作步骤总数", examples=[18])
    size_kb: float = Field(default=0.0, description="文件物理大小 (单位: KB)", examples=[4.25])
    modified_at: Optional[str] = Field(default=None, description="最后修改时间 (手工用例)", examples=["2026-11-10 14:20:00"])
    created_at: Optional[str] = Field(default=None, description="创建时间 (AI 自动生成用例)")
    app_name: Optional[str] = Field(default=None, description="归属矿山应用代号", examples=["zhaiwan"])
    run_id: Optional[str] = Field(default=None, description="生成该用例的巡检运行批次 ID")
    description: Optional[str] = Field(default="", description="用例业务目标描述")
    type: str = Field(description="用例类型: manual(手工编写) / auto(AI自动沉淀)", examples=["manual"])


class TestCaseListResponse(BaseModel):
    """全量测试用例资产列表响应模型"""
    manual_cases: List[TestCaseItem] = Field(default_factory=list, description="手工编写的常态化 YAML 用例列表")
    auto_cases: List[TestCaseItem] = Field(default_factory=list, description="AI 探索全自动逆向沉淀的回归用例列表")
    total_manual: int = Field(default=0, description="手工用例总数", examples=[6])
    total_auto: int = Field(default=0, description="AI 自动生成用例总数", examples=[12])


class TestCaseContentResponse(BaseModel):
    """用例 YAML 内容响应模型"""
    path: str = Field(description="用例相对工程根目录的路径", examples=["test_cases/case_zhaiwan_smoke.yaml"])
    filename: str = Field(description="用例文件名", examples=["case_zhaiwan_smoke.yaml"])
    content: str = Field(description="YAML 纯文本内容")


class CasePromoteRequest(BaseModel):
    """AI 自动生成用例固化转存请求模型"""
    path: str = Field(
        description="待固化的 AI 用例相对路径 (如 reports/runs/.../generated_cases/case_xxx.yaml)",
        examples=["reports/runs/zhaiwan/explore_20261103_183408/generated_cases/case_auto_1.yaml"]
    )
    target_name: Optional[str] = Field(
        default=None,
        description="固化后的新用例文件名 (如 case_zhaiwan_custom.yaml)，留空则使用源文件名",
        examples=["case_zhaiwan_replay_2026.yaml"]
    )


class CasePromoteResponse(BaseModel):
    """AI 自动生成用例固化转存响应模型"""
    code: int = Field(default=200, description="状态码", examples=[200])
    message: str = Field(description="操作说明", examples=["成功固化为常态用例: test_cases/case_zhaiwan_replay_2026.yaml"])
    dest_path: str = Field(description="固化后在 test_cases/ 下的目标相对路径", examples=["test_cases/case_zhaiwan_replay_2026.yaml"])


class MetricsCleanupResponse(BaseModel):
    """历史性能时序数据清理响应模型"""
    code: int = Field(default=200, description="状态码", examples=[200])
    message: str = Field(description="清理操作结果提示", examples=["成功清理 1200 条超过 7 天的历史性能时序数据"])
    deleted_count: int = Field(description="本次成功物理删除的过期记录总数", examples=[1200])
    retention_days: int = Field(description="配置的保留天数", examples=[7])


class AppLiveStatusItem(BaseModel):
    """单个矿山应用物理运行实时状态"""
    app_name: str = Field(description="矿山应用系统代号 (zhaiwan / tianrui / liwutong)", examples=["zhaiwan"])
    title: Optional[str] = Field(default=None, description="矿山应用友好展示名称", examples=["寨湾矿山"])
    online: bool = Field(default=False, description="应用是否在线 (UE 或 CDP 至少一个在线)", examples=[True])
    ue_pid: Optional[int] = Field(default=None, description="伴生 UE5 渲染引擎主进程 PID", examples=[9212])
    ue_memory_mb: Optional[float] = Field(default=None, description="伴生 UE5 物理常驻工作集内存占用 (MB)", examples=[1450.2])
    ue_commit_mb: Optional[float] = Field(default=None, description="伴生 UE5 专用虚拟提交量 (Private Commit, MB)", examples=[2100.5])
    ue_cpu_percent: Optional[float] = Field(default=None, description="伴生 UE5 CPU 占用百分比 (%)", examples=[12.5])
    cdp_online: bool = Field(default=False, description="Chromium CDP 调试接口是否在线连通", examples=[True])


class AmbientMetricPointResponse(BaseModel):
    """环境常驻性能时序单点快照响应模型"""
    timestamp: str = Field(description="采样时间戳 (ISO 8601)", examples=["2026-11-11T09:40:00.000Z"])
    dom_count: int = Field(default=0, description="实时 DOM 节点总数", examples=[1250])
    listeners_count: int = Field(default=0, description="实时 JS 事件监听器总数", examples=[310])
    js_heap_mb: float = Field(default=0.0, description="实时 V8 JS 堆内存 (MB)", examples=[115.4])
    js_heap_total_mb: float = Field(default=0.0, description="实时 V8 JS 堆内存总容量 (MB)", examples=[180.0])
    echarts_instances: int = Field(default=0, description="活跃 ECharts 实例数", examples=[8])
    canvas_count: int = Field(default=0, description="Canvas 数量", examples=[4])
    video_instances: int = Field(default=0, description="视频流标签数", examples=[1])
    webrtc_fps: Optional[float] = Field(default=None, description="WebRTC 实时帧率 (FPS)", examples=[59.8])
    chrome_pid: Optional[int] = Field(default=None, description="Chrome 主 PID", examples=[18340])
    chrome_cpu_percent: Optional[float] = Field(default=None, description="Chrome 进程树 CPU (%)", examples=[8.5])
    chrome_memory_mb: Optional[float] = Field(default=None, description="Chrome 进程树物理内存 (MB)", examples=[428.5])
    ue_pid: Optional[int] = Field(default=None, description="UE5 进程 PID", examples=[9212])
    ue_cpu_percent: Optional[float] = Field(default=None, description="UE5 进程归一化 CPU (%)", examples=[12.3])
    ue_memory_mb: Optional[float] = Field(default=None, description="UE5 进程物理内存 (MB)", examples=[1450.2])
    ue_commit_mb: Optional[float] = Field(default=None, description="UE5 进程专用虚拟提交量 (Commit, 单位: MB)", examples=[2100.5])
    host_ram_load_percent: Optional[float] = Field(default=None, description="整机物理内存使用率 (%)", examples=[65.4])
    host_commit_load_percent: Optional[float] = Field(default=None, description="整机虚拟内存提交率 (%)", examples=[58.2])
    host_commit_avail_gb: Optional[float] = Field(default=None, description="整机剩余可用虚拟提交量 (GB)", examples=[14.2])
    gpu_usage_percent: Optional[float] = Field(default=None, description="GPU 3D 核心占用率 (%)", examples=[35.0])
    gpu_memory_mb: Optional[float] = Field(default=None, description="GPU 显存占用 (MB)", examples=[2890.0])


class HotSyncResponse(BaseModel):
    """磁盘增量热同步执行结果模型"""
    synced: bool = Field(description="是否实际触发了增量同步", examples=[True])
    reason: Optional[str] = Field(default=None, description="未触发同步的原因 (如 throttled, up_to_date)", examples=["up_to_date"])
    new_tasks: Optional[int] = Field(default=0, description="本次增量入库的新任务数量", examples=[1])
    new_bugs: Optional[int] = Field(default=0, description="本次增量入库的新缺陷数量", examples=[0])
    elapsed: Optional[float] = Field(default=0.0, description="同步耗时秒数", examples=[0.05])
    timestamp: Optional[str] = Field(default=None, description="同步完成时间戳", examples=["2026-11-11 17:40:00"])
    message: str = Field(default="热同步完成", description="同步结果说明", examples=["热同步完成"])


class AllAppsLiveStatusResponse(BaseModel):
    """全矿山应用实时运行状态集合模型"""
    apps: List[AppLiveStatusItem] = Field(default_factory=list, description="各矿山应用实时探测状态列表")
    timestamp: str = Field(description="采样时间戳 (ISO 8601)", examples=["2026-11-11T09:40:00.000Z"])


class AmbientMetricsHistoryResponse(BaseModel):
    """历史常驻性能指标时序查询响应模型"""
    app_name: str = Field(description="矿山应用代号", examples=["zhaiwan"])
    hours: int = Field(description="查询回溯时间范围 (小时)", examples=[24])
    total_points: int = Field(description="检索到的时序样本点总数", examples=[180])
    metrics: List[AmbientMetricPointResponse] = Field(default_factory=list, description="性能指标时序明细列表")




