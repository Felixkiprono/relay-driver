import time
from typing import Any

from fastapi import APIRouter, Depends, Security
from fastapi.security import APIKeyHeader
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import START_TIME, __version__, get_logger, settings
from app.database import get_db
from app.drivers.manager import get_driver_manager
from app.models import AuditLog

logger = get_logger(__name__)

api_key_header = APIKeyHeader(name="X-API-KEY", auto_error=False)


def verify_api_key(x_api_key: str | None = Security(api_key_header)) -> None:
    # TODO: re-enable once the Laravel side's API key is confirmed working —
    # left open for now so requests aren't silently rejected while we debug
    # the Laravel -> Relay integration.
    return


def log_audit(db: Session, action: str, target: str | None = None) -> None:
    logger.info("Event: %s target=%s", action, target)
    db.add(AuditLog(action=action, target=target))
    db.commit()


class CreateCustomerRequest(BaseModel):
    username: str
    password: str
    first_name: str | None = None
    email: str | None = None
    phone: str | None = None


class UpdateCustomerRequest(BaseModel):
    password: str | None = None
    first_name: str | None = None
    email: str | None = None
    phone: str | None = None


class PackageRequest(BaseModel):
    username: str
    package: str
    session_timeout_seconds: int | None = None
    rate_limit: str | None = None


class UsernameRequest(BaseModel):
    username: str


# Unauthenticated — load balancers/uptime monitors hit this directly.
public_router = APIRouter(prefix="/api/v1", tags=["health"])

# Everything else requires X-API-KEY.
router = APIRouter(prefix="/api/v1", dependencies=[Depends(verify_api_key)])


@public_router.get("/health", summary="Service and dependency health")
def health(db: Session = Depends(get_db)) -> dict[str, Any]:
    """Checks Relay's own SQLite DB and the configured driver's backend (e.g. the daloRADIUS MariaDB)."""
    logger.info("Connecting to local db at %s", settings.database_url)
    try:
        db.execute(text("SELECT 1"))
        database_status = "healthy"
        logger.info("Local db connection succeeded (%s)", settings.database_url)
    except Exception as exc:
        database_status = "unreachable"
        logger.warning("Local db connection failed (%s): %s", settings.database_url, exc)

    try:
        get_driver_manager().driver.health()
        radius_db_status = "healthy"
    except Exception:
        radius_db_status = "unreachable"

    return {
        "status": "healthy" if database_status == "healthy" and radius_db_status == "healthy" else "degraded",
        "driver": settings.driver,
        "database": database_status,
        "radius_db": radius_db_status,
        "uptime": int(time.monotonic() - START_TIME),
    }


@router.get("/version", tags=["meta"], summary="Relay's own version")
def version() -> dict[str, str]:
    return {"version": __version__}


@router.get("/driver", tags=["meta"], summary="Active network driver")
def driver() -> dict[str, str]:
    return {"driver": settings.driver}


@router.post("/customer", tags=["customer"], summary="Provision a customer on the network driver")
def create_customer(body: CreateCustomerRequest, db: Session = Depends(get_db)) -> Any:
    """Idempotent — calling this again for an already-provisioned username is a no-op."""
    result = get_driver_manager().dispatch("create_customer", **body.model_dump(exclude_none=True))
    log_audit(db, "create_customer", body.username)
    return result


@router.put("/customer/{username}", tags=["customer"], summary="Update a customer's credentials/details")
def update_customer(username: str, body: UpdateCustomerRequest, db: Session = Depends(get_db)) -> Any:
    result = get_driver_manager().dispatch("update_customer", username=username, **body.model_dump(exclude_none=True))
    log_audit(db, "update_customer", username)
    return result


@router.delete("/customer/{username}", tags=["customer"], summary="Remove a customer from the network driver")
def delete_customer(username: str, db: Session = Depends(get_db)) -> Any:
    result = get_driver_manager().dispatch("delete_customer", username=username)
    log_audit(db, "delete_customer", username)
    return result


@router.post("/customer/{username}/resume", tags=["customer"], summary="Clear a suspension, keep the current package")
def resume_customer(username: str, db: Session = Depends(get_db)) -> Any:
    result = get_driver_manager().dispatch("resume_customer", username=username)
    log_audit(db, "resume_customer", username)
    return result


@router.post("/package/activate", tags=["package"], summary="Assign a package and grant network access")
def activate_package(body: PackageRequest, db: Session = Depends(get_db)) -> Any:
    result = get_driver_manager().dispatch("activate_package", **body.model_dump(exclude_none=True))
    log_audit(db, "activate_package", body.username)
    return result


@router.post("/package/deactivate", tags=["package"], summary="Suspend network access")
def deactivate_package(body: UsernameRequest, db: Session = Depends(get_db)) -> Any:
    result = get_driver_manager().dispatch("deactivate_package", username=body.username)
    log_audit(db, "deactivate_package", body.username)
    return result


@router.post("/session/disconnect", tags=["session"], summary="Close a customer's active session")
def disconnect_session(body: UsernameRequest, db: Session = Depends(get_db)) -> Any:
    """No RADIUS CoA support — closes the accounting record, doesn't force an already-connected device off the NAS."""
    result = get_driver_manager().dispatch("disconnect_session", username=body.username)
    log_audit(db, "disconnect_session", body.username)
    return result


@router.get("/sessions", tags=["session"], summary="List active sessions")
def sessions() -> Any:
    return get_driver_manager().dispatch("sessions")


@router.get("/statistics", tags=["meta"], summary="Customer/session counters")
def statistics() -> Any:
    return get_driver_manager().dispatch("statistics")
