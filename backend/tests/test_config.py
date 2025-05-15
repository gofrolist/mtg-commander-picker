import pytest
import os
import json
import logging
from unittest.mock import patch, MagicMock

from mtg_commander_picker import config
from pydantic import ValidationError, SecretStr


# Fixture to clear the settings singleton before each test
@pytest.fixture(autouse=True)
def clear_settings_singleton():
    """Clears the settings singleton instance before each test."""
    yield
    # Reset the singleton instance after the test
    config._settings_instance = None


# Fixture to set minimal required environment variables for tests
@pytest.fixture
def set_minimal_env(monkeypatch):
    """Sets minimal required environment variables for Settings to load."""
    monkeypatch.setenv("GOOGLE_SHEET_ID", "test_sheet_id")
    # Pydantic expects a string for SecretStr, which it then wraps
    monkeypatch.setenv("GOOGLE_SHEETS_CREDENTIALS_JSON", json.dumps({"type": "service_account"}))


# --- ConfigError Tests ---

def test_config_error_exception():
    """Tests the custom ConfigError exception."""
    msg = "This is a config error"
    err = config.ConfigError(msg)
    assert isinstance(err, Exception)
    assert str(err) == msg


# --- Settings Class Tests ---

def test_settings_loads_from_env(monkeypatch, set_minimal_env):
    """Tests that Settings loads values from environment variables."""
    monkeypatch.setenv("SHEET_CACHE_TTL_SECONDS", "120")
    monkeypatch.setenv("MAX_RESERVATIONS_PER_USER", "10")
    monkeypatch.setenv("DEV_MODE", "True")
    monkeypatch.setenv("IMAGE_CACHE_DIR", "/tmp/image_cache")
    monkeypatch.setenv("PLACEHOLDER_IMAGE_URL", "http://example.com/placeholder.jpg")
    monkeypatch.setenv("SCRYFALL_RETRY_TOTAL", "5")
    monkeypatch.setenv("SCRYFALL_BACKOFF_FACTOR", "2.0")
    monkeypatch.setenv("SCRYFALL_STATUS_FORCELIST", "[408, 429, 500]")


    settings = config.Settings()

    assert settings.GOOGLE_SHEET_ID == "test_sheet_id"
    assert isinstance(settings.GOOGLE_SHEETS_CREDENTIALS_JSON, SecretStr)
    assert settings.GOOGLE_SHEETS_CREDENTIALS_JSON.get_secret_value() == json.dumps({"type": "service_account"})
    assert settings.SHEET_CACHE_TTL_SECONDS == 120
    assert settings.MAX_RESERVATIONS_PER_USER == 10
    assert settings.DEV_MODE is True
    assert settings.IMAGE_CACHE_DIR == "/tmp/image_cache"
    assert settings.PLACEHOLDER_IMAGE_URL == "http://example.com/placeholder.jpg"
    assert settings.SCRYFALL_RETRY_TOTAL == 5
    assert settings.SCRYFALL_BACKOFF_FACTOR == 2.0
    assert settings.SCRYFALL_STATUS_FORCELIST == [408, 429, 500]


def test_settings_uses_default_values(monkeypatch, set_minimal_env):
    """Tests that Settings uses default values when env vars are not set."""
    # Only minimal required env vars are set by the fixture

    settings = config.Settings()

    # Check default values
    assert settings.SHEET_CACHE_TTL_SECONDS == 300
    assert settings.MAX_RESERVATIONS_PER_USER == 5
    assert settings.DEV_MODE is False
    # Check default IMAGE_CACHE_DIR which is based on BACKEND_DIR
    assert settings.IMAGE_CACHE_DIR == os.path.join(config.BACKEND_DIR, 'image_cache')
    assert settings.PLACEHOLDER_IMAGE_URL == "/images/placeholder.jpg"
    assert settings.SCRYFALL_RETRY_TOTAL == 3
    assert settings.SCRYFALL_BACKOFF_FACTOR == 1.0
    assert settings.SCRYFALL_STATUS_FORCELIST == [429, 500, 502, 503, 504]


def test_settings_validation_error_missing_required(monkeypatch):
    """Tests that Settings raises ValidationError for missing required env vars."""
    # Do NOT use set_minimal_env fixture
    monkeypatch.delenv("GOOGLE_SHEET_ID", raising=False)
    monkeypatch.delenv("GOOGLE_SHEETS_CREDENTIALS_JSON", raising=False)

    with pytest.raises(ValidationError):
        config.Settings()


def test_settings_validation_error_invalid_type(monkeypatch, set_minimal_env):
    """Tests that Settings raises ValidationError for invalid types."""
    monkeypatch.setenv("SHEET_CACHE_TTL_SECONDS", "not_an_int")

    with pytest.raises(ValidationError):
        config.Settings()


# --- get_settings Function Tests ---

def test_get_settings_loads_and_returns_settings(set_minimal_env):
    """Tests that get_settings loads and returns a Settings instance."""
    settings = config.get_settings()
    assert isinstance(settings, config.Settings)
    assert settings.GOOGLE_SHEET_ID == "test_sheet_id"


def test_get_settings_is_singleton(set_minimal_env):
    """Tests that get_settings returns the same instance on subsequent calls."""
    settings1 = config.get_settings()
    settings2 = config.get_settings()
    assert settings1 is settings2


def test_get_settings_raises_config_error_on_validation_error(monkeypatch):
    """Tests that get_settings wraps ValidationError in ConfigError."""
    # Do NOT use set_minimal_env fixture to force ValidationError
    monkeypatch.delenv("GOOGLE_SHEET_ID", raising=False)
    monkeypatch.delenv("GOOGLE_SHEETS_CREDENTIALS_JSON", raising=False)

    with pytest.raises(config.ConfigError) as exc_info:
        config.get_settings()

    # Check that the original ValidationError is the cause
    assert isinstance(exc_info.value.__cause__, ValidationError)


def test_get_settings_logs_info(set_minimal_env, caplog):
    """Tests that get_settings logs configuration information."""
    # Configure caplog to capture INFO level messages
    caplog.set_level(logging.INFO)

    config.get_settings()

    # Check if expected log messages are present
    assert "Configuration loaded and validated successfully." in caplog.text
    assert "Using MAX_RESERVATIONS_PER_USER: 5" in caplog.text
    assert "Using IMAGE_CACHE_DIR:" in caplog.text # Check for part of the path
    assert "Using SHEET_CACHE_TTL_SECONDS: 300" in caplog.text
    assert "Using GOOGLE_SHEET_ID: test_sheet_id" in caplog.text
    assert "Scryfall Retry Total: 3" in caplog.text
    assert "Scryfall Backoff Factor: 1.0" in caplog.text
    assert "Scryfall Status Forcelist: [429, 500, 502, 503, 504]" in caplog.text
    assert "Development Mode (DEV_MODE): False" in caplog.text


def test_get_settings_logs_error_on_validation_error(monkeypatch, caplog):
    """Tests that get_settings logs an error on ValidationError."""
    # Configure caplog to capture ERROR level messages
    caplog.set_level(logging.ERROR)

    # Do NOT use set_minimal_env fixture to force ValidationError
    monkeypatch.delenv("GOOGLE_SHEET_ID", raising=False)
    monkeypatch.delenv("GOOGLE_SHEETS_CREDENTIALS_JSON", raising=False)

    with pytest.raises(config.ConfigError):
        config.get_settings()

    # Check if the validation error message is logged
    assert "Configuration validation error:" in caplog.text
