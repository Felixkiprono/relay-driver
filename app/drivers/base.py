from abc import ABC, abstractmethod
from typing import Any


class BaseDriver(ABC):
    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def health(self) -> dict[str, Any]: ...

    @abstractmethod
    def create_user(self, username: str, password: str, **kwargs: Any) -> dict[str, Any]: ...

    @abstractmethod
    def delete_user(self, username: str) -> dict[str, Any]: ...

    @abstractmethod
    def activate_package(self, username: str, package: str) -> dict[str, Any]: ...

    @abstractmethod
    def disconnect_user(self, username: str) -> dict[str, Any]: ...

    @abstractmethod
    def online_users(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def statistics(self) -> dict[str, Any]: ...
