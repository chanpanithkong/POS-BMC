"""Application settings, read from environment variables and backend/.env (NFR-MNT-006)."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated
from urllib.parse import quote_plus

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    app_name: str = "PIMS API"

    db_host: str = "localhost"
    db_port: int = 5432
    db_user: str = "postgres"
    db_password: SecretStr = SecretStr("")
    db_name: str = "pims_db"
    test_db_name: str = "pims_test_db"
    # Optional full override, for example in Docker.
    database_url_override: str | None = Field(default=None, alias="DATABASE_URL")

    secret_key: SecretStr
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    session_idle_minutes: int = 30
    session_absolute_hours: int = 12
    jwt_algorithm: str = "HS256"

    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]
    refresh_cookie_name: str = "pims_refresh"
    refresh_cookie_secure: bool = False

    # Uploaded files (product images). Kept outside git; mount a volume in Docker.
    storage_dir: Path = BACKEND_DIR / "storage"

    login_lock_attempts: int = 5
    login_lock_window_minutes: int = 15

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        if isinstance(value, str) and not value.startswith("["):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("secret_key")
    @classmethod
    def strong_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters.")
        return value

    def url_for(self, database: str) -> str:
        password = quote_plus(self.db_password.get_secret_value())
        return f"postgresql+psycopg://{quote_plus(self.db_user)}:{password}@{self.db_host}:{self.db_port}/{database}"

    @property
    def database_url(self) -> str:
        return self.database_url_override or self.url_for(self.db_name)

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
