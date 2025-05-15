from unittest.mock import patch, MagicMock
import pytest
import mtg_commander_picker.config as config_module
import json


@pytest.fixture(scope="module")
def mock_settings():
    dummy_credentials = {
        "type": "service_account",
        "client_email": "test@example.com",
        "token_uri": "https://oauth2.googleapis.com/token",
        "private_key": "-----BEGIN PRIVATE KEY-----\nFAKEKEYBASE64==\n-----END PRIVATE KEY-----\n"
    }

    mock = MagicMock()
    mock.GOOGLE_SHEET_ID = "dummy_sheet_id"
    mock.GOOGLE_SHEETS_CREDENTIALS_JSON.get_secret_value.return_value = json.dumps(dummy_credentials)
    mock.IMAGE_CACHE_DIR = "/tmp/test_images"
    mock.MAX_RESERVATIONS_PER_USER = 1
    mock.SHEET_CACHE_TTL_SECONDS = 300
    mock.DEV_MODE = True
    mock.SCRYFALL_RETRY_TOTAL = 3
    mock.SCRYFALL_BACKOFF_FACTOR = 1.0
    mock.SCRYFALL_STATUS_FORCELIST = [429, 500, 502, 503, 504]
    mock.PLACEHOLDER_IMAGE_URL = "/images/placeholder.jpg"
    return mock


@pytest.fixture(autouse=True)
def mock_google_sheets():
    with patch("mtg_commander_picker.services.google_sheets_service.initialize", return_value=None), \
         patch("google.oauth2.service_account.Credentials.from_service_account_info"), \
         patch("gspread.authorize"):
        yield


def pytest_sessionstart():
    config_module._settings_instance = None
