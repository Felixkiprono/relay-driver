from app.core import settings
from app.drivers.base import BaseDriver
from app.drivers.daloradius import DaloRadiusDriver

_REGISTRY: dict[str, type[BaseDriver]] = {
    "daloradius": DaloRadiusDriver,
}


class DriverManager:
    def __init__(self, driver_name: str | None = None) -> None:
        name = driver_name or settings.driver
        try:
            driver_cls = _REGISTRY[name]
        except KeyError:
            raise ValueError(f"Unknown driver: {name}") from None
        self.name = name
        self.driver: BaseDriver = driver_cls()

    def dispatch(self, action: str, **kwargs: object) -> object:
        method = getattr(self.driver, action, None)
        if method is None:
            raise ValueError(f"Driver '{self.name}' has no action '{action}'")
        return method(**kwargs)


_manager: DriverManager | None = None


def get_driver_manager() -> DriverManager:
    global _manager
    if _manager is None:
        _manager = DriverManager()
    return _manager
