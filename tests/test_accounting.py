from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.engine import Engine


def seed(engine: Engine) -> None:
    sessions = [
        ("u1", "10.200.0.10", "2026-10-20 08:00:00", None, 600, 1_000, 50_000),
        ("u1", "10.200.0.10", "2026-10-21 09:00:00", "2026-10-21 10:00:00", 3600, 2_000, 150_000),
        ("u2", "10.200.0.11", "2026-10-21 12:00:00", "2026-10-21 12:30:00", 1800, 500, 10_000),
        ("u3", "10.200.0.11", "2026-09-01 12:00:00", "2026-09-01 12:30:00", 1800, 9_999, 9_999_999),
    ]
    with engine.begin() as conn:
        for username, nas, start, stop, seconds, up, down in sessions:
            conn.execute(
                text("INSERT INTO radacct (username, nasipaddress, acctstarttime, acctstoptime, acctsessiontime, acctinputoctets, acctoutputoctets) VALUES (:u, :n, :s, :e, :t, :i, :o)"),
                {"u": username, "n": nas, "s": start, "e": stop, "t": seconds, "i": up, "o": down},
            )


def test_usage_per_customer_covers_open_and_closed_sessions_in_range(client: TestClient, radius_engine: Engine) -> None:
    seed(radius_engine)

    usage = client.get("/api/v1/accounting/usage", params={"since": "2026-10-01", "until": "2026-11-01"}).json()

    assert usage[0] == {"key": "u1", "sessions": 2, "download_bytes": 200_000, "upload_bytes": 3_000, "seconds": 4200}
    assert [row["key"] for row in usage] == ["u1", "u2"]


def test_usage_per_router(client: TestClient, radius_engine: Engine) -> None:
    seed(radius_engine)

    usage = client.get("/api/v1/accounting/usage", params={"since": "2026-10-01", "until": "2026-11-01", "group_by": "nas"}).json()

    assert {row["key"]: row["sessions"] for row in usage} == {"10.200.0.10": 2, "10.200.0.11": 1}


def test_daily_usage(client: TestClient, radius_engine: Engine) -> None:
    seed(radius_engine)

    daily = client.get("/api/v1/accounting/daily", params={"since": "2026-10-20", "until": "2026-10-22"}).json()

    assert daily == [
        {"day": "2026-10-20", "sessions": 1, "users": 1, "download_bytes": 50_000, "upload_bytes": 1_000},
        {"day": "2026-10-21", "sessions": 2, "users": 2, "download_bytes": 160_000, "upload_bytes": 2_500},
    ]


def test_bad_ranges_are_rejected(client: TestClient) -> None:
    assert client.get("/api/v1/accounting/usage", params={"since": "nope", "until": "2026-11-01"}).status_code == 422
    assert client.get("/api/v1/accounting/usage", params={"since": "2026-10-01", "until": "2026-11-01", "group_by": "x"}).status_code == 422
