from typing import Any

import httpx

from app.core import settings
from app.drivers.base import BaseDriver


class DaloRadiusDriver(BaseDriver):
    def __init__(self) -> None:
        self._client = httpx.Client(
            base_url=settings.dalo_url,
            auth=(settings.dalo_username, settings.dalo_password),
            timeout=10.0,
        )

    def health(self) -> dict[str, Any]:
        raise NotImplementedError

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
