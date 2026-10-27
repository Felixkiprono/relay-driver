from sqlalchemy.engine import Engine

from app.drivers.daloradius import DISABLED_GROUP, DaloRadiusDriver
from tests.conftest import rows


def test_creating_a_customer_writes_the_password_and_details(driver: DaloRadiusDriver, radius_engine: Engine) -> None:
    result = driver.create_customer("254700000001", "secret", first_name="Wanjiku", phone="254700000001")

    assert result == {"status": "created", "username": "254700000001"}
    assert rows(radius_engine, "SELECT attribute, value FROM radcheck") == [{"attribute": "Cleartext-Password", "value": "secret"}]
    assert rows(radius_engine, "SELECT firstname FROM userinfo")[0]["firstname"] == "Wanjiku"


def test_creating_an_existing_customer_corrects_a_drifted_password(driver: DaloRadiusDriver, radius_engine: Engine) -> None:
    driver.create_customer("254700000001", "old")

    assert driver.create_customer("254700000001", "new")["status"] == "exists"
    assert rows(radius_engine, "SELECT value FROM radcheck")[0]["value"] == "new"


def test_suspend_and_resume_toggle_the_disabled_group(driver: DaloRadiusDriver, radius_engine: Engine) -> None:
    driver.deactivate_package("254700000001")
    driver.deactivate_package("254700000001")
    assert rows(radius_engine, "SELECT groupname FROM radusergroup") == [{"groupname": DISABLED_GROUP}]

    driver.resume_customer("254700000001")
    assert rows(radius_engine, "SELECT groupname FROM radusergroup") == []


def test_deleting_a_customer_removes_every_trace(driver: DaloRadiusDriver, radius_engine: Engine) -> None:
    driver.create_customer("254700000001", "secret", first_name="W")
    driver.activate_package("254700000001", "Daily", session_timeout_seconds=86400)

    driver.delete_customer("254700000001")

    for table in ("radcheck", "radusergroup", "userinfo"):
        assert rows(radius_engine, f"SELECT * FROM {table}") == []


def test_disconnect_closes_open_accounting_sessions(driver: DaloRadiusDriver, radius_engine: Engine) -> None:
    with radius_engine.begin() as conn:
        from sqlalchemy import text

        conn.execute(text("INSERT INTO radacct (username, acctstarttime) VALUES ('254700000001', '2026-10-27 08:00:00')"))

    assert driver.disconnect_session("254700000001")["closed_sessions"] == 1
    assert rows(radius_engine, "SELECT acctterminatecause FROM radacct")[0]["acctterminatecause"] == "Admin-Reset"
    assert driver.sessions() == []
