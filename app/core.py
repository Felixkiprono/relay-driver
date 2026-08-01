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

    dalo_db_host: str = ""
    dalo_db_port: int = 3308
    dalo_db_name: str = "radius"
    dalo_db_user: str = ""
    dalo_db_password: str = ""

    @property
    def dalo_db_url(self) -> str:
        return (
            f"mysql+pymysql://{self.dalo_db_user}:{self.dalo_db_password}"
            f"@{self.dalo_db_host}:{self.dalo_db_port}/{self.dalo_db_name}"
        )


settings = Settings()


def get_logger(name: str) -> logging.Logger:
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    return logging.getLogger(name)
