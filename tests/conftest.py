"""
Test setup: Relay's own SQLite DB goes to a temp file, and the daloRADIUS
driver runs against an in-memory SQLite copy of the FreeRADIUS tables it
touches (radcheck, radusergroup, radgroupreply, radreply, userinfo, radacct,
nas). MySQL's NOW() is registered as a SQLite function so the driver's SQL
runs unchanged.
"""

import os
import tempfile
from collections.abc import Iterator
from datetime import UTC, datetime

_tmp = tempfile.mkdtemp(prefix="relay-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/relay.db"
os.environ.setdefault("API_KEY", "test-key")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event, text  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.api import v1  # noqa: E402
from app.database import init_db  # noqa: E402
from app.drivers.daloradius import DaloRadiusDriver  # noqa: E402
from app.drivers.manager import DriverManager  # noqa: E402
from app.main import app  # noqa: E402

RADIUS_SCHEMA = [
    "CREATE TABLE radcheck (id INTEGER PRIMARY KEY, username TEXT, attribute TEXT, op TEXT, value TEXT)",
    "CREATE TABLE radreply (id INTEGER PRIMARY KEY, username TEXT, attribute TEXT, op TEXT, value TEXT)",
    "CREATE TABLE radusergroup (id INTEGER PRIMARY KEY, username TEXT, groupname TEXT, priority INTEGER)",
    "CREATE TABLE radgroupreply (id INTEGER PRIMARY KEY, groupname TEXT, attribute TEXT, op TEXT, value TEXT)",
    "CREATE TABLE userinfo (id INTEGER PRIMARY KEY, username TEXT, firstname TEXT, email TEXT, mobilephone TEXT,"
    " creationdate TEXT, creationby TEXT, updatedate TEXT, updateby TEXT)",
    "CREATE TABLE nas (id INTEGER PRIMARY KEY, nasname TEXT, shortname TEXT, type TEXT, ports INTEGER, secret TEXT,"
    " server TEXT, community TEXT, description TEXT)",
    "CREATE TABLE radacct (radacctid INTEGER PRIMARY KEY, acctsessionid TEXT, username TEXT, nasipaddress TEXT,"
    " framedipaddress TEXT, callingstationid TEXT, calledstationid TEXT, acctstarttime TEXT, acctstoptime TEXT,"
    " acctsessiontime INTEGER, acctinputoctets INTEGER, acctoutputoctets INTEGER, acctterminatecause TEXT)",
]


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


@pytest.fixture
def radius_engine() -> Iterator[Engine]:
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _register_now(dbapi_connection, _record) -> None:  # type: ignore[no-untyped-def]
        dbapi_connection.create_function("NOW", 0, _now)

    with engine.begin() as conn:
        for statement in RADIUS_SCHEMA:
            conn.execute(text(statement))

    yield engine
    engine.dispose()


@pytest.fixture
def driver(radius_engine: Engine) -> DaloRadiusDriver:
    return DaloRadiusDriver(engine=radius_engine)


@pytest.fixture
def client(driver: DaloRadiusDriver, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    init_db()
    manager = DriverManager("daloradius", driver=driver)
    monkeypatch.setattr(v1, "get_driver_manager", lambda: manager)
    return TestClient(app, headers={"X-API-KEY": "test-key"})


def rows(engine: Engine, sql: str, **params: object) -> list[dict[str, object]]:
    with engine.connect() as conn:
        return [dict(row) for row in conn.execute(text(sql), params).mappings()]
