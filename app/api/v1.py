import time
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import START_TIME, __version__, get_logger, settings
from app.database import get_db
from app.drivers.manager import get_driver_manager
from app.models import AuditLog

logger = get_logger(__name__)

router = APIRouter(prefix="/api/v1")


def verify_api_key(x_api_key: str = Header(default="")) -> None:
    if not settings.api_key or x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


def log_audit(db: Session, action: str, target: str | None = None) -> None:
    db.add(AuditLog(action=action, target=target))
    db.commit()


class CreateCustomerRequest(BaseModel):
    username: str
    password: str


class UpdateCustomerRequest(BaseModel):
    password: str | None = None


class PackageRequest(BaseModel):
    username: str
    package: str


class UsernameRequest(BaseModel):
    username: str


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, Any]:
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


@router.get("/version", dependencies=[Depends(verify_api_key)])
def version() -> dict[str, str]:
    return {"version": __version__}


@router.get("/driver", dependencies=[Depends(verify_api_key)])
def driver() -> dict[str, str]:
    return {"driver": settings.driver}


@router.post("/customer", dependencies=[Depends(verify_api_key)])
def create_customer(body: CreateCustomerRequest, db: Session = Depends(get_db)) -> Any:
    result = get_driver_manager().dispatch("create_customer", username=body.username, password=body.password)
    log_audit(db, "create_customer", body.username)
    return result


@router.put("/customer/{username}", dependencies=[Depends(verify_api_key)])
def update_customer(username: str, body: UpdateCustomerRequest, db: Session = Depends(get_db)) -> Any:
    result = get_driver_manager().dispatch("update_customer", username=username, **body.model_dump(exclude_none=True))
    log_audit(db, "update_customer", username)
    return result


@router.delete("/customer/{username}", dependencies=[Depends(verify_api_key)])
def delete_customer(username: str, db: Session = Depends(get_db)) -> Any:
    result = get_driver_manager().dispatch("delete_customer", username=username)
    log_audit(db, "delete_customer", username)
    return result


@router.post("/package/activate", dependencies=[Depends(verify_api_key)])
def activate_package(body: PackageRequest, db: Session = Depends(get_db)) -> Any:
    result = get_driver_manager().dispatch("activate_package", username=body.username, package=body.package)
    log_audit(db, "activate_package", body.username)
    return result


@router.post("/package/deactivate", dependencies=[Depends(verify_api_key)])
def deactivate_package(body: UsernameRequest, db: Session = Depends(get_db)) -> Any:
    result = get_driver_manager().dispatch("deactivate_package", username=body.username)
    log_audit(db, "deactivate_package", body.username)
    return result


@router.post("/session/disconnect", dependencies=[Depends(verify_api_key)])
def disconnect_session(body: UsernameRequest, db: Session = Depends(get_db)) -> Any:
    result = get_driver_manager().dispatch("disconnect_session", username=body.username)
    log_audit(db, "disconnect_session", body.username)
    return result


@router.get("/sessions", dependencies=[Depends(verify_api_key)])
def sessions() -> Any:
    return get_driver_manager().dispatch("sessions")


@router.get("/statistics", dependencies=[Depends(verify_api_key)])
def statistics() -> Any:
    return get_driver_manager().dispatch("statistics")
