from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_serializer
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
        description="矿山应用系统代号 (zhaiwan: 寨湾矿山 / liwutong: 李屋塘矿山)",
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
    max_steps: int = Field(
        default=200,
        ge=5,
        le=5000,
        description="最大允许执行的动作步数上限 (Steps)，达到后自动安全收尾",
        examples=[200]
    )
    max_times: int = Field(
        default=60,
        ge=1,
        le=1440,
        description="最大运行时间限制 (单位：分钟)，超时自动安全退出",
        examples=[60]
    )
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
    pid: Optional[int] = Field(default=None, description="后台执行子进程物理 PID")
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
    occurrences: int = Field(default=1, description="AI 语义去重累计匹配到的历史复现总次数")
    first_seen: Optional[datetime.datetime] = Field(default=None, description="该缺陷首次被捕获的时间戳")
    last_seen: Optional[datetime.datetime] = Field(default=None, description="该缺陷最近一次被复现的时间戳")

    class Config:
        from_attributes = True


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
    max_steps: int = Field(default=200, ge=5, le=5000, description="最大步数")
    max_times: int = Field(default=60, ge=1, le=1440, description="最大时间 (分钟)")
    reset_memory: bool = Field(default=False, description="是否重置长期记忆")
    ignore_errors: bool = Field(default=True, description="是否容错继续")
    case_path: Optional[str] = Field(default=None, description="用例路径 (case模式生效)")
    badge: Optional[str] = Field(default="自定义", description="标签 (推荐/抗压/冒烟/回归/自定义)")
    description: Optional[str] = Field(default=None, description="简要描述说明")


class PresetTaskResponse(BaseModel):
    """预设巡检任务模板定义"""
    id: str = Field(description="预设任务唯一标识 (如 preset_zhaiwan_explore_full)")
    title: str = Field(description="预设任务标题")
    app_name: str = Field(description="目标矿山系统代号")
    mode: str = Field(description="运行模式 (explore/smoke/case/all)")
    macro_objective: str = Field(description="预设宏观意图提示词")
    max_steps: int = Field(description="推荐最大执行步数")
    max_times: int = Field(description="推荐超时时间 (分钟)")
    reset_memory: bool = Field(default=False, description="是否重置记忆")
    ignore_errors: bool = Field(default=True, description="是否忽略软错误继续")
    case_path: Optional[str] = Field(default=None, description="用例文件相对路径")
    badge: str = Field(default="推荐", description="标签 (推荐/高优/抗压/冒烟/自定义)")
    description: Optional[str] = Field(default=None, description="业务场景与测试目标简要说明")
    is_system: bool = Field(default=False, description="是否为系统只读预设")

    class Config:
        from_attributes = True


class ConfigOptionsResponse(BaseModel):
    """前端表单初始化选项字典响应模型"""
    apps: List[Dict[str, str]] = Field(description="可选矿山大屏应用清单 (key, name, desc)")
    modes: List[Dict[str, str]] = Field(description="可选运行模式清单 (key, name, desc)")
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

