import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.drivers.manager import get_driver_manager

_START = time.monotonic()


def check(db: Session) -> dict[str, Any]:
    result: dict[str, Any] = {"service": "ok", "uptime": int(time.monotonic() - _START)}

    try:
        db.execute(text("SELECT 1"))
        result["database"] = "ok"
    except Exception:
        result["database"] = "error"

    try:
        driver_health = get_driver_manager().driver.health()
        result["driver"] = "ok"
        result.update(driver_health)
    except Exception:
        result["driver"] = "error"

    return result
