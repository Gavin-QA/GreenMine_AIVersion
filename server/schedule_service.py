import datetime
import calendar
import logging
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy.orm import Session

from .models import SchedulePlan, TaskQueueItem, TaskRun, PresetTaskRecord

logger = logging.getLogger("server.schedule")


def parse_time_parts(time_str: str, default_h: int = 18, default_m: int = 35, default_s: int = 0) -> Tuple[int, int, int]:
    """解析 HH:mm:ss 格式的时间字符串"""
    if not time_str:
        return default_h, default_m, default_s
    parts = time_str.strip().split(":")
    try:
        h = int(parts[0]) if len(parts) >= 1 else default_h
        m = int(parts[1]) if len(parts) >= 2 else default_m
        s = int(parts[2]) if len(parts) >= 3 else default_s
        return max(0, min(23, h)), max(0, min(59, m)), max(0, min(59, s))
    except Exception:
        return default_h, default_m, default_s


def calculate_next_run_time(
    cron_mode: str,
    cron_spec: str,
    start_time_str: str,
    start_date_str: Optional[str] = None,
    end_date_str: Optional[str] = None,
    after_time: Optional[datetime.datetime] = None,
) -> Optional[datetime.datetime]:
    """
    计算调度计划的下一次执行时刻 (本地时间)
    返回: 下一次触发的 datetime 对象；若已到期或无法排期则返回 None
    """
    now = after_time or datetime.datetime.now()
    h, m, s = parse_time_parts(start_time_str)

    clean_start_date = (start_date_str or "").strip()
    clean_end_date = (end_date_str or "").strip()

    # 1. 单次执行模式 (once)
    if cron_mode == "once":
        base_date_str = clean_start_date if clean_start_date else now.strftime("%Y-%m-%d")
        try:
            target = datetime.datetime.strptime(f"{base_date_str} {h:02d}:{m:02d}:{s:02d}", "%Y-%m-%d %H:%M:%S")
        except Exception:
            return None
        if target > now:
            if clean_end_date and target.strftime("%Y-%m-%d") > clean_end_date:
                return None
            return target
        return None

    # 2. 分钟级高频模式 (minute)
    elif cron_mode == "minute":
        interval = int(cron_spec) if (cron_spec and cron_spec.isdigit()) else 30
        interval = max(1, interval)
        candidate = now + datetime.timedelta(minutes=interval)
        if clean_end_date and candidate.strftime("%Y-%m-%d") > clean_end_date:
            return None
        return candidate

    # 3. 小时级模式 (hour)
    elif cron_mode == "hour":
        interval = int(cron_spec) if (cron_spec and cron_spec.isdigit()) else 1
        interval = max(1, interval)
        candidate = now + datetime.timedelta(hours=interval)
        if clean_end_date and candidate.strftime("%Y-%m-%d") > clean_end_date:
            return None
        return candidate

    # 4. 按天循环模式 (daily)
    elif cron_mode == "daily":
        interval = int(cron_spec) if (cron_spec and cron_spec.isdigit()) else 1
        interval = max(1, interval)

        # 确定起始基准日期
        base_date_str = clean_start_date if clean_start_date else now.strftime("%Y-%m-%d")
        try:
            base_date = datetime.datetime.strptime(base_date_str, "%Y-%m-%d").date()
        except Exception:
            base_date = now.date()

        # 如果计划的起始日期在今天之后，直接从起始日期的 start_time 开始
        if base_date > now.date():
            candidate = datetime.datetime(base_date.year, base_date.month, base_date.day, h, m, s)
        else:
            # 起始日期就是今天或过去：先看今天的 start_time 是否还没到
            candidate = datetime.datetime(now.year, now.month, now.day, h, m, s)
            while candidate <= now:
                candidate += datetime.timedelta(days=interval)

        if clean_end_date and candidate.strftime("%Y-%m-%d") > clean_end_date:
            return None
        return candidate

    # 5. 每周指定星期几模式 (weekly)
    elif cron_mode == "weekly":
        raw_days = [int(x.strip()) for x in (cron_spec or "1").split(",") if x.strip().isdigit()]
        valid_days = [d for d in raw_days if 1 <= d <= 7]
        if not valid_days:
            valid_days = [1]

        base_date = now.date()
        if clean_start_date:
            try:
                sd = datetime.datetime.strptime(clean_start_date, "%Y-%m-%d").date()
                if sd > base_date:
                    base_date = sd
            except Exception:
                pass

        # 向上寻找未来 14 天内匹配的星期
        for offset in range(0, 15):
            test_date = base_date + datetime.timedelta(days=offset)
            cand = datetime.datetime(test_date.year, test_date.month, test_date.day, h, m, s)
            if cand.isoweekday() in valid_days and cand > now:
                if clean_end_date and cand.strftime("%Y-%m-%d") > clean_end_date:
                    return None
                return cand
        return None

    # 6. 每月固定几号模式 (monthly)
    elif cron_mode == "monthly":
        day_num = int(cron_spec) if (cron_spec and cron_spec.isdigit()) else 1
        day_num = max(1, min(31, day_num))

        year = now.year
        month = now.month
        max_d = calendar.monthrange(year, month)[1]
        cand = datetime.datetime(year, month, min(day_num, max_d), h, m, s)

        if cand <= now:
            month += 1
            if month > 12:
                year += 1
                month = 1
            max_d = calendar.monthrange(year, month)[1]
            cand = datetime.datetime(year, month, min(day_num, max_d), h, m, s)

        if clean_start_date:
            try:
                sd = datetime.datetime.strptime(clean_start_date, "%Y-%m-%d")
                while cand < sd:
                    month += 1
                    if month > 12:
                        year += 1
                        month = 1
                    max_d = calendar.monthrange(year, month)[1]
                    cand = datetime.datetime(year, month, min(day_num, max_d), h, m, s)
            except Exception:
                pass

        if clean_end_date and cand.strftime("%Y-%m-%d") > clean_end_date:
            return None
        return cand

    return None


