import logging
import os
from typing import Set, List

from pydantic import Field, ValidationError, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Set up logging for this module
app_logger = logging.getLogger(__name__)

# Get the absolute path of the directory containing this config file
BACKEND_DIR: str = os.path.dirname(os.path.abspath(__file__))


# --- Custom Exception for Configuration Errors ───────────────────────────────────

class ConfigError(Exception):
    """Custom exception raised for configuration errors."""
    pass


# --- Application Constants ─────────────────────────────────────────────────────
# These are fixed application values, not loaded from environment variables.
COL_CARD_NAME: str = 'Card Name'
COL_COLOR: str = 'Color'
COL_RESERVED: str = 'Reserved'
REQUIRED_COLS: List[str] = [COL_CARD_NAME, COL_COLOR, COL_RESERVED]

VALID_COLORS: Set[str] = {"white", "blue", "black", "red", "green"}

# Default scope for Google Sheets API - also a constant
SCOPE: List[str] = ['https://www.googleapis.com/auth/spreadsheets']


# --- Pydantic Settings (Environment Dependent) ───────────────────────────────────

class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    """

    # Google Sheets Configuration
    GOOGLE_SHEET_ID: str = Field(..., description="The ID of the Google Sheet.")
    GOOGLE_SHEETS_CREDENTIALS_JSON: SecretStr = Field(...,
        description="Google Sheets service account credentials JSON.")

    # Cache Configuration
    SHEET_CACHE_TTL_SECONDS: int = Field(
        300, description="TTL for Google Sheet data cache in seconds."
    )

    # Image Cache Directory
    IMAGE_CACHE_DIR: str = Field(
        os.path.join(BACKEND_DIR, 'image_cache'),
        description="Directory to cache images."
    )

    # Placeholder image URL
    PLACEHOLDER_IMAGE_URL: str = "/images/placeholder.jpg"

    # Application Configuration
    MAX_RESERVATIONS_PER_USER: int = Field(
        5, description="Maximum number of reservations allowed per user."
    )

    # Scryfall Retry Configuration
    SCRYFALL_RETRY_TOTAL: int = Field(
        3, description="Total number of retries for failed Scryfall API requests."
    )
    SCRYFALL_BACKOFF_FACTOR: float = Field(
        1.0, description="Backoff factor for exponential delay between retries."
    )
    SCRYFALL_STATUS_FORCELIST: List[int] = Field(
        [429, 500, 502, 503, 504],
        description="HTTP status codes that should trigger a retry."
    )

    # Development Mode
    DEV_MODE: bool = Field(
        False, description="Enable development mode (e.g., Flask debug server)."
    )

    # Pydantic config
    model_config = SettingsConfigDict(
        env_file='.env',  # You can override this in your test config
        env_file_encoding='utf-8',
        case_sensitive=False
    )


# --- Lazy Settings Loader ─────────────────────────────────────────────────────

_settings_instance = None

def get_settings() -> Settings:
    global _settings_instance

    if _settings_instance is not None:
        return _settings_instance

    try:
        _settings_instance = Settings()
        app_logger.info("Configuration loaded and validated successfully.")
    except ValidationError as e:
        app_logger.error(f"Configuration validation error: {e}")
        raise ConfigError("Application failed to start due to configuration errors.") from e

    # Log safe config values
    app_logger.info(f"Using MAX_RESERVATIONS_PER_USER: {_settings_instance.MAX_RESERVATIONS_PER_USER}")
    app_logger.info(f"Using IMAGE_CACHE_DIR: {_settings_instance.IMAGE_CACHE_DIR}")
    app_logger.info(f"Using SHEET_CACHE_TTL_SECONDS: {_settings_instance.SHEET_CACHE_TTL_SECONDS}")
    app_logger.info(f"Using GOOGLE_SHEET_ID: {_settings_instance.GOOGLE_SHEET_ID}")
    app_logger.info(f"Scryfall Retry Total: {_settings_instance.SCRYFALL_RETRY_TOTAL}")
    app_logger.info(f"Scryfall Backoff Factor: {_settings_instance.SCRYFALL_BACKOFF_FACTOR}")
    app_logger.info(f"Scryfall Status Forcelist: {_settings_instance.SCRYFALL_STATUS_FORCELIST}")
    app_logger.info(f"Development Mode (DEV_MODE): {_settings_instance.DEV_MODE}")

    return _settings_instance
