from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # App
    APP_ENV: str = "development"
    SECRET_KEY: str
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]

    # Database
    DB_HOST: str | None = None
    DB_PORT: int | None = 5432
    DB_USER: str | None
    DB_PASSWORD: str | None
    DB_NAME: str | None
    RAW_DATABASE_URL: str | None = None

    @property
    def DATABASE_URL(self) -> str:
        if self.RAW_DATABASE_URL:
            return self.RAW_DATABASE_URL.replace(
                "postgresql://", "postgresql+asyncpg://"
            )
        if not all(
            [self.DB_HOST, self.DB_PORT, self.DB_USER, self.DB_PASSWORD, self.DB_NAME]
        ):
            raise ValueError("Database configuration is incomplete.")
        return (
            f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str | None = None
    RAW_REDIS_URL: str | None = None

    @property
    def REDIS_URL(self) -> str:
        if self.RAW_REDIS_URL:
            return self.RAW_REDIS_URL
        if self.REDIS_PASSWORD:
            return (
                f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/0"
            )
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/0"

    # JWT
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    NOMBA_SANDBOX_URL: str = "https://sandbox.api.nomba.com/v1"
    NOMBA_PRODUCTION_URL: str = "https://api.nomba.com/v1"

    @property
    def NOMBA_BASE_URL(self) -> str:
        if self.APP_ENV == "production":
            return self.NOMBA_PRODUCTION_URL
        return self.NOMBA_SANDBOX_URL

    # Nomba
    NOMBA_CLIENT_ID: str
    NOMBA_CLIENT_SECRET: str
    NOMBA_ACCOUNT_ID: str
    NOMBA_WEBHOOK_SECRET: str

    # Email (Resend)
    RESEND_API_KEY: str | None = None
    EMAIL_FROM: str = "notifications@settle.ng"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