def spawn_task_from_plan(plan: SchedulePlan, db: Session) -> Optional[TaskRun]:
    """根据调度计划常驻规则实例化生成一次真实的巡检任务并送入执行队列"""
    import uuid

    preset = db.query(PresetTaskRecord).filter(PresetTaskRecord.id == plan.preset_id).first()
    if not preset:
        logger.error(f"❌ 调度计划 [{plan.id}] 关联的预设模板 [{plan.preset_id}] 不存在，跳过下发！")
        return None

    now = datetime.datetime.now()
    new_task_id = f"task_{now.strftime('%Y%m%d_%H%M%S')}"

    # 拷贝预设配置参数
    new_task = TaskRun(
        id=new_task_id,
        name=plan.name,
        app_name=plan.app_name,
        mode=preset.mode,
        status="pending",
        macro_objective=preset.macro_objective,
        max_steps=preset.max_steps,
        max_times=preset.max_times,
        reset_memory=preset.reset_memory,
        ignore_errors=preset.ignore_errors,
        case_path=preset.case_path,
        tour=preset.tour,
        resume_from=preset.resume_from,
        reexplore=preset.reexplore,
        start_delay=preset.start_delay,
        wait_ready=preset.wait_ready,
        wait_timeout=preset.wait_timeout,
        ignore_env_check=bool(plan.ignore_env_check or getattr(preset, "ignore_env_check", False)),
        explore_context=getattr(preset, "explore_context", None) or getattr(plan, "explore_context", None) or f"docs/explore_rules_{plan.app_name}.md",
        trigger_type="scheduled",
        start_time=now,
    )
    db.add(new_task)
    db.flush()

    # 注入单机独占 RPA 排队队列
    queue_id = f"queue_{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
    q_item = TaskQueueItem(
        id=queue_id,
        task_id=new_task.id,
        priority=plan.priority,
        status="pending",
        scheduled_at=None, # 已到点，立即排队进入就绪态
        cron_mode=plan.cron_mode,
        cron_spec=plan.cron_spec,
        time_of_day=plan.start_time,
        is_active=1,
        created_at=now,
    )
    db.add(q_item)

    # 回填调度计划统计状态
    plan.last_run_time = now
    plan.last_task_id = new_task.id
    plan.run_count = (plan.run_count or 0) + 1

    # 推演下一次执行时刻
    if plan.cron_mode == "once":
        plan.is_active = 0
        plan.status = "completed"
        plan.next_run_time = None
        logger.info(f"✅ 单次调度计划 [{plan.name}] 已成功下发任务 [{new_task.id}]，计划自动归档完成。")
    else:
        next_dt = calculate_next_run_time(
            cron_mode=plan.cron_mode,
            cron_spec=plan.cron_spec,
            start_time_str=plan.start_time,
            start_date_str=plan.start_date,
            end_date_str=plan.end_date,
            after_time=now,
        )
        if next_dt:
            plan.next_run_time = next_dt
            plan.status = "active"
            logger.info(f"🔄 周期调度计划 [{plan.name}] 已成功下发任务 [{new_task.id}]，下次执行时间已预约至: {next_dt.strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            plan.is_active = 0
            plan.status = "expired"
            plan.next_run_time = None
            logger.info(f"🏁 周期调度计划 [{plan.name}] 已到达结束日期，自动标记为已到期 (expired)。")

    db.commit()
    return new_task

