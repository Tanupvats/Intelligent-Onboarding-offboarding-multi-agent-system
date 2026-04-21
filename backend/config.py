

from __future__ import annotations

import os
from functools import lru_cache
from typing import List, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration for backend + MCP subprocesses."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # don't fail on unknown env vars
    )

    # --- App ---------------------------------------------------------------
    APP_ENV: Literal["dev", "staging", "prod"] = "dev"
    APP_NAME: str = "Intelligent Onboarding/Offboarding MAS"
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    LOG_JSON: bool = True  # structured logs; flip to False for human-readable dev logs

    # --- Auth / sessions ---------------------------------------------------
    # Must be set in production. We enforce this in APP_ENV=prod.
    JWT_SECRET: str = Field(default="dev-only-change-me-" + "x" * 24, min_length=32)
    JWT_ALG: str = "HS256"
    JWT_EXPIRES_HOURS: int = 8

    # --- CORS --------------------------------------------------------------
    # Comma-separated list. Default covers the three local Streamlit ports.
    CORS_ALLOW_ORIGINS: str = "http://localhost:8501,http://localhost:8502,http://localhost:8503"
    CORS_ALLOW_CREDENTIALS: bool = True

    # --- Data paths --------------------------------------------------------
    DATA_DIR: str = "data"
    UPLOADS_DIR: str = "uploads"

    USERS_CSV: str = "data/users.csv"
    EMPLOYEES_CSV: str = "data/employees.csv"
    TICKETS_CSV: str = "data/ticket.csv"

    # --- Uploads -----------------------------------------------------------
    MAX_UPLOAD_MB: int = 10
    ALLOWED_UPLOAD_EXTS: str = "pdf,jpg,jpeg,png"

    # --- MCP ---------------------------------------------------------------
    MCP_FS_COMMAND: str = "python"
    MCP_FS_ARGS: str = "servers/fs_server.py"
    MCP_EMAIL_COMMAND: str = "python"
    MCP_EMAIL_ARGS: str = "servers/email_server.py"
    MCP_TICKET_MIRROR: str = "data/tickets_mirror.jsonl"

    # Filesystem MCP: paths (comma-separated) that the fs subprocess may read/write.
    FS_ALLOWED_DIRS: str = "./uploads,./data"
    # Maximum file size the fs MCP will write (bytes). Cheap DoS protection.
    FS_MAX_BYTES: int = 25 * 1024 * 1024  # 25 MB

    # --- Email (used by email MCP subprocess) -----------------------------
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    SMTP_STARTTLS: bool = True
    SMTP_TIMEOUT: int = 15

    # --- LLM / agents ------------------------------------------------------
    OLLAMA_MODEL: str = "llama3.2"

    # --- LangSmith ---------------------------------------------------------
    LANGCHAIN_TRACING_V2: bool = False
    LANGCHAIN_ENDPOINT: str = "https://api.smith.langchain.com"
    LANGCHAIN_API_KEY: str = ""
    LANGCHAIN_PROJECT: str = "hr-multi-agent-system"

    # --- Derived helpers --------------------------------------------------

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ALLOW_ORIGINS.split(",") if o.strip()]

    @property
    def allowed_upload_exts_set(self) -> set[str]:
        return {e.strip().lower().lstrip(".") for e in self.ALLOWED_UPLOAD_EXTS.split(",") if e.strip()}

    @property
    def smtp_from_effective(self) -> str:
        return self.SMTP_FROM or self.SMTP_USER or "no-reply@example.com"

    @property
    def is_prod(self) -> bool:
        return self.APP_ENV == "prod"

    # --- Validation -------------------------------------------------------

    @field_validator("JWT_SECRET")
    @classmethod
    def _jwt_secret_strength(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters.")
        return v


@lru_cache
def get_settings() -> Settings:
    """
    Cached settings accessor. Use this everywhere instead of re-instantiating.

    In production (APP_ENV=prod) we require that JWT_SECRET is NOT the default
    development value — refuse to start otherwise.
    """
    s = Settings()
    if s.is_prod and s.JWT_SECRET.startswith("dev-only-change-me-"):
        raise RuntimeError(
            "Refusing to start in APP_ENV=prod with the default JWT_SECRET. "
            "Set JWT_SECRET via your secrets manager."
        )
    if s.is_prod and not s.SMTP_USER:
        # Warn rather than fail — the email feature is optional
        import warnings
        warnings.warn("SMTP_USER is not set; email notifications will fail.", stacklevel=2)
    return s
