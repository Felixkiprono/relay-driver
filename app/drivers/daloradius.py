from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.core import get_logger, settings
from app.drivers.base import BaseDriver

logger = get_logger(__name__)


class DaloRadiusDriver(BaseDriver):
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

    def create_customer(self, username: str, password: str, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError

    def update_customer(self, username: str, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError

    def delete_customer(self, username: str) -> dict[str, Any]:
        raise NotImplementedError

    def activate_package(self, username: str, package: str) -> dict[str, Any]:
        raise NotImplementedError

    def deactivate_package(self, username: str) -> dict[str, Any]:
        raise NotImplementedError

    def disconnect_session(self, username: str) -> dict[str, Any]:
        raise NotImplementedError

    def sessions(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def statistics(self) -> dict[str, Any]:
        raise NotImplementedError
