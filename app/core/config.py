from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    host: str = "0.0.0.0"
    port: int = 8080
    log_level: str = "INFO"

    database_url: str = "sqlite:///data/relay.db"

    driver: str = "daloradius"

    dalo_url: str = ""
    dalo_username: str = ""
    dalo_password: str = ""

    mikrotik_host: str = ""
    mikrotik_username: str = ""
    mikrotik_password: str = ""


settings = Settings()
