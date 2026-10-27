from typing import Any

from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.engine import Connection, Engine

from app.core import get_logger, settings
from app.drivers.base import BaseDriver
from app.vendors import MANAGED_ATTRIBUTES, PackagePolicy, build_reply_attributes, parse_rate_limit

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

    def __init__(self, engine: Engine | None = None) -> None:
        # An engine can be injected (tests use an in-memory SQLite copy of
        # the FreeRADIUS schema); otherwise connect to the daloRADIUS MariaDB.
        self._engine: Engine = engine or create_engine(settings.dalo_db_url, pool_pre_ping=True)

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
                # Keep radcheck in sync with whatever password the caller currently
                # considers current, rather than silently keeping whatever was
                # written on first provisioning. Laravel's RadiusGateway.authenticate()
                # calls this endpoint on every access grant, not just the first one,
                # and always sends its own customers.radius_password — if that ever
                # diverges from what's already in radcheck (e.g. the caller's local
                # record was reset/regenerated after the first provisioning, or a
                # radcheck row was created some other way, e.g. directly in
                # daloRADIUS), silently skipping here leaves radcheck holding a
                # password the caller no longer has on file, and the customer's
                # actual mobile login attempt (sent using the caller's current
                # password) fails RADIUS auth against a value it has no way of
                # knowing is stale. Never log the password itself either way.
                current_password = conn.execute(
                    text(
                        "SELECT value FROM radcheck "
                        "WHERE username = :username AND attribute = 'Cleartext-Password'"
                    ),
                    {"username": username},
                ).scalar_one_or_none()

                if current_password != password:
                    conn.execute(
                        text(
                            "UPDATE radcheck SET value = :password "
                            "WHERE username = :username AND attribute = 'Cleartext-Password'"
                        ),
                        {"username": username, "password": password},
                    )
                    logger.warning(
                        "Radius: password drift detected on existing user, radcheck corrected. username=%s",
                        username,
                    )
                else:
                    logger.info("Radius: user already provisioned, password unchanged. username=%s", username)

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
        mikrotik_group: str | None = None,
        upload_kbps: int | None = None,
        download_kbps: int | None = None,
        data_limit_bytes: int | None = None,
        idle_timeout_seconds: int | None = None,
        interim_interval_seconds: int | None = None,
        profile: str | None = None,
        vendors: list[str] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Assign the user to the package's group and (re)write the group's
        reply attributes for every vendor in `vendors`. Attributes Relay
        manages are replaced on every call, so edited speeds and caps take
        effect; rows added by hand in daloRADIUS for other attributes stay.
        """
        if (upload_kbps is None or download_kbps is None) and rate_limit:
            parsed = parse_rate_limit(rate_limit)
            if parsed:
                upload_kbps, download_kbps = parsed

        policy = PackagePolicy(
            session_timeout_seconds=session_timeout_seconds,
            idle_timeout_seconds=idle_timeout_seconds,
            interim_interval_seconds=interim_interval_seconds,
            upload_kbps=upload_kbps,
            download_kbps=download_kbps,
            data_limit_bytes=data_limit_bytes,
            profile=profile or mikrotik_group,
        )
        attributes = build_reply_attributes(policy, vendors)

        with self._engine.begin() as conn:
            self._sync_group(conn, package, attributes)
            conn.execute(
                text("DELETE FROM radusergroup WHERE username = :username AND groupname != :disabled_group"),
                {"username": username, "disabled_group": DISABLED_GROUP},
            )
            conn.execute(
                text("INSERT INTO radusergroup (username, groupname, priority) VALUES (:username, :package, 0)"),
                {"username": username, "package": package},
            )

        logger.info("Radius: package activated. username=%s package=%s attributes=%d", username, package, len(attributes))
        return {"status": "activated", "username": username, "package": package, "attributes": [list(attribute) for attribute in attributes]}

    def sync_package(self, package: str, attributes: list[tuple[str, str]]) -> dict[str, Any]:
        """Rewrite a package group's managed reply attributes without touching its members."""
        with self._engine.begin() as conn:
            self._sync_group(conn, package, attributes)

        logger.info("Radius: package synced. package=%s attributes=%d", package, len(attributes))
        return {"status": "synced", "package": package, "attributes": [list(attribute) for attribute in attributes]}

    def _sync_group(self, conn: Connection, package: str, attributes: list[tuple[str, str]]) -> None:
        conn.execute(
            text("DELETE FROM radgroupreply WHERE groupname = :package AND attribute IN :managed").bindparams(
                bindparam("managed", expanding=True)
            ),
            {"package": package, "managed": list(MANAGED_ATTRIBUTES)},
        )
        for attribute, value in attributes:
            conn.execute(
                text("INSERT INTO radgroupreply (groupname, attribute, op, value) VALUES (:package, :attribute, ':=', :value)"),
                {"package": package, "attribute": attribute, "value": value},
            )

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

    def resume_customer(self, username: str, **kwargs: Any) -> dict[str, Any]:
        """Clears a suspension without touching whatever package group is already assigned."""
        with self._engine.begin() as conn:
            conn.execute(
                text("DELETE FROM radusergroup WHERE username = :username AND groupname = :disabled_group"),
                {"username": username, "disabled_group": DISABLED_GROUP},
            )

        logger.info("Radius: user resumed. username=%s", username)
        return {"status": "resumed", "username": username}

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
                    # Byte counters let LumaNet show live usage and top
                    # consumers. Only columns present in every FreeRADIUS
                    # radacct schema (2.x and 3.x) are selected.
                    "SELECT radacctid, acctsessionid, username, nasipaddress, framedipaddress, "
                    "callingstationid, calledstationid, acctstarttime, acctsessiontime, "
                    "acctinputoctets, acctoutputoctets "
                    "FROM radacct WHERE acctstoptime IS NULL ORDER BY acctstarttime DESC"
                )
            ).mappings()
            return [dict(row) for row in rows]

    def usage(self, since: str, until: str, group_by: str = "username", limit: int = 100) -> list[dict[str, Any]]:
        """Data and time used per customer (username) or router (nasipaddress), for sessions started in the range."""
        column = {"username": "username", "nas": "nasipaddress"}[group_by]
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    f"SELECT {column} AS key, COUNT(*) AS sessions, "
                    "COALESCE(SUM(acctoutputoctets), 0) AS download_bytes, "
                    "COALESCE(SUM(acctinputoctets), 0) AS upload_bytes, "
                    "COALESCE(SUM(acctsessiontime), 0) AS seconds "
                    "FROM radacct WHERE acctstarttime >= :since AND acctstarttime < :until "
                    f"GROUP BY {column} "
                    "ORDER BY COALESCE(SUM(acctoutputoctets), 0) + COALESCE(SUM(acctinputoctets), 0) DESC "
                    "LIMIT :limit"
                ),
                {"since": since, "until": until, "limit": limit},
            ).mappings()
            return [dict(row) for row in rows]

    def usage_daily(self, since: str, until: str) -> list[dict[str, Any]]:
        """Totals per day (by session start) across all routers."""
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT DATE(acctstarttime) AS day, COUNT(*) AS sessions, COUNT(DISTINCT username) AS users, "
                    "COALESCE(SUM(acctoutputoctets), 0) AS download_bytes, "
                    "COALESCE(SUM(acctinputoctets), 0) AS upload_bytes "
                    "FROM radacct WHERE acctstarttime >= :since AND acctstarttime < :until "
                    "GROUP BY DATE(acctstarttime) ORDER BY day"
                ),
                {"since": since, "until": until},
            ).mappings()
            return [{**dict(row), "day": str(row["day"])} for row in rows]

    def nas_list(self) -> list[dict[str, Any]]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, nasname, shortname, type, ports, secret, server, community, description "
                    "FROM nas ORDER BY id"
                )
            ).mappings()
            return [dict(row) for row in rows]

    def nas_get(self, nas_id: int) -> dict[str, Any] | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT id, nasname, shortname, type, ports, secret, server, community, description "
                    "FROM nas WHERE id = :id"
                ),
                {"id": nas_id},
            ).mappings().first()
            return dict(row) if row else None

    def nas_create(
        self,
        nasname: str,
        shortname: str | None = None,
        type: str | None = None,
        ports: int | None = None,
        secret: str | None = None,
        server: str | None = None,
        community: str | None = None,
        description: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        with self._engine.begin() as conn:
            result = conn.execute(
                text(
                    "INSERT INTO nas (nasname, shortname, type, ports, secret, server, community, description) "
                    "VALUES (:nasname, :shortname, :type, :ports, :secret, :server, :community, :description)"
                ),
                {
                    "nasname": nasname,
                    "shortname": shortname,
                    "type": type,
                    "ports": ports,
                    "secret": secret,
                    "server": server,
                    "community": community,
                    "description": description,
                },
            )
            nas_id = result.lastrowid

        logger.info("Radius: NAS created. id=%s nasname=%s", nas_id, nasname)
        return {"status": "created", "id": nas_id}

    def nas_update(self, nas_id: int, **fields: Any) -> dict[str, Any]:
        columns = ("nasname", "shortname", "type", "ports", "secret", "server", "community", "description")
        updates = {col: fields[col] for col in columns if fields.get(col) is not None}

        if updates:
            set_clause = ", ".join(f"{col} = :{col}" for col in updates)
            with self._engine.begin() as conn:
                conn.execute(text(f"UPDATE nas SET {set_clause} WHERE id = :id"), {**updates, "id": nas_id})

        logger.info("Radius: NAS updated. id=%s", nas_id)
        return {"status": "updated", "id": nas_id}

    def nas_delete(self, nas_id: int) -> dict[str, Any]:
        with self._engine.begin() as conn:
            conn.execute(text("DELETE FROM nas WHERE id = :id"), {"id": nas_id})

        logger.info("Radius: NAS deleted. id=%s", nas_id)
        return {"status": "deleted", "id": nas_id}

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
