import os

try:
    from pydantic_settings import BaseSettings
except ImportError:
    try:
        from pydantic import BaseSettings
    except ImportError:
        class BaseSettings:
            def __init__(self, **kwargs):
                for k, v in kwargs.items():
                    setattr(self, k, v)

from typing import Optional

class Settings(BaseSettings):
    APP_NAME: str = "Agni API Gateway"
    ENV: str = os.getenv("ENV", "development")
    PORT: int = int(os.getenv("PORT", "8000"))
    HOST: str = os.getenv("HOST", "0.0.0.0")

    # Database
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", 
        "postgresql+asyncpg://agni:agni_secret@localhost:5432/agni_db"
    )

    # Redis (Dockerized)
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    # Security & Ed25519 Keys
    ED25519_PRIVATE_KEY_PEM: Optional[str] = os.getenv("ED25519_PRIVATE_KEY_PEM", None)
    ED25519_PUBLIC_KEY_PEM: Optional[str] = os.getenv("ED25519_PUBLIC_KEY_PEM", None)
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    TOKEN_FAMILY_GRACE_PERIOD_SECONDS: int = 30

    # Device Auth Flow (RFC 8628)
    DEVICE_CODE_EXPIRE_SECONDS: int = 300
    DEVICE_POLL_INTERVAL_SECONDS: int = 2
    FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:3000")

    class Config:
        env_file = ".env"
        extra = "allow"

settings = Settings()
