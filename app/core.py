import logging
import time

from pydantic_settings import BaseSettings, SettingsConfigDict

__version__ = "0.1.0"
START_TIME = time.monotonic()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    host: str = "0.0.0.0"
    port: int = 8080
    log_level: str = "INFO"

    api_key: str = ""

    database_url: str = "sqlite:///data/relay.db"

    driver: str = "daloradius"

    dalo_url: str = ""
    dalo_username: str = ""
    dalo_password: str = ""


settings = Settings()


def get_logger(name: str) -> logging.Logger:
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    return logging.getLogger(name)
