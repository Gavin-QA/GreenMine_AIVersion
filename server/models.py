import datetime
from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    Boolean,
    Text,
    DateTime,
    ForeignKey
)
from sqlalchemy.orm import relationship
from .database import Base


class TaskRun(Base):
    """巡检任务模型表"""
    __tablename__ = "task_runs"

    id = Column(String(64), primary_key=True, index=True) # 格式如 task_20261102_153022
    name = Column(String(128), default="自动化探索巡检任务")
    app_name = Column(String(64), default="zhaiwan", index=True) # 矿山应用代号
    mode = Column(String(32), default="explore", index=True) # explore, case, smoke, all
    status = Column(String(32), default="pending", index=True) # pending, running, completed, stopped, failed
    
    # 探索/回放核心配置
    macro_objective = Column(Text, nullable=True)
    max_steps = Column(Integer, default=200)
    max_times = Column(Integer, default=60) # 分钟
    reset_memory = Column(Boolean, default=False)
    ignore_errors = Column(Boolean, default=True)
    explore_context = Column(String(256), default="docs/explore_rules_zhaiwan.md")
    case_path = Column(String(256), nullable=True)
    
    # 运行物理环境与进程
    pid = Column(Integer, nullable=True)
    run_dir = Column(String(256), nullable=True) # 如 reports/runs/zhaiwan/explore_xxx
    report_url = Column(String(256), nullable=True)
    exit_code = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)
    
    # 统计汇总指标
    start_time = Column(DateTime, default=datetime.datetime.utcnow)
    end_time = Column(DateTime, nullable=True)
    duration = Column(String(64), nullable=True)
    total_steps = Column(Integer, default=0)
    planner_phases = Column(Integer, default=0)
    coverage_rate = Column(Float, default=0.0)
    bugs_count = Column(Integer, default=0)
    apis_count = Column(Integer, default=0)
    yaml_steps_count = Column(Integer, default=0)

    # 级联关系
    steps = relationship("StepRecord", back_populates="task", cascade="all, delete-orphan")
    bugs = relationship("BugRecord", back_populates="task")
    metrics = relationship("PerformanceMetric", back_populates="task", cascade="all, delete-orphan")


class StepRecord(Base):
    """步骤执行历史记录表"""
    __tablename__ = "step_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(64), ForeignKey("task_runs.id"), index=True)
    step_number = Column(Integer, index=True)
    step_type = Column(String(32), default="worker") # planner 或 worker
    action_type = Column(String(32), default="click")
    target_element = Column(String(256), nullable=True)
    ui_path = Column(String(256), nullable=True)
    thought = Column(Text, nullable=True)
    status = Column(String(32), default="success") # success, failed, skipped
    screenshot_path = Column(String(256), nullable=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)

    task = relationship("TaskRun", back_populates="steps")


class BugRecord(Base):
    """全局/任务缺陷归档表"""
    __tablename__ = "bug_records"

    id = Column(String(64), primary_key=True, index=True) # 如 BUG-20261030-002
    task_id = Column(String(64), ForeignKey("task_runs.id"), nullable=True, index=True)
    run_id = Column(String(64), nullable=True, index=True) # 如 explore_20261103_183408
    title = Column(String(256), index=True)
    severity = Column(String(32), default="Medium", index=True) # High, Medium, Low
    status = Column(String(32), default="激活", index=True) # 激活, 已提单, 误报, 已关闭
    assignee = Column(String(64), default="陈贻雄", index=True)
    zentao_id = Column(String(32), nullable=True, index=True)
    ui_path = Column(String(256), nullable=True)
    target_element = Column(String(256), nullable=True)
    actual_error = Column(Text, nullable=True)
    analysis_notes = Column(Text, nullable=True)
    remark = Column(Text, nullable=True) # 人工复核备注或关闭原因说明 (非必填)
    screenshot_path = Column(String(256), nullable=True)
    occurrences = Column(Integer, default=1)
    first_seen = Column(DateTime, default=datetime.datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.datetime.utcnow)

    task = relationship("TaskRun", back_populates="bugs")


