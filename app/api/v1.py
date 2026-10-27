import secrets
import time
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Security
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core import START_TIME, __version__, get_logger, settings
from app.database import get_db
from app.drivers.manager import get_driver_manager
from app.models import AuditLog, DnsQuery
from app.vendors import FAMILIES, VENDORS, PackagePolicy, build_reply_attributes, families_for, nas_type_for

logger = get_logger(__name__)

api_key_header = APIKeyHeader(name="X-API-KEY", auto_error=False)


def verify_api_key(x_api_key: str | None = Security(api_key_header)) -> None:
    """Enforced when REQUIRE_API_KEY=true (see Settings.require_api_key)."""
    if not settings.require_api_key:
        return
    if not settings.api_key or not x_api_key or not secrets.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-KEY")


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


class PolicyFields(BaseModel):
    session_timeout_seconds: int | None = Field(default=None, ge=1)
    idle_timeout_seconds: int | None = Field(default=None, ge=1)
    interim_interval_seconds: int | None = Field(default=None, ge=30)
    upload_kbps: int | None = Field(default=None, ge=1)
    download_kbps: int | None = Field(default=None, ge=1)
    data_limit_bytes: int | None = Field(default=None, ge=1)
    profile: str | None = None
    # Vendor keys present in the fleet (LumaNet's RouterVendor values);
    # decides which attribute families are written. Defaults to MikroTik.
    vendors: list[str] | None = None

    def policy(self) -> PackagePolicy:
        return PackagePolicy(**{name: getattr(self, name) for name in PackagePolicy.__dataclass_fields__})


class PackageRequest(PolicyFields):
    username: str
    package: str
    max_devices: int | None = Field(default=None, ge=0, le=50)
    # ISO 8601; on-site subscriptions end on a date rather than a timer.
    expires_at: str | None = None
    # Legacy fields, still accepted from older LumaNet versions.
    rate_limit: str | None = None
    mikrotik_group: str | None = None


class PackageSyncRequest(PolicyFields):
    package: str
    max_devices: int | None = Field(default=None, ge=0, le=50)


class ExpirationRequest(BaseModel):
    expires_at: str | None = None


class UsernameRequest(BaseModel):
    username: str


class NasRequest(BaseModel):
    nasname: str
    shortname: str | None = None
    type: str | None = None
    ports: int | None = None
    secret: str | None = None
    server: str | None = None
    community: str | None = None
    description: str | None = None


class NasUpdateRequest(BaseModel):
    nasname: str | None = None
    shortname: str | None = None
    type: str | None = None
    ports: int | None = None
    secret: str | None = None
    server: str | None = None
    community: str | None = None
    description: str | None = None


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


@router.put("/customer/{username}/expiration", tags=["customer"], summary="Set or clear the date after which RADIUS refuses this user")
def set_expiration(username: str, body: ExpirationRequest, db: Session = Depends(get_db)) -> Any:
    result = get_driver_manager().dispatch("set_expiration", username=username, expires_at=body.expires_at or "")
    log_audit(db, "set_expiration", username)
    return result


@router.post("/package/activate", tags=["package"], summary="Assign a package and grant network access")
def activate_package(body: PackageRequest, db: Session = Depends(get_db)) -> Any:
    try:
        families_for(body.vendors)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    result = get_driver_manager().dispatch("activate_package", **body.model_dump(exclude_none=True))
    log_audit(db, "activate_package", body.username)
    return result


@router.post("/package/sync", tags=["package"], summary="Rewrite a package's reply attributes for the fleet's vendors")
def sync_package(body: PackageSyncRequest, db: Session = Depends(get_db)) -> Any:
    """Call after editing a package so new speeds/caps reach routers without re-activating every customer."""
    attributes = _attributes_or_422(body)
    result = get_driver_manager().dispatch("sync_package", package=body.package, attributes=attributes, max_devices=body.max_devices)
    log_audit(db, "sync_package", body.package)
    return result


@router.post("/package/preview", tags=["package"], summary="Show the reply attributes a package would produce, without writing")
def preview_package(body: PolicyFields) -> Any:
    return {
        "attributes": [list(attribute) for attribute in _attributes_or_422(body)],
        "by_vendor": {
            vendor: [list(attribute) for attribute in build_reply_attributes(body.policy(), [vendor])]
            for vendor in (body.vendors or ["mikrotik"])
        },
    }


