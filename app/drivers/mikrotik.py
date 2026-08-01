from typing import Any

from app.drivers.base import BaseDriver


class MikroTikDriver(BaseDriver):
    def __init__(self) -> None:
        self._connected = False

    def connect(self) -> None:
        raise NotImplementedError

    def disconnect(self) -> None:
        self._connected = False

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
