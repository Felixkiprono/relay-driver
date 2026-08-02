from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.core import get_logger, settings
from app.drivers.base import BaseDriver

logger = get_logger(__name__)

DISABLED_GROUP = "daloRADIUS-Disabled-Users"
DISABLED_GROUP_PRIORITY = -1


class DaloRadiusDriver(BaseDriver):
    """
    Writes directly to daloRADIUS/FreeRADIUS's own tables (radcheck,
    radusergroup, radgroupreply, userinfo, radacct) over the exposed MariaDB
    connection — the same tables daloRADIUS's own admin UI writes to, and the
    same row conventions as the working Laravel RadiusService this was
    ported from (koren/apps/customer/app/Services/Radius/RadiusService.php).

    No RADIUS CoA/Disconnect-Request support: disconnect_session() closes the
    accounting record (radacct) but cannot force an already-connected device
    off the NAS mid-session — same limitation the source implementation had.
    """

    def __init__(self) -> None:
        self._engine: Engine = create_engine(settings.dalo_db_url, pool_pre_ping=True)

    def health(self) -> dict[str, Any]:
        target = f"{settings.dalo_db_host}:{settings.dalo_db_port}/{settings.dalo_db_name}"
        logger.info("Connecting to radius db at %s", target)
        try:
            with self._engine.connect() as conn:
                conn.execute(text("SELECT 1"))
        except Exception as exc:
            logger.warning("Radius db connection failed (%s): %s", target, exc)
            raise
        logger.info("Radius db connection succeeded (%s)", target)
        return {"radius_db": "healthy"}

    def create_customer(
        self,
        username: str,
        password: str,
        first_name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        with self._engine.begin() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM radcheck WHERE username = :username LIMIT 1"), {"username": username}
            ).first()
            if exists:
                logger.info("Radius: user already provisioned, skipping. username=%s", username)
                return {"status": "exists", "username": username}

            conn.execute(
                text(
                    "INSERT INTO radcheck (username, attribute, op, value) "
                    "VALUES (:username, 'Cleartext-Password', ':=', :password)"
                ),
                {"username": username, "password": password},
            )

            if first_name or email or phone:
                conn.execute(
                    text(
                        "INSERT INTO userinfo "
                        "(username, firstname, email, mobilephone, creationdate, creationby, updatedate, updateby) "
                        "VALUES (:username, :first_name, :email, :phone, NOW(), 'Relay', NOW(), 'Relay')"
                    ),
                    {"username": username, "first_name": first_name, "email": email, "phone": phone},
                )

        logger.info("Radius: user provisioned. username=%s", username)
        return {"status": "created", "username": username}

    def update_customer(
        self,
        username: str,
        password: str | None = None,
        first_name: str | None = None,
        email: str | None = None,
        phone: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        with self._engine.begin() as conn:
            if password:
                conn.execute(
                    text(
                        "UPDATE radcheck SET value = :password "
                        "WHERE username = :username AND attribute = 'Cleartext-Password'"
                    ),
                    {"username": username, "password": password},
                )

            updates = {
                col: value
                for col, value in (("firstname", first_name), ("email", email), ("mobilephone", phone))
                if value
            }
            if updates:
                set_clause = ", ".join(f"{col} = :{col}" for col in updates)
                conn.execute(
                    text(f"UPDATE userinfo SET {set_clause}, updatedate = NOW(), updateby = 'Relay' WHERE username = :username"),
                    {**updates, "username": username},
                )

        logger.info("Radius: user updated. username=%s", username)
        return {"status": "updated", "username": username}

    def delete_customer(self, username: str) -> dict[str, Any]:
        with self._engine.begin() as conn:
            for table in ("radcheck", "radreply", "radusergroup", "userinfo"):
                conn.execute(text(f"DELETE FROM {table} WHERE username = :username"), {"username": username})

        logger.info("Radius: user deleted. username=%s", username)
        return {"status": "deleted", "username": username}

    def activate_package(
        self,
        username: str,
        package: str,
        session_timeout_seconds: int | None = None,
        rate_limit: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        with self._engine.begin() as conn:
            group_configured = conn.execute(
                text("SELECT 1 FROM radgroupreply WHERE groupname = :package LIMIT 1"), {"package": package}
            ).first()
            if not group_configured:
                if session_timeout_seconds:
                    conn.execute(
                        text(
                            "INSERT INTO radgroupreply (groupname, attribute, op, value) "
                            "VALUES (:package, 'Session-Timeout', ':=', :value)"
                        ),
                        {"package": package, "value": str(session_timeout_seconds)},
                    )
                if rate_limit:
                    conn.execute(
                        text(
                            "INSERT INTO radgroupreply (groupname, attribute, op, value) "
                            "VALUES (:package, 'Mikrotik-Rate-Limit', ':=', :value)"
                        ),
                        {"package": package, "value": rate_limit},
                    )
                logger.info("Radius: group bootstrapped. package=%s", package)

            conn.execute(
                text("DELETE FROM radusergroup WHERE username = :username AND groupname != :disabled_group"),
                {"username": username, "disabled_group": DISABLED_GROUP},
            )
            conn.execute(
                text("INSERT INTO radusergroup (username, groupname, priority) VALUES (:username, :package, 0)"),
                {"username": username, "package": package},
            )

        logger.info("Radius: package activated. username=%s package=%s", username, package)
        return {"status": "activated", "username": username, "package": package}

    def deactivate_package(self, username: str, **kwargs: Any) -> dict[str, Any]:
        with self._engine.begin() as conn:
            conn.execute(
                text("DELETE FROM radusergroup WHERE username = :username AND groupname = :disabled_group"),
                {"username": username, "disabled_group": DISABLED_GROUP},
            )
            conn.execute(
                text(
                    "INSERT INTO radusergroup (username, groupname, priority) "
                    "VALUES (:username, :disabled_group, :priority)"
                ),
                {"username": username, "disabled_group": DISABLED_GROUP, "priority": DISABLED_GROUP_PRIORITY},
            )

        logger.info("Radius: user disabled. username=%s", username)
        return {"status": "deactivated", "username": username}

    def disconnect_session(self, username: str, **kwargs: Any) -> dict[str, Any]:
        with self._engine.begin() as conn:
            result = conn.execute(
                text(
                    "UPDATE radacct SET acctstoptime = NOW(), acctterminatecause = 'Admin-Reset' "
                    "WHERE username = :username AND acctstoptime IS NULL"
                ),
                {"username": username},
            )

        logger.info("Radius: session(s) closed. username=%s closed=%d", username, result.rowcount)
        return {"status": "disconnected", "username": username, "closed_sessions": result.rowcount}

    def sessions(self) -> list[dict[str, Any]]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT username, nasipaddress, framedipaddress, callingstationid, "
                    "acctstarttime, acctsessiontime "
                    "FROM radacct WHERE acctstoptime IS NULL ORDER BY acctstarttime DESC"
                )
            ).mappings()
            return [dict(row) for row in rows]

    def statistics(self) -> dict[str, Any]:
        with self._engine.connect() as conn:
            total_customers = conn.execute(text("SELECT COUNT(DISTINCT username) FROM radcheck")).scalar_one()
            active_sessions = conn.execute(
                text("SELECT COUNT(*) FROM radacct WHERE acctstoptime IS NULL")
            ).scalar_one()
            disabled_users = conn.execute(
                text("SELECT COUNT(*) FROM radusergroup WHERE groupname = :disabled_group"),
                {"disabled_group": DISABLED_GROUP},
            ).scalar_one()

        return {
            "total_customers": total_customers,
            "active_sessions": active_sessions,
            "disabled_users": disabled_users,
        }
