from typing import Any

from sqlalchemy.orm import Session

from app.drivers.manager import get_driver_manager
from app.models.health import AuditLog, Job


def execute(db: Session, action: str, actor: str = "api", **kwargs: Any) -> Any:
    manager = get_driver_manager()
    job = Job(driver=manager.name, action=action, status="running")
    db.add(job)
    db.commit()

    try:
        result = manager.dispatch(action, **kwargs)
        job.status = "done"
    except Exception as exc:
        job.status = "failed"
        job.error = str(exc)
        raise
    finally:
        db.add(AuditLog(actor=actor, action=action, target=kwargs.get("username")))
        db.commit()

    return result
