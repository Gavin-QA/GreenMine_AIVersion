from datetime import datetime, timedelta
from fastapi.testclient import TestClient

from server.main import app
from utils.zentao_sync import pick_default_opened_builds


def test_pick_default_opened_builds_picks_latest_web_and_ue():
    builds = [
        {"id": 150, "name": "bigScreen-web-zhaiwan-20261023-build001", "product": 11},
        {"id": 169, "name": "bigScreen-web-zhaiwan-20261116-build001", "product": 11},
        {"id": 148, "name": "bigScreen-ue-zhaiwan-20261021-build001", "product": 11},
        {"id": 168, "name": "bigScreen-ue-zhaiwan-20261116-build001", "product": 11},
        {"id": 170, "name": "other-product-web-20261116", "product": 8},
    ]
    picked = pick_default_opened_builds(builds, product_id=11)
    assert picked == ["169", "168"]


def test_pick_default_opened_builds_fallback_and_trunk():
    assert pick_default_opened_builds([], product_id=11) == ["trunk"]
    builds = [
        {"id": 151, "name": "bigScreen-web-liwutong-20261023-build001", "product": 36},
        {"id": 141, "name": "App_android_20260928_build001", "product": 36},
    ]
    picked = pick_default_opened_builds(builds, product_id=11)
    assert picked == ["151", "141"]


def test_zentao_metadata_and_preview_endpoints():
    client = TestClient(app)

    meta_res = client.get("/api/zentao/metadata?project_id=26&product_id=11")
    assert meta_res.status_code == 200
    meta = meta_res.json()
    assert len(meta["executions"]) >= 1
    assert any(m["id"] == 0 and m["name"] == "/" for m in meta["modules"])
    assert len(meta["builds"]) >= 2
    assert len(meta["recommended_builds"]) == 2

    bugs_res = client.get("/api/bugs?limit=5")
    assert bugs_res.status_code == 200
    bugs = bugs_res.json().get("bugs", [])
    if bugs:
        bug_id = bugs[0]["id"]
        preview_res = client.get(f"/api/bugs/{bug_id}/zentao_preview")
        assert preview_res.status_code == 200
        preview = preview_res.json()
        defaults = preview["defaults"]
        expected_deadline = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
        assert defaults["bug_id"] == bug_id
        assert defaults["type"] == "codeerror"
        assert defaults["status_label"] == "激活"
        assert defaults["module_id"] == 0
        assert defaults["deadline"] == expected_deadline
        assert len(defaults["opened_build"]) >= 1
        assert len(preview["options"]["users"]) >= 1
        assert len(preview["options"]["products"]) >= 1
        assert len(preview["options"]["projects"]) >= 1

