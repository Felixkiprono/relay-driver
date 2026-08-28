from datetime import UTC, datetime

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Setting(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String, unique=True, index=True)
    value: Mapped[str] = mapped_column(String)
    updated_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class HealthCheck(Base):
    __tablename__ = "health_checks"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String)
    detail: Mapped[str | None] = mapped_column(String, nullable=True)
    checked_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    action: Mapped[str] = mapped_column(String)
    target: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))


class DnsQuery(Base):
    """
    One row per DNS query a hotspot client made, as reported by a MikroTik's
    own `topics=dns` syslog stream (see app/dns_listener.py) — never a proxy
    or packet inspection, just the router's own recursive/forwarding DNS
    server telling us what it resolved and for whom. `domain` is already
    reduced to the registrable/top-level domain (e.g. "google.com", not
    "www.google.com") before being stored, so Laravel doesn't need to.
    """

    __tablename__ = "dns_queries"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_ip: Mapped[str] = mapped_column(String, index=True)
    domain: Mapped[str] = mapped_column(String, index=True)
    queried_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC), index=True)
