from abc import ABC, abstractmethod
from typing import Any


class BaseDriver(ABC):
    @abstractmethod
    def health(self) -> dict[str, Any]: ...

    @abstractmethod
    def create_customer(self, username: str, password: str, **kwargs: Any) -> dict[str, Any]: ...

    @abstractmethod
    def update_customer(self, username: str, **kwargs: Any) -> dict[str, Any]: ...

    @abstractmethod
    def delete_customer(self, username: str) -> dict[str, Any]: ...

    @abstractmethod
    def activate_package(self, username: str, package: str, **kwargs: Any) -> dict[str, Any]: ...

    @abstractmethod
    def deactivate_package(self, username: str, **kwargs: Any) -> dict[str, Any]: ...

    @abstractmethod
    def disconnect_session(self, username: str, **kwargs: Any) -> dict[str, Any]: ...

    @abstractmethod
    def sessions(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def statistics(self) -> dict[str, Any]: ...
