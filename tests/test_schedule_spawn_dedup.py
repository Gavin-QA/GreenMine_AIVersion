import datetime
import sys
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from server.database import Base, get_db
from server.models import PresetTaskRecord, SchedulePlan, TaskQueueItem, TaskRun
from server.routers.queue import router as queue_router
from server.schedule_service import DuplicatePlanTaskError, spawn_task_from_plan


@pytest.fixture()
def db_setup(tmp_path):
    """创建隔离的临时 SQLite 测试库，避免污染生产库 data/vision_platform.db。"""
    db_file = tmp_path / "test_schedule.db"
    engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    test_app = FastAPI()
    test_app.include_router(queue_router)
    test_app.dependency_overrides[get_db] = override_get_db

    yield TestingSessionLocal, TestClient(test_app)

    engine.dispose()


def _seed_preset_and_plan(
    db,
    plan_id: str = "plan_test_001",
    preset_id: str = "preset_test_001",
    cron_mode: str = "daily",
    cron_spec: str = "1",
    next_run_time: datetime.datetime | None = None,
) -> SchedulePlan:
    preset = db.query(PresetTaskRecord).filter(PresetTaskRecord.id == preset_id).first()
    if not preset:
        preset = PresetTaskRecord(
            id=preset_id,
            app_name="zhaiwan",
            title="测试预设模板",
            mode="explore",
            macro_objective="测试巡检目标",
            max_steps=50,
            max_times=10,
        )
        db.add(preset)

    plan = SchedulePlan(
        id=plan_id,
        name=f"计划_{plan_id}",
        app_name="zhaiwan",
        preset_id=preset_id,
        priority=2,
        start_date="2026-01-01",
        end_date="2099-12-31",
        start_time="18:35:00",
        end_time="23:59:59",
        cron_mode=cron_mode,
        cron_spec=cron_spec,
        conflict_policy="wait",
        is_active=1,
        status="active",
        run_count=0,
        next_run_time=next_run_time or datetime.datetime(2026, 11, 21, 18, 35, 0),
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


def test_manual_run_normal_preserves_schedule_state(db_setup):
    """场景 1：手动执行正常任务 -> 正常执行，不消耗定时次数，不修改 next_run_time"""
    SessionLocal, client = db_setup
    original_next = datetime.datetime(2026, 11, 21, 18, 35, 0)
    with SessionLocal() as db:
        plan = _seed_preset_and_plan(db, next_run_time=original_next)

    resp = client.post(f"/api/tasks/queue/schedule/{plan.id}/run_now")
    assert resp.status_code == 200
    task_id = resp.json()["task_id"]

    with SessionLocal() as db:
        task = db.query(TaskRun).filter(TaskRun.id == task_id).first()
        q_item = db.query(TaskQueueItem).filter(TaskQueueItem.task_id == task_id).first()
        refreshed_plan = db.query(SchedulePlan).filter(SchedulePlan.id == plan.id).first()

        assert task is not None
        assert task.trigger_type == "manual"
        assert q_item is not None
        assert q_item.id.startswith(f"queue_{plan.id}_")
        assert q_item.status == "pending"

        assert refreshed_plan.run_count == 0
        assert refreshed_plan.next_run_time == original_next
        assert refreshed_plan.last_task_id is None
        assert refreshed_plan.status == "active"


def test_manual_run_once_plan_keeps_active(db_setup):
    """场景 2：手动执行单次计划 -> 执行后计划仍保持原状态"""
    SessionLocal, client = db_setup
    original_next = datetime.datetime(2026, 11, 21, 18, 35, 0)
    with SessionLocal() as db:
        plan = _seed_preset_and_plan(db, plan_id="plan_once_001", cron_mode="once", next_run_time=original_next)

    resp = client.post(f"/api/tasks/queue/schedule/{plan.id}/run_now")
    assert resp.status_code == 200

    with SessionLocal() as db:
        refreshed_plan = db.query(SchedulePlan).filter(SchedulePlan.id == plan.id).first()
        assert refreshed_plan.is_active == 1
        assert refreshed_plan.status == "active"
        assert refreshed_plan.run_count == 0
        assert refreshed_plan.next_run_time == original_next


def test_manual_run_failure_does_not_affect_schedule(db_setup):
    """场景 3：手动执行失败 -> 不影响定时调度状态"""
    SessionLocal, client = db_setup
    original_next = datetime.datetime(2026, 11, 21, 18, 35, 0)
    with SessionLocal() as db:
        plan = _seed_preset_and_plan(db, plan_id="plan_fail_001", next_run_time=original_next)

    resp = client.post(f"/api/tasks/queue/schedule/{plan.id}/run_now")
    assert resp.status_code == 200
    task_id = resp.json()["task_id"]

    # 模拟该手动任务最终执行失败
    with SessionLocal() as db:
        task = db.query(TaskRun).filter(TaskRun.id == task_id).first()
        q_item = db.query(TaskQueueItem).filter(TaskQueueItem.task_id == task_id).first()
        task.status = "failed"
        q_item.status = "failed"
        db.commit()

        refreshed_plan = db.query(SchedulePlan).filter(SchedulePlan.id == plan.id).first()
        assert refreshed_plan.is_active == 1
        assert refreshed_plan.status == "active"
        assert refreshed_plan.run_count == 0
        assert refreshed_plan.next_run_time == original_next


def test_scheduled_run_increments_count_and_updates_next_time(db_setup):
    """场景 4：定时任务正常触发 -> 次数 +1，推演下次执行时间（单次自动完结）"""
    SessionLocal, _ = db_setup
    past_next = datetime.datetime.now() - datetime.timedelta(minutes=5)
    with SessionLocal() as db:
        daily_plan = _seed_preset_and_plan(db, plan_id="plan_sched_daily", cron_mode="daily", next_run_time=past_next)
        task_daily = spawn_task_from_plan(daily_plan, db, trigger_type="scheduled")
        assert task_daily is not None
        assert task_daily.trigger_type == "scheduled"
        assert daily_plan.run_count == 1
        assert daily_plan.last_task_id == task_daily.id
        assert daily_plan.next_run_time is not None
        assert daily_plan.next_run_time > past_next

        once_plan = _seed_preset_and_plan(db, plan_id="plan_sched_once", cron_mode="once", next_run_time=past_next)
        task_once = spawn_task_from_plan(once_plan, db, trigger_type="scheduled")
        assert task_once is not None
        assert task_once.trigger_type == "scheduled"
        assert once_plan.run_count == 1
        assert once_plan.is_active == 0
        assert once_plan.status == "completed"
        assert once_plan.next_run_time is None


def test_manual_then_scheduled_after_completion(db_setup):
    """场景 5：手动执行后等待定时触发 -> 手动任务完成后定时触发仍按原计划执行"""
    SessionLocal, client = db_setup
    original_next = datetime.datetime.now() - datetime.timedelta(seconds=1)
    with SessionLocal() as db:
        plan = _seed_preset_and_plan(db, plan_id="plan_m_then_s", next_run_time=original_next)

    resp = client.post(f"/api/tasks/queue/schedule/{plan.id}/run_now")
    assert resp.status_code == 200
    manual_task_id = resp.json()["task_id"]

    # 模拟手动任务执行完成
    with SessionLocal() as db:
        q_item = db.query(TaskQueueItem).filter(TaskQueueItem.task_id == manual_task_id).first()
        task = db.query(TaskRun).filter(TaskRun.id == manual_task_id).first()
        q_item.status = "completed"
        task.status = "completed"
        db.commit()

        refreshed_plan = db.query(SchedulePlan).filter(SchedulePlan.id == plan.id).first()
        assert refreshed_plan.next_run_time == original_next

        sched_task = spawn_task_from_plan(refreshed_plan, db, trigger_type="scheduled")
        assert sched_task is not None
        assert sched_task.id != manual_task_id
        assert sched_task.trigger_type == "scheduled"
        assert refreshed_plan.run_count == 1


def test_dedup_blocks_same_plan_but_allows_different_plans_same_preset(db_setup):
    """场景 6：队列已有同计划 pending/running 任务时阻止重复入队；不同计划同模板互不限制"""
    SessionLocal, client = db_setup
    with SessionLocal() as db:
        _seed_preset_and_plan(db, plan_id="plan_a", preset_id="shared_preset")
        _seed_preset_and_plan(db, plan_id="plan_b", preset_id="shared_preset")

    # 计划 A 第一次手动触发成功 (pending)
    r1 = client.post("/api/tasks/queue/schedule/plan_a/run_now")
    assert r1.status_code == 200

    # 计划 A 在 pending 态再次手动触发被阻止
    r2 = client.post("/api/tasks/queue/schedule/plan_a/run_now")
    assert r2.status_code == 409
    assert "该任务已在队列中或正在执行" in r2.json()["detail"]

    # 切换为 running 态依然被阻止
    with SessionLocal() as db:
        q_a = db.query(TaskQueueItem).filter(TaskQueueItem.task_id == r1.json()["task_id"]).first()
        q_a.status = "running"
        db.commit()

    r3 = client.post("/api/tasks/queue/schedule/plan_a/run_now")
    assert r3.status_code == 409

    # 计划 B 虽然共用同一 preset_id，但不受计划 A 限制，可正常入队
    r_b = client.post("/api/tasks/queue/schedule/plan_b/run_now")
    assert r_b.status_code == 200


def test_concurrent_manual_and_scheduled_only_enqueue_once(db_setup):
    """场景 7：手动执行与定时触发同时发生 -> 原子操作保证只能成功入队一次"""
    SessionLocal, _ = db_setup
    with SessionLocal() as db:
        plan = _seed_preset_and_plan(db, plan_id="plan_race_001")

    barrier = threading.Barrier(2)
    results = []
    errors = []

    def worker(trigger_type: str):
        with SessionLocal() as db:
            p = db.query(SchedulePlan).filter(SchedulePlan.id == "plan_race_001").first()
            barrier.wait()
            try:
                task = spawn_task_from_plan(p, db, trigger_type=trigger_type)
                results.append((trigger_type, task.id if task else None))
            except DuplicatePlanTaskError as exc:
                errors.append((trigger_type, str(exc)))

    t1 = threading.Thread(target=worker, args=("manual",))
    t2 = threading.Thread(target=worker, args=("scheduled",))
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert len(results) == 1
    assert len(errors) == 1
    assert "该任务已在队列中或正在执行" in errors[0][1]

    with SessionLocal() as db:
        q_items = db.query(TaskQueueItem).filter(TaskQueueItem.id.like("queue_plan_race_001_%")).all()
        assert len(q_items) == 1


def test_scheduled_run_failure_follows_original_policy(db_setup):
    """场景 8：定时任务下发/执行失败 -> 按原有失败处理规则执行"""
    SessionLocal, _ = db_setup
    with SessionLocal() as db:
        plan = _seed_preset_and_plan(db, plan_id="plan_sched_fail", cron_mode="once")
        # 模拟关联预设不存在导致定时下发失败（返回 None，不创建 TaskRun，不误标 completed）
        plan.preset_id = "missing_preset"
        db.commit()

        result = spawn_task_from_plan(plan, db, trigger_type="scheduled")
        assert result is None
        assert plan.run_count == 0
        assert plan.status == "active"
