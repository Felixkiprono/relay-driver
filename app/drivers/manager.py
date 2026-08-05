from app.core import get_logger, settings
from app.drivers.base import BaseDriver
from app.drivers.daloradius import DaloRadiusDriver

logger = get_logger(__name__)

_REGISTRY: dict[str, type[BaseDriver]] = {
    "daloradius": DaloRadiusDriver,
}

REDACTED_ARGS = {"password"}


class DriverManager:
    def __init__(self, driver_name: str | None = None) -> None:
        name = driver_name or settings.driver
        try:
            driver_cls = _REGISTRY[name]
        except KeyError:
            raise ValueError(f"Unknown driver: {name}") from None
        self.name = name
        self.driver: BaseDriver = driver_cls()
        logger.info("Driver manager initialized. driver=%s", name)

    def dispatch(self, action: str, **kwargs: object) -> object:
        method = getattr(self.driver, action, None)
        if method is None:
            raise ValueError(f"Driver '{self.name}' has no action '{action}'")

        logged_args = {k: ("[redacted]" if k in REDACTED_ARGS else v) for k, v in kwargs.items()}
        logger.info("Driver: dispatching %s.%s args=%s", self.name, action, logged_args)

        try:
            result = method(**kwargs)
        except Exception:
            logger.exception("Driver: %s.%s failed. args=%s", self.name, action, logged_args)
            raise

        logger.info("Driver: %s.%s ok. result=%s", self.name, action, result)
        return result


_manager: DriverManager | None = None


def get_driver_manager() -> DriverManager:
    global _manager
    if _manager is None:
        _manager = DriverManager()
    return _manager