class PerformanceMetric(Base):
    """全景性能时序监控数据表 (Chrome/Electron + DOM/WebRTC + UE5 伴生双核 + GPU)"""
    __tablename__ = "performance_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(64), ForeignKey("task_runs.id"), index=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    step_number = Column(Integer, nullable=True)
    page_scope = Column(String(256), nullable=True)
    
    # Chrome / Electron 渲染、DOM、事件监听器与 WebRTC 像素流指标
    dom_count = Column(Integer, default=0)
    listeners_count = Column(Integer, default=0)
    js_heap_mb = Column(Float, default=0.0)
    js_heap_total_mb = Column(Float, default=0.0)
    echarts_instances = Column(Integer, default=0)
    canvas_count = Column(Integer, default=0)
    video_instances = Column(Integer, default=0)
    webrtc_fps = Column(Float, nullable=True)
    
    # Electron / Chromium 进程树系统资源占用
    chrome_pid = Column(Integer, nullable=True)
    chrome_cpu_percent = Column(Float, nullable=True)
    chrome_memory_mb = Column(Float, nullable=True)
    
    # 伴生 UE5 引擎进程树监控指标
    ue_pid = Column(Integer, nullable=True)
    ue_cpu_percent = Column(Float, nullable=True)
    ue_memory_mb = Column(Float, nullable=True)
    ue_commit_mb = Column(Float, nullable=True)  # 专用虚拟提交量 (Private Bytes / Commit)

    # 宿主机整机内存与虚拟提交水位
    host_ram_load_percent = Column(Float, nullable=True)
    host_commit_load_percent = Column(Float, nullable=True)
    
    # 显卡 3D 渲染与 VRAM 显存指标
    gpu_usage_percent = Column(Float, nullable=True)
    gpu_memory_mb = Column(Float, nullable=True)

    task = relationship("TaskRun", back_populates="metrics")


class AmbientMetric(Base):
    """
    环境常驻实时时序性能表 (专门记录未拉起正式任务时后台常驻运行的应用心电图)
    - 独立隔离存储，与正式测试任务数据完全解耦；
    - 滚动保留最近 24 小时数据，过期自动清理；
    - 正式测试任务 (14小时+全量探索或回归压测) 永久保留在 performance_metrics 中绝对不清理。
    """
    __tablename__ = "ambient_metrics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    app_name = Column(String(64), nullable=False, index=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, index=True)
    page_scope = Column(String(256), nullable=True)

    # Chromium / DOM / 事件监听器 / V8 JS 堆内存 / WebRTC FPS
    dom_count = Column(Integer, default=0)
    listeners_count = Column(Integer, default=0)
    js_heap_mb = Column(Float, default=0.0)
    js_heap_total_mb = Column(Float, default=0.0)
    echarts_instances = Column(Integer, default=0)
    canvas_count = Column(Integer, default=0)
    video_instances = Column(Integer, default=0)
    webrtc_fps = Column(Float, nullable=True)

    # Electron / Chromium 渲染端
    chrome_pid = Column(Integer, nullable=True)
    chrome_cpu_percent = Column(Float, nullable=True)
    chrome_memory_mb = Column(Float, nullable=True)

    # 伴生 UE5 引擎 (Working Set 物理内存 + 专用提交量 Commit)
    ue_pid = Column(Integer, nullable=True)
    ue_cpu_percent = Column(Float, nullable=True)
    ue_memory_mb = Column(Float, nullable=True)
    ue_commit_mb = Column(Float, nullable=True)

    # 宿主机整体内存与提交水位
    host_ram_load_percent = Column(Float, nullable=True)
    host_commit_load_percent = Column(Float, nullable=True)
    host_commit_avail_gb = Column(Float, nullable=True)

    # 显卡 3D 与 VRAM
    gpu_usage_percent = Column(Float, nullable=True)
    gpu_memory_mb = Column(Float, nullable=True)


class PresetTaskRecord(Base):
    """预设巡检任务模板持久化表 (支持在前端增删改查并保存用户自定义预设)"""
    __tablename__ = "preset_task_records"

    id = Column(String(64), primary_key=True, index=True) # 如 preset_zhaiwan_explore_full 或 user_preset_xxx
    title = Column(String(128), nullable=False)
    app_name = Column(String(64), default="zhaiwan", index=True)
    mode = Column(String(32), default="explore", index=True)
    badge = Column(String(32), default="自定义") # 推荐 / 抗压 / 冒烟 / 回归 / 自定义
    description = Column(String(256), nullable=True)
    macro_objective = Column(Text, nullable=False)
    max_steps = Column(Integer, default=200)
    max_times = Column(Integer, default=60)
    reset_memory = Column(Boolean, default=False)
    ignore_errors = Column(Boolean, default=True)
    case_path = Column(String(256), nullable=True)
    is_system = Column(Boolean, default=False) # 系统默认预设 vs 用户自定义预设
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

