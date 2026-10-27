from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.core import settings
from app.drivers.daloradius import DaloRadiusDriver
from tests.conftest import rows


def group_attributes(engine: Engine, group: str) -> dict[str, str]:
    return {row["attribute"]: row["value"] for row in rows(engine, "SELECT attribute, value FROM radgroupreply WHERE groupname = :g", g=group)}


def test_activation_writes_attributes_for_every_vendor_in_the_fleet(driver: DaloRadiusDriver, radius_engine: Engine) -> None:
    driver.activate_package("254700000001", "t1-p3", session_timeout_seconds=86400, upload_kbps=2000, download_kbps=10000, vendors=["mikrotik", "ubiquiti"])

    attributes = group_attributes(radius_engine, "t1-p3")
    assert attributes["Mikrotik-Rate-Limit"] == "2000k/10000k"
    assert attributes["WISPr-Bandwidth-Max-Down"] == "10000000"
    assert rows(radius_engine, "SELECT groupname FROM radusergroup") == [{"groupname": "t1-p3"}]


def test_reactivating_rewrites_changed_limits_instead_of_keeping_the_first(driver: DaloRadiusDriver, radius_engine: Engine) -> None:
    driver.activate_package("254700000001", "Daily", session_timeout_seconds=86400, rate_limit="2M/5M")
    driver.activate_package("254700000002", "Daily", session_timeout_seconds=43200, rate_limit="4M/10M")

    attributes = group_attributes(radius_engine, "Daily")
    assert attributes == {"Session-Timeout": "43200", "Mikrotik-Rate-Limit": "4000k/10000k"}


def test_hand_added_attributes_survive_a_resync(driver: DaloRadiusDriver, radius_engine: Engine) -> None:
    with radius_engine.begin() as conn:
        conn.execute(text("INSERT INTO radgroupreply (groupname, attribute, op, value) VALUES ('Daily', 'Port-Limit', ':=', '1')"))

    driver.sync_package("Daily", [("Session-Timeout", "3600")])

    assert group_attributes(radius_engine, "Daily") == {"Port-Limit": "1", "Session-Timeout": "3600"}


def test_activation_moves_the_user_out_of_their_old_package_but_keeps_a_suspension(driver: DaloRadiusDriver, radius_engine: Engine) -> None:
    driver.activate_package("254700000001", "Daily", session_timeout_seconds=86400)
    driver.deactivate_package("254700000001")
    driver.activate_package("254700000001", "Weekly", session_timeout_seconds=604800)

    groups = sorted(row["groupname"] for row in rows(radius_engine, "SELECT groupname FROM radusergroup"))
    assert groups == ["Weekly", "daloRADIUS-Disabled-Users"]


def test_the_api_activates_with_vendors_and_returns_the_attributes(client: TestClient, radius_engine: Engine) -> None:
    response = client.post("/api/v1/package/activate", json={"username": "254700000001", "package": "t1-p3", "upload_kbps": 1000, "download_kbps": 5000, "data_limit_bytes": 1073741824, "vendors": ["huawei"]})

    assert response.status_code == 200
    assert ["Huawei-Remanent-Volume", "1048576"] in response.json()["attributes"]


def test_unknown_vendors_are_a_422_not_a_500(client: TestClient) -> None:
    response = client.post("/api/v1/package/activate", json={"username": "u", "package": "p", "vendors": ["juniper"]})

    assert response.status_code == 422
    assert "juniper" in response.json()["detail"]


def test_package_sync_and_preview(client: TestClient, radius_engine: Engine) -> None:
    preview = client.post("/api/v1/package/preview", json={"session_timeout_seconds": 3600, "upload_kbps": 1000, "download_kbps": 2000, "vendors": ["mikrotik", "tplink_omada"]})
    assert preview.status_code == 200
    assert ["WISPr-Bandwidth-Max-Up", "1000000"] in preview.json()["by_vendor"]["tplink_omada"]
    assert group_attributes(radius_engine, "p") == {}

    synced = client.post("/api/v1/package/sync", json={"package": "p", "session_timeout_seconds": 3600})
    assert synced.status_code == 200
    assert group_attributes(radius_engine, "p") == {"Session-Timeout": "3600"}


def test_vendor_catalogue_lists_capabilities(client: TestClient) -> None:
    vendors = {vendor["key"]: vendor for vendor in client.get("/api/v1/vendors").json()}

    assert vendors["mikrotik"]["supports_quota"] is True
    assert vendors["ubiquiti"]["family"] == "wispr"
    assert vendors["aruba"]["supports_rate"] is False


def test_nas_type_is_translated_from_a_vendor_key(client: TestClient, radius_engine: Engine) -> None:
    assert client.post("/api/v1/nas", json={"nasname": "10.200.0.10", "type": "huawei", "secret": "s"}).status_code == 200

    assert rows(radius_engine, "SELECT type FROM nas") == [{"type": "other"}]


def test_api_key_is_enforced_when_required(client: TestClient, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(settings, "require_api_key", True)
    monkeypatch.setattr(settings, "api_key", "test-key")

    assert client.get("/api/v1/vendors").status_code == 200
    assert client.get("/api/v1/vendors", headers={"X-API-KEY": "wrong"}).status_code == 401
    assert client.get("/api/v1/health", headers={"X-API-KEY": ""}).status_code == 200
