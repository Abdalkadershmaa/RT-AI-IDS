import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    secret_key: str
    jwt_secret_key: str
    database_url: str
    redis_url: str
    ingest_queue: str
    inference_queue: str
    alert_cache_ttl_seconds: int
    admin_username: str
    admin_password: str
    log_level: str


def get_settings() -> Settings:
    return Settings(
        secret_key=os.getenv("SECRET_KEY", "change-me-in-production"),
        jwt_secret_key=os.getenv("JWT_SECRET_KEY", "change-me-in-production"),
        database_url=os.getenv("DATABASE_URL", "sqlite:///ids.db"),
        redis_url=os.getenv("REDIS_URL", "redis://redis:6379/0"),
        ingest_queue=os.getenv("INGEST_QUEUE", "packet_ingest"),
        inference_queue=os.getenv("INFERENCE_QUEUE", "inference"),
        alert_cache_ttl_seconds=int(os.getenv("ALERT_CACHE_TTL_SECONDS", "300")),
        admin_username=os.getenv("ADMIN_USERNAME", "admin"),
        admin_password=os.getenv("ADMIN_PASSWORD", "admin"),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
    )

