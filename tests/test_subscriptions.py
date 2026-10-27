from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.drivers.daloradius import DaloRadiusDriver, freeradius_date
from tests.conftest import rows


def test_iso_dates_become_freeradius_expiration_values() -> None:
    assert freeradius_date("2026-11-26T20:59:59Z") == "26 Nov 2026 20:59:59"
    assert freeradius_date("2026-11-26T23:59:59+03:00") == "26 Nov 2026 20:59:59"


def test_home_activation_sets_device_limit_and_expiry(driver: DaloRadiusDriver, radius_engine: Engine) -> None:
    driver.activate_package("acc-10021", "t1-p9", upload_kbps=5000, download_kbps=20000, max_devices=1, expires_at="2026-11-26T20:59:59Z")

    assert rows(radius_engine, "SELECT attribute, value FROM radgroupcheck WHERE groupname = 't1-p9'") == [{"attribute": "Simultaneous-Use", "value": "1"}]
    assert rows(radius_engine, "SELECT attribute, value FROM radcheck WHERE username = 'acc-10021'") == [{"attribute": "Expiration", "value": "26 Nov 2026 20:59:59"}]


def test_renewing_replaces_the_expiry_and_changing_devices_replaces_the_limit(driver: DaloRadiusDriver, radius_engine: Engine) -> None:
    driver.activate_package("acc-1", "home", max_devices=1, expires_at="2026-11-01T00:00:00Z")
    driver.activate_package("acc-1", "home", max_devices=3, expires_at="2026-12-01T00:00:00Z")

    assert rows(radius_engine, "SELECT value FROM radcheck WHERE attribute = 'Expiration'") == [{"value": "01 Dec 2026 00:00:00"}]
    assert rows(radius_engine, "SELECT value FROM radgroupcheck") == [{"value": "3"}]


def test_hotspot_activation_without_expiry_leaves_radcheck_alone(driver: DaloRadiusDriver, radius_engine: Engine) -> None:
    driver.create_customer("254700000001", "pw")
    driver.activate_package("254700000001", "Daily", session_timeout_seconds=86400)

    assert rows(radius_engine, "SELECT attribute FROM radcheck") == [{"attribute": "Cleartext-Password"}]
    assert rows(radius_engine, "SELECT * FROM radgroupcheck") == []


def test_the_expiration_endpoint_sets_and_clears(client: TestClient, radius_engine: Engine) -> None:
    assert client.put("/api/v1/customer/acc-1/expiration", json={"expires_at": "2026-11-26T20:59:59Z"}).status_code == 200
    assert rows(radius_engine, "SELECT value FROM radcheck WHERE attribute = 'Expiration'") == [{"value": "26 Nov 2026 20:59:59"}]

    assert client.put("/api/v1/customer/acc-1/expiration", json={"expires_at": None}).status_code == 200
    assert rows(radius_engine, "SELECT * FROM radcheck WHERE attribute = 'Expiration'") == []


def test_activation_api_accepts_devices_and_expiry(client: TestClient, radius_engine: Engine) -> None:
    response = client.post("/api/v1/package/activate", json={"username": "acc-2", "package": "home", "max_devices": 2, "expires_at": "2026-11-26T20:59:59Z"})

    assert response.status_code == 200
    assert rows(radius_engine, "SELECT value FROM radgroupcheck") == [{"value": "2"}]
    assert client.post("/api/v1/package/activate", json={"username": "acc-2", "package": "home", "max_devices": 0}).status_code == 422
