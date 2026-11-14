from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Neighbor's Inn Admin API"
    app_env: str = "dev"
    debug: bool = True
    secret_key: str = "dev-only-change-me-please-32bytes-min"

    database_url: str = "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/neighinn_dev"
    redis_url: str = ""
    rabbitmq_url: str = ""

    minio_endpoint: str = "127.0.0.1:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_secure: bool = False
    minio_region: str = ""
    minio_bucket_public: str = "ni-public"
    minio_bucket_private: str = "ni-private"
    minio_bucket_system: str = "ni-system"

    session_cookie_name: str = "ni_admin_session"
    session_ttl_minutes: int = 480
    auth_require_2fa: bool = False
    auth_enforce_csrf: bool = True
    cors_origins: str = "http://localhost:5192,http://127.0.0.1:5192"

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