@router.get("/vendors", tags=["meta"], summary="Router vendors Relay can write attributes for")
def vendors() -> Any:
    return [
        {
            "key": vendor.key,
            "label": vendor.label,
            "family": vendor.family,
            "nas_type": vendor.nas_type,
            "supports_rate": bool(vendor.family and FAMILIES[vendor.family].supports_rate),
            "supports_quota": bool(vendor.family and FAMILIES[vendor.family].supports_quota),
            "supports_profile": bool(vendor.family and FAMILIES[vendor.family].supports_profile),
            "notes": vendor.notes,
        }
        for vendor in VENDORS.values()
    ]


def _attributes_or_422(body: PolicyFields) -> list[tuple[str, str]]:
    try:
        return build_reply_attributes(body.policy(), body.vendors)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None


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


@router.get("/accounting/usage", tags=["session"], summary="Data and time used per customer or router")
def accounting_usage(
    since: date,
    until: date,
    group_by: Literal["username", "nas"] = "username",
    limit: int = Query(default=100, ge=1, le=1000),
) -> Any:
    """Sessions started from `since` up to (not including) `until`, heaviest first."""
    return get_driver_manager().dispatch("usage", since=since.isoformat(), until=until.isoformat(), group_by=group_by, limit=limit)


@router.get("/accounting/daily", tags=["session"], summary="Sessions, users and data per day")
def accounting_daily(since: date, until: date) -> Any:
    return get_driver_manager().dispatch("usage_daily", since=since.isoformat(), until=until.isoformat())


@router.get("/statistics", tags=["meta"], summary="Customer/session counters")
def statistics() -> Any:
    return get_driver_manager().dispatch("statistics")


@router.get("/nas", tags=["nas"], summary="List NAS (network access server) records")
def list_nas() -> Any:
    return get_driver_manager().dispatch("nas_list")


@router.get("/nas/{nas_id}", tags=["nas"], summary="Get a single NAS record")
def get_nas(nas_id: int) -> Any:
    return get_driver_manager().dispatch("nas_get", nas_id=nas_id)


@router.post("/nas", tags=["nas"], summary="Create a NAS record")
def create_nas(body: NasRequest, db: Session = Depends(get_db)) -> Any:
    fields = body.model_dump(exclude_none=True)
    if "type" in fields:
        fields["type"] = nas_type_for(fields["type"])
    result = get_driver_manager().dispatch("nas_create", **fields)
    log_audit(db, "create_nas", body.nasname)
    return result


@router.put("/nas/{nas_id}", tags=["nas"], summary="Update a NAS record")
def update_nas(nas_id: int, body: NasUpdateRequest, db: Session = Depends(get_db)) -> Any:
    fields = body.model_dump(exclude_none=True)
    if "type" in fields:
        fields["type"] = nas_type_for(fields["type"])
    result = get_driver_manager().dispatch("nas_update", nas_id=nas_id, **fields)
    log_audit(db, "update_nas", str(nas_id))
    return result


@router.delete("/nas/{nas_id}", tags=["nas"], summary="Delete a NAS record")
def delete_nas(nas_id: int, db: Session = Depends(get_db)) -> Any:
    result = get_driver_manager().dispatch("nas_delete", nas_id=nas_id)
    log_audit(db, "delete_nas", str(nas_id))
    return result


@router.get("/dns-log", tags=["dns"], summary="Top-level domains resolved by hotspot clients, as captured from RouterOS DNS logging")
def dns_log(since_id: int = 0, limit: int = 500, db: Session = Depends(get_db)) -> Any:
    """Ordered by id ascending so a caller can page through with `since_id = last id seen`."""
    limit = min(limit, 1000)

    rows = (
        db.query(DnsQuery)
        .filter(DnsQuery.id > since_id)
        .order_by(DnsQuery.id.asc())
        .limit(limit)
        .all()
    )

    return [
        {"id": row.id, "client_ip": row.client_ip, "domain": row.domain, "queried_at": row.queried_at.isoformat()}
        for row in rows
    ]
