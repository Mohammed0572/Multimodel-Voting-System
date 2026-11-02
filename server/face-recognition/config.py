"""
config.py — Pydantic Settings for Face Auth API
================================================
Reads all configuration from environment variables / .env file.
Add new settings here — never use os.getenv() directly in main.py.
"""

from pathlib import Path
import os

from pydantic_settings import BaseSettings, SettingsConfigDict  # pyright: ignore[reportMissingImports]
from pydantic import Field, field_validator # type: ignore


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(Path(__file__).resolve().parents[2] / ".env"), str(Path(__file__).resolve().parent / ".env")),
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

    JWT_EXPIRY_HOURS: int = Field(default=2, ge=1, le=24)

    # ── Face Matching ─────────────────────────────────────────
    MATCH_TOLERANCE: float = Field(default=0.55, gt=0, le=0.6)
    FACE_WORKERS: int = Field(default=min(4, os.cpu_count() or 1), ge=1, le=4)
    FACE_PROCESSING_TIMEOUT_SECONDS: int = Field(default=15, ge=5, le=60)

    # ── Redis ─────────────────────────────────────────────────
    REDIS_URL: str = "redis://127.0.0.1:6379/0"
    REQUIRE_REDIS: bool = False
    IMPORT_LEGACY_PICKLE: bool = False
    SEED_DEMO_ROSTER: bool = False
    FACE_DB_PATH: str = ""

    @property
    def resolved_face_db_path(self) -> str:
        # `make backend` runs at repo root, while the demo runs in this folder.
        # Both must see the same enrollments after a restart.
        path = Path(self.FACE_DB_PATH or "face_voter_db.sqlite").expanduser()
        if not path.is_absolute():
            path = Path(__file__).resolve().parent / path
        return str(path.resolve())

    FRONTEND_ORIGINS: str = (
        "http://localhost:8080,http://127.0.0.1:8080,"
        "http://localhost:5173,http://127.0.0.1:5173"
    )
    COOKIE_SECURE: bool = False
    COOKIE_SAMESITE: str = "lax"
    BLOCKCHAIN_RPC_URL: str = "http://127.0.0.1:7545"
    BLOCKCHAIN_CONTRACT_ADDRESS: str = ""
    BLOCKCHAIN_RELAYER_ADDRESS: str = ""
    BLOCKCHAIN_RELAYER_PRIVATE_KEY: str = ""
    VOTING_CREDENTIAL_TTL_MINUTES: int = Field(default=15, ge=1, le=120)
    BLOCKCHAIN_CONFIRMATIONS: int = Field(default=1, ge=1, le=100)

    @field_validator("COOKIE_SAMESITE")
    @classmethod
    def valid_samesite(cls, value: str) -> str:
        if value not in ("lax", "strict", "none"):
            raise ValueError("COOKIE_SAMESITE must be lax, strict or none")
        return value

    @property
    def frontend_origins(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.FRONTEND_ORIGINS.split(",")
            if origin.strip()
        ]

    # ── EAR Liveness Thresholds ───────────────────────────────
    # Configurable so narrow-eye demographics aren't falsely rejected.
    # Closed eye typically < 0.21, open eye typically > 0.25.
    EAR_MIN_CLOSED: float = 0.22
    EAR_MIN_OPEN: float = 0.25


settings = Settings()
