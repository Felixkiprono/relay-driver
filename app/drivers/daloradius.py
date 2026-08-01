from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from app.core import settings
from app.drivers.base import BaseDriver


class DaloRadiusDriver(BaseDriver):
    def __init__(self) -> None:
        self._engine: Engine = create_engine(settings.dalo_db_url, pool_pre_ping=True)

    def health(self) -> dict[str, Any]:
        with self._engine.connect() as conn:
            conn.execute(text("SELECT 1"))
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
