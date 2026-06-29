"""
config.py — Pydantic Settings for Face Auth API
================================================
Reads all configuration from environment variables / .env file.
Add new settings here — never use os.getenv() directly in main.py.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict  # pyright: ignore[reportMissingImports]
from pydantic import field_validator # type: ignore


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../../.env", ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Auth ──────────────────────────────────────────────────
    # Supports both SECRET_KEY (new) and FASTAPI_SECRET_KEY (legacy)
    SECRET_KEY: str = ""
    FASTAPI_SECRET_KEY: str = ""
    # ── Admin Auth ────────────────────────────────────────────
    ADMIN_USERNAME: str = "admin_user"
    ADMIN_PASSWORD: str = ""

    @field_validator("ADMIN_USERNAME")
    @classmethod
    def username_must_not_be_predictable(cls, v: str) -> str:
        if v.lower() in ["admin", "root"]:
            raise ValueError("Predictable usernames like 'admin' or 'root' are strictly prohibited.")
        return v

    @property
    def resolved_secret_key(self) -> str:
        """Return whichever key is set, preferring SECRET_KEY."""
        return self.SECRET_KEY or self.FASTAPI_SECRET_KEY

    JWT_EXPIRY_HOURS: int = 2

    # ── Face Matching ─────────────────────────────────────────
    MATCH_TOLERANCE: float = 0.5

    # ── Redis ─────────────────────────────────────────────────
    REDIS_URL: str = "redis://127.0.0.1:6379/0"

    # ── EAR Liveness Thresholds ───────────────────────────────
    # Configurable so narrow-eye demographics aren't falsely rejected.
    # Closed eye typically < 0.21, open eye typically > 0.25.
    EAR_MIN_CLOSED: float = 0.22
    EAR_MIN_OPEN: float = 0.25


settings = Settings()
