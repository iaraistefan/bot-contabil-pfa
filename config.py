"""
Centralized configuration for the PFA accounting bot.

Reads ALL environment variables in one place using pydantic-settings.
Fails fast at startup if required vars are missing.

Usage anywhere in the project:
    from config import settings
    bot = Bot(token=settings.telegram_token)
"""

from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Required: app refuses to start if these are missing ---
    telegram_token: str
    openai_api_key: str

    # --- Optional with sensible defaults ---
    database_url: str = "sqlite:///./data.db"   # Postgres on Render in prod
    openai_model: str = "gpt-4o"
    log_level: str = "INFO"
    env: str = "production"                     # 'production' | 'development'

    # --- Google Sheets (optional — bot starts fine without them) ---
    google_credentials_json: Optional[str] = None
    sheet_id: Optional[str] = None


# Singleton. Import THIS everywhere instead of calling os.getenv.
settings = Settings()
