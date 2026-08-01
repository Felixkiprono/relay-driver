from typing import Any

import httpx

from app.core.config import settings
from app.drivers.base import BaseDriver


class DaloRadiusDriver(BaseDriver):
    def __init__(self) -> None:
        self._client: httpx.Client | None = None

    def connect(self) -> None:
        self._client = httpx.Client(
            base_url=settings.dalo_url,
            auth=(settings.dalo_username, settings.dalo_password),
            timeout=10.0,
        )

    def disconnect(self) -> None:
        if self._client:
            self._client.close()
            self._client = None

    def health(self) -> dict[str, Any]:
        raise NotImplementedError

    def create_user(self, username: str, password: str, **kwargs: Any) -> dict[str, Any]:
        raise NotImplementedError

    def delete_user(self, username: str) -> dict[str, Any]:
        raise NotImplementedError

    def activate_package(self, username: str, package: str) -> dict[str, Any]:
        raise NotImplementedError

    def disconnect_user(self, username: str) -> dict[str, Any]:
        raise NotImplementedError

    def online_users(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def statistics(self) -> dict[str, Any]:
        raise NotImplementedError
