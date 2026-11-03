import sys
from pathlib import Path
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
PROJECT_ROOT = Path(__file__).parent.parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest
from fastapi.testclient import TestClient
from server.main import app

client = TestClient(app)

def test_unified_platform():
    # 1. 测试控制台首页
    r1 = client.get("/")
    assert r1.status_code == 200
    print("✅ 1. 控制台首页 GET / : 200 OK")

    # 2. 测试大盘统一规范重定向
    r2 = client.get("/report-hub", follow_redirects=False)
    assert r2.status_code == 302
    assert r2.headers["location"] == "/reports/runs/index.html"
    print("✅ 2. 大盘统一跳转 GET /report-hub -> 302 /reports/runs/index.html: OK")

    # 3. 测试大盘页面加载与平台中枢回跳入口
    r3 = client.get("/reports/runs/index.html")
    assert r3.status_code == 200
    assert "Electron Vision AI" in r3.text
    assert "进入调度控制台中枢" in r3.text
    print("✅ 3. 大盘页面 GET /reports/runs/index.html : 200 OK")

    # 4. 测试单次测试运行报告
    r4 = client.get("/reports/runs/zhaiwan/explore_20261102_182417/report.html")
    assert r4.status_code == 200
    print("✅ 4. 单次报告 GET /reports/runs/zhaiwan/explore_20261102_182417/report.html : 200 OK")

    # 5. 测试截图资源加载 (相对路径天然解析，无任何多端口与根挂载黑魔法)
    r5 = client.get("/reports/runs/zhaiwan/explore_20261102_182417/screenshots/explore_step_462.png")
    assert r5.status_code == 200
    assert "image/png" in r5.headers.get("content-type", "")
    print("✅ 5. 截图资源 GET /reports/runs/zhaiwan/.../screenshots/explore_step_462.png : 200 OK")

    # 6. 测试统一缺陷更新接口
    r6 = client.post("/api/update_bug_detail", json={"bug_id": "BUG-20261030-002", "assignee": "陈贻雄"})
    assert r6.status_code == 200
    res_json = r6.json()
    assert res_json["success"] is True
    print(f"✅ 6. 统一缺陷接口 POST /api/update_bug_detail : 200 OK, updated: {res_json.get('updated')}")

if __name__ == "__main__":
    test_unified_platform()
