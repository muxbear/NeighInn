from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """统一服务端配置。所有密钥经环境变量注入，禁止提交真实值。"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Neighbor's Inn Platform API"
    app_env: str = "dev"
    app_host: str = "127.0.0.1"
    app_port: int = 5193
    debug: bool = True
    secret_key: str = "dev-only-change-me-please-32bytes-min"

    # ---- 日志 ----
    # DEBUG 仅作为调试标记保留；SQL 日志由 SQL_ECHO 独立控制，避免开发默认刷屏。
    log_level: str = "INFO"
    log_format: str = "console"  # console（开发）| json（生产采集）
    log_to_file: bool = False  # 生产建议 false，仅输出 stdout
    log_dir: str = "logs"
    log_max_bytes: int = 10 * 1024 * 1024
    log_backup_count: int = 5
    sql_echo: bool = False
    access_log_enabled: bool = True
    slow_request_ms: int = 2000
    access_log_skip_paths: str = "/health/live,/health/ready,/favicon.ico"

    database_url: str = "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/neighinn_platform"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    redis_url: str = ""
    # 短信验证码存储后端：memory（进程内，重启失效）| redis（重启/多副本不丢）。
    sms_code_backend: str = "memory"
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
    auth_require_2fa: bool = True
    auth_enforce_csrf: bool = True
    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:5191,http://127.0.0.1:5191,"
        "http://localhost:5192,http://127.0.0.1:5192"
    )
    # 开发环境额外允许的跨域来源正则（私网 IP 的移动端 H5）；生产环境不生效。
    cors_origin_regex: str = ""

    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 120
    refresh_token_ttl_days: int = 30

    # 进程内调度（开发）：Outbox 继电器 + 超时任务；生产替换为 Celery/Arq
    enable_scheduler: bool = True
    outbox_interval_seconds: int = 5
    timeout_interval_seconds: int = 60

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def access_log_skip_path_set(self) -> set[str]:
        return {item.strip() for item in self.access_log_skip_paths.split(",") if item.strip()}

    # ---- 业务规则默认值（运行时以 parameter_items 参数为准，见 domain/enums.py） ----
    min_item_images: int = 3
    max_item_images: int = 12
    item_expire_days: int = 30
    pay_timeout_minutes: int = 30
    auto_release_hours: int = 72
    confirm_timeout_hours: int = 48
    nearby_radius_km: float = 3.0
    nearby_max_count: int = 10
    withdrawal_dual_review_threshold_cents: int = 500_000
    ai_fast_track_confidence: float = 0.95
    friend_max_count: int = 500


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
