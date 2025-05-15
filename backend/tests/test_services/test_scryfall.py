# -*- coding: utf-8 -*-
import pytest
from unittest.mock import patch, MagicMock, mock_open, call
import mtg_commander_picker.services.scryfall as scryfall_module
import requests
import os
import json

@pytest.fixture
def mock_settings():
    settings = MagicMock()
    settings.IMAGE_CACHE_DIR = "/tmp/test_images"
    settings.PLACEHOLDER_IMAGE_URL = "/images/placeholder.jpg"
    settings.SCRYFALL_RETRY_TOTAL = 3
    settings.SCRYFALL_BACKOFF_FACTOR = 1.0
    settings.SCRYFALL_STATUS_FORCELIST = [429, 500, 502, 503, 504]
    return settings

@pytest.fixture(autouse=True)
def mock_session():
    """Fixture to mock the scryfall_session and its methods."""
    with patch("mtg_commander_picker.services.scryfall.scryfall_session") as mock_sess:
        yield mock_sess

def test_ensure_image_cache_dir_exists_creates_dir(mock_settings):
    """Test that ensure_image_cache_dir_exists creates the directory if it doesn't exist."""
    with patch("mtg_commander_picker.services.scryfall.get_settings", return_value=mock_settings), \
         patch("os.path.exists", return_value=False) as mock_exists, \
         patch("os.makedirs") as mock_makedirs, \
         patch.object(scryfall_module.app_logger, "info") as mock_info:

        scryfall_module.ensure_image_cache_dir_exists()

        mock_exists.assert_called_once_with(mock_settings.IMAGE_CACHE_DIR)
        mock_makedirs.assert_called_once_with(mock_settings.IMAGE_CACHE_DIR)
        mock_info.assert_called_once_with(f"Created image cache directory: {mock_settings.IMAGE_CACHE_DIR}")

def test_ensure_image_cache_dir_exists_handles_os_error(mock_settings):
    """Test that ensure_image_cache_dir_exists handles OSError during directory creation."""
    with patch("mtg_commander_picker.services.scryfall.get_settings", return_value=mock_settings), \
         patch("os.path.exists", return_value=False) as mock_exists, \
         patch("os.makedirs", side_effect=OSError("Permission denied")) as mock_makedirs, \
         patch.object(scryfall_module.app_logger, "error") as mock_error:

        scryfall_module.ensure_image_cache_dir_exists()

        mock_exists.assert_called_once_with(mock_settings.IMAGE_CACHE_DIR)
        mock_makedirs.assert_called_once_with(mock_settings.IMAGE_CACHE_DIR)
        mock_error.assert_called_once_with(f"Error creating image cache directory {mock_settings.IMAGE_CACHE_DIR}: Permission denied")


def test_get_retry_strategy_with_settings(mock_settings):
    """Test that get_retry_strategy uses settings when available."""
    with patch("mtg_commander_picker.services.scryfall.get_settings", return_value=mock_settings), \
         patch("mtg_commander_picker.services.scryfall.Retry") as mock_retry, \
         patch.object(scryfall_module.app_logger, "info") as mock_info:

        scryfall_module.get_retry_strategy()

        mock_retry.assert_called_once_with(
            total=mock_settings.SCRYFALL_RETRY_TOTAL,
            backoff_factor=mock_settings.SCRYFALL_BACKOFF_FACTOR,
            status_forcelist=mock_settings.SCRYFALL_STATUS_FORCELIST,
            allowed_methods=["HEAD", "GET", "OPTIONS"]
        )
        # Check if info is called, specific message can be checked if needed
        mock_info.assert_called_once()


def test_create_slug_non_string_input():
    """Test create_slug with non-string input."""
    with patch.object(scryfall_module.app_logger, "warning") as mock_warning:
        result = scryfall_module.create_slug(12345)
        assert result == ""
        mock_warning.assert_called_once_with("Attempted to create slug from non-string type: <class 'int'>")


def test_fetch_scryfall_image_uri_empty_card_name(mock_settings):
    """Test fetch_scryfall_image_uri with an empty card name."""
    with patch("mtg_commander_picker.services.scryfall.get_settings", return_value=mock_settings), \
         patch.object(scryfall_module.app_logger, "warning") as mock_warning:
        result = scryfall_module.fetch_scryfall_image_uri("")
        assert result == mock_settings.PLACEHOLDER_IMAGE_URL
        mock_warning.assert_called_once_with("Attempted to fetch Scryfall URI with empty card name.")


def test_fetch_scryfall_image_uri_no_image_uris_in_response(mock_settings, mock_session):
    """Test fetch_scryfall_image_uri when the response has no image_uris."""
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {"object": "card", "name": "Test Card"} # No image_uris or card_faces
    mock_session.get.return_value = mock_response

    with patch("mtg_commander_picker.services.scryfall.get_settings", return_value=mock_settings), \
         patch.object(scryfall_module.app_logger, "warning") as mock_warning:
        result = scryfall_module.fetch_scryfall_image_uri("Test Card")
        assert result == ""
        # The warning message includes the keys of the uris dictionary, which is empty here.
        # The actual code logs 'None' if uris is None or empty, so we expect 'None'.
        mock_warning.assert_called_once_with("No image URI found in Scryfall response for 'Test Card'. Response keys: None")


def test_fetch_scryfall_image_uri_timeout(mock_settings, mock_session):
    """Test fetch_scryfall_image_uri handles timeout."""
    mock_session.get.side_effect = requests.exceptions.Timeout("Request timed out")

    with patch("mtg_commander_picker.services.scryfall.get_settings", return_value=mock_settings), \
         patch.object(scryfall_module.app_logger, "error") as mock_error:
        result = scryfall_module.fetch_scryfall_image_uri("Test Card")
        assert result == mock_settings.PLACEHOLDER_IMAGE_URL
        mock_error.assert_called_once_with("Scryfall API request timed out for 'Test Card'.")


def test_fetch_scryfall_image_uri_request_exception(mock_settings, mock_session):
    """Test fetch_scryfall_image_uri handles RequestException."""
    mock_session.get.side_effect = requests.exceptions.RequestException("Connection error")

    with patch("mtg_commander_picker.services.scryfall.get_settings", return_value=mock_settings), \
         patch.object(scryfall_module.app_logger, "error") as mock_error:
        result = scryfall_module.fetch_scryfall_image_uri("Test Card")
        assert result == mock_settings.PLACEHOLDER_IMAGE_URL
        mock_error.assert_called_once_with("Scryfall API request error for 'Test Card': Connection error")

def test_fetch_scryfall_image_uri_json_decode_error(mock_settings, mock_session):
    """Test fetch_scryfall_image_uri handles JSONDecodeError."""
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.side_effect = json.JSONDecodeError("Invalid JSON", "doc", 0)
    mock_session.get.return_value = mock_response

    with patch("mtg_commander_picker.services.scryfall.get_settings", return_value=mock_settings), \
         patch.object(scryfall_module.app_logger, "error") as mock_error:
        result = scryfall_module.fetch_scryfall_image_uri("Test Card")
        assert result == mock_settings.PLACEHOLDER_IMAGE_URL
        mock_error.assert_called_once_with("Failed to decode JSON response from Scryfall for 'Test Card'.")


def test_fetch_scryfall_image_uri_unexpected_exception(mock_settings, mock_session):
    """Test fetch_scryfall_image_uri handles an unexpected Exception."""
    mock_session.get.side_effect = Exception("Unexpected error")

    with patch("mtg_commander_picker.services.scryfall.get_settings", return_value=mock_settings), \
         patch.object(scryfall_module.app_logger, "error") as mock_error:
        result = scryfall_module.fetch_scryfall_image_uri("Test Card")
        # Corrected assertion to use the actual placeholder URL string
        assert result == "/images/placeholder.jpg"
        mock_error.assert_called_once_with("An unexpected error occurred fetching Scryfall URI for 'Test Card': Unexpected error")


def test_fetch_image_url_empty_card_name(mock_settings):
    """Test fetch_image_url with an empty card name."""
    with patch("mtg_commander_picker.services.scryfall.get_settings", return_value=mock_settings), \
         patch.object(scryfall_module.app_logger, "warning") as mock_warning, \
         patch("mtg_commander_picker.services.scryfall.ensure_image_cache_dir_exists"):
        result = scryfall_module.fetch_image_url("")
        assert result == mock_settings.PLACEHOLDER_IMAGE_URL
        mock_warning.assert_called_once_with("Attempted to fetch image URL for empty card name.")


def test_fetch_image_url_slug_creation_fails(mock_settings):
    """Test fetch_image_url when slug creation returns empty string."""
    with patch("mtg_commander_picker.services.scryfall.get_settings", return_value=mock_settings), \
         patch("mtg_commander_picker.services.scryfall.create_slug", return_value="") as mock_create_slug, \
         patch.object(scryfall_module.app_logger, "warning") as mock_warning, \
         patch("mtg_commander_picker.services.scryfall.ensure_image_cache_dir_exists"):

        card_name = "Card Name"
        result = scryfall_module.fetch_image_url(card_name)

        mock_create_slug.assert_called_once_with(card_name)
        assert result == mock_settings.PLACEHOLDER_IMAGE_URL
        mock_warning.assert_called_once_with(f"Could not create slug for card name '{card_name}'.")


def test_fetch_image_url_caching_request_exception(mock_settings, mock_session):
    """Test fetch_image_url handles RequestException during caching."""
    mock_image_uri = "https://example.com/image.jpg"
    card_name = "Test Card" # Define card_name here
    with patch("mtg_commander_picker.services.scryfall.get_settings", return_value=mock_settings), \
         patch("os.path.exists", return_value=False), \
         patch("mtg_commander_picker.services.scryfall.fetch_scryfall_image_uri", return_value=mock_image_uri), \
         patch("mtg_commander_picker.services.scryfall.ensure_image_cache_dir_exists"), \
         patch("mtg_commander_picker.services.scryfall.create_slug", return_value="test_card"), \
         patch.object(scryfall_module.app_logger, "error") as mock_error:

        mock_session.get.side_effect = requests.exceptions.RequestException("Caching failed")

        result = scryfall_module.fetch_image_url(card_name)

        assert result == mock_settings.PLACEHOLDER_IMAGE_URL
        mock_error.assert_called_once_with(f"Failed to lazy-cache '{card_name}' from {mock_image_uri}: Caching failed")


def test_fetch_image_url_caching_io_error(mock_settings, mock_session):
    """Test fetch_image_url handles IOError during caching."""
    mock_image_uri = "https://example.com/image.jpg"
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.headers = {'Content-Type': 'image/jpeg'}
    # iter_content returns a generator, so we need to mock its behavior
    mock_response.iter_content.return_value = iter([b"image_data"])
    mock_session.get.return_value = mock_response

    # mock_open returns a file handle mock, set side_effect on its write method
    mock_file_handle = MagicMock()
    mock_file_handle.write.side_effect = IOError("Disk full")
    m_open = mock_open()
    m_open.return_value.__enter__.return_value = mock_file_handle


    with patch("mtg_commander_picker.services.scryfall.get_settings", return_value=mock_settings), \
         patch("os.path.exists", return_value=False), \
         patch("mtg_commander_picker.services.scryfall.fetch_scryfall_image_uri", return_value=mock_image_uri), \
         patch("mtg_commander_picker.services.scryfall.ensure_image_cache_dir_exists"), \
         patch("mtg_commander_picker.services.scryfall.create_slug", return_value="test_card"), \
         patch("builtins.open", m_open) as mock_file, \
         patch.object(scryfall_module.app_logger, "error") as mock_error:

        result = scryfall_module.fetch_image_url("Test Card")

        assert result == mock_settings.PLACEHOLDER_IMAGE_URL
        mock_error.assert_called_once_with(f"Failed to write lazy-cached image file for 'Test Card' to {mock_settings.IMAGE_CACHE_DIR}/test_card.jpg: Disk full")


def test_fetch_image_url_caching_unexpected_exception(mock_settings, mock_session):
    """Test fetch_image_url handles an unexpected Exception during caching."""
    mock_image_uri = "https://example.com/image.jpg"
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.headers = {'Content-Type': 'image/jpeg'}
    mock_response.iter_content.side_effect = Exception("Unexpected caching error")
    mock_session.get.return_value = mock_response

    with patch("mtg_commander_picker.services.scryfall.get_settings", return_value=mock_settings), \
         patch("os.path.exists", return_value=False), \
         patch("mtg_commander_picker.services.scryfall.fetch_scryfall_image_uri", return_value=mock_image_uri), \
         patch("mtg_commander_picker.services.scryfall.ensure_image_cache_dir_exists"), \
         patch("mtg_commander_picker.services.scryfall.create_slug", return_value="test_card"), \
         patch("builtins.open", mock_open()) as mock_file, \
         patch.object(scryfall_module.app_logger, "error") as mock_error:

        result = scryfall_module.fetch_image_url("Test Card")

        assert result == mock_settings.PLACEHOLDER_IMAGE_URL
        mock_error.assert_called_once_with("An unexpected error occurred during lazy-caching for 'Test Card': Unexpected caching error")

def test_fetch_image_url_cached_image_exists(mock_settings):
    """Test fetch_image_url returns cached image URL if file exists."""
    with patch("mtg_commander_picker.services.scryfall.get_settings", return_value=mock_settings), \
         patch("os.path.exists", return_value=True) as mock_exists, \
         patch("mtg_commander_picker.services.scryfall.ensure_image_cache_dir_exists"), \
         patch("mtg_commander_picker.services.scryfall.create_slug", return_value="test_card") as mock_create_slug, \
         patch.object(scryfall_module.app_logger, "debug") as mock_debug:

        card_name = "Test Card"
        result = scryfall_module.fetch_image_url(card_name)

        mock_create_slug.assert_called_once_with(card_name)
        mock_exists.assert_called_once_with(os.path.join(mock_settings.IMAGE_CACHE_DIR, "test_card.jpg"))
        assert result == "/images/test_card.jpg"
        mock_debug.assert_called_once_with(f"Serving cached image for '{card_name}' from {mock_settings.IMAGE_CACHE_DIR}/test_card.jpg")

def test_fetch_image_url_fetches_and_caches(mock_settings, mock_session):
    """Test fetch_image_url fetches and caches the image if not exists."""
    mock_image_uri = "https://example.com/image.jpg"
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.headers = {'Content-Type': 'image/jpeg'}
    # iter_content returns a generator, so we need to mock its behavior
    mock_response.iter_content.return_value = iter([b"chunk1", b"chunk2"])
    mock_session.get.return_value = mock_response

    m_open = mock_open()

    with patch("mtg_commander_picker.services.scryfall.get_settings", return_value=mock_settings), \
         patch("os.path.exists", return_value=False), \
         patch("mtg_commander_picker.services.scryfall.fetch_scryfall_image_uri", return_value=mock_image_uri) as mock_fetch_uri, \
         patch("mtg_commander_picker.services.scryfall.ensure_image_cache_dir_exists"), \
         patch("mtg_commander_picker.services.scryfall.create_slug", return_value="test_card") as mock_create_slug, \
         patch("builtins.open", m_open) as mock_file, \
         patch.object(scryfall_module.app_logger, "info") as mock_info:

        card_name = "Test Card"
        result = scryfall_module.fetch_image_url(card_name)

        mock_create_slug.assert_called_once_with(card_name)
        mock_fetch_uri.assert_called_once_with(card_name)
        mock_session.get.assert_called_once_with(mock_image_uri, timeout=15, stream=True)
        m_open.assert_called_once_with(os.path.join(mock_settings.IMAGE_CACHE_DIR, "test_card.jpg"), 'wb')
        mock_file().write.assert_has_calls([call(b"chunk1"), call(b"chunk2")])
        assert result == "/images/test_card.jpg"
        mock_info.assert_any_call(f"Lazy-caching image for '{card_name}' from {mock_image_uri}")
        mock_info.assert_any_call(f"Successfully cached image for '{card_name}' to {mock_settings.IMAGE_CACHE_DIR}/test_card.jpg")

def test_fetch_image_url_caching_non_image_content_type(mock_settings, mock_session):
    """Test fetch_image_url handles non-image content type during caching."""
    mock_image_uri = "https://example.com/not_an_image"
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.headers = {'Content-Type': 'text/html'} # Not an image
    # iter_content returns a generator, so we need to mock its behavior
    mock_response.iter_content.return_value = iter([b"html_data"])
    mock_session.get.return_value = mock_response

    with patch("mtg_commander_picker.services.scryfall.get_settings", return_value=mock_settings), \
         patch("os.path.exists", return_value=False), \
         patch("mtg_commander_picker.services.scryfall.fetch_scryfall_image_uri", return_value=mock_image_uri), \
         patch("mtg_commander_picker.services.scryfall.ensure_image_cache_dir_exists"), \
         patch("mtg_commander_picker.services.scryfall.create_slug", return_value="test_card"), \
         patch.object(scryfall_module.app_logger, "warning") as mock_warning:

        result = scryfall_module.fetch_image_url("Test Card")

        mock_session.get.assert_called_once_with(mock_image_uri, timeout=15, stream=True)
        assert result == mock_settings.PLACEHOLDER_IMAGE_URL
        mock_warning.assert_called_once_with(
            f"Downloaded content for 'Test Card' from {mock_image_uri} is not an image. Content-Type: text/html")

def test_fetch_scryfall_image_uri_double_faced_card(mock_settings, mock_session):
    """Test fetch_scryfall_image_uri handles double-faced cards."""
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "object": "card",
        "name": "Double Faced Card",
        "card_faces": [
            {
                "object": "card_face",
                "name": "Face A",
                "image_uris": {
                    "small": "uri_a_small",
                    "normal": "uri_a_normal",
                    "large": "uri_a_large"
                }
            },
            {
                "object": "card_face",
                "name": "Face B",
                "image_uris": {
                    "small": "uri_b_small",
                    "normal": "uri_b_normal",
                    "large": "uri_b_large"
                }
            }
        ]
    }
    mock_session.get.return_value = mock_response

    with patch("mtg_commander_picker.services.scryfall.get_settings", return_value=mock_settings), \
         patch.object(scryfall_module.app_logger, "debug"):

        result = scryfall_module.fetch_scryfall_image_uri("Double Faced Card")
        assert result == "uri_a_normal" # Should pick the normal URI of the first face

def test_fetch_scryfall_image_uri_double_faced_card_no_normal(mock_settings, mock_session):
    """Test fetch_scryfall_image_uri handles double-faced cards with no 'normal' uri on first face."""
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "object": "card",
        "name": "Double Faced Card",
        "card_faces": [
            {
                "object": "card_face",
                "name": "Face A",
                "image_uris": {
                    "small": "uri_a_small",
                    "large": "uri_a_large"
                }
            },
            {
                "object": "card_face",
                "name": "Face B",
                "image_uris": {
                    "small": "uri_b_small",
                    "normal": "uri_b_normal",
                    "large": "uri_b_large"
                }
            }
        ]
    }
    mock_session.get.return_value = mock_response

    with patch("mtg_commander_picker.services.scryfall.get_settings", return_value=mock_settings), \
         patch.object(scryfall_module.app_logger, "debug"):

        result = scryfall_module.fetch_scryfall_image_uri("Double Faced Card")
        assert result == "uri_a_large" # Should fallback to large URI of the first face

def test_fetch_scryfall_image_uri_double_faced_card_only_small(mock_settings, mock_session):
    """Test fetch_scryfall_image_uri handles double-faced cards with only 'small' uri on first face."""
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "object": "card",
        "name": "Double Faced Card",
        "card_faces": [
            {
                "object": "card_face",
                "name": "Face A",
                "image_uris": {
                    "small": "uri_a_small"
                }
            },
            {
                "object": "card_face",
                "name": "Face B",
                "image_uris": {
                    "small": "uri_b_small",
                    "normal": "uri_b_normal",
                    "large": "uri_b_large"
                }
            }
        ]
    }
    mock_session.get.return_value = mock_response

    with patch("mtg_commander_picker.services.scryfall.get_settings", return_value=mock_settings), \
         patch.object(scryfall_module.app_logger, "debug"):

        result = scryfall_module.fetch_scryfall_image_uri("Double Faced Card")
        assert result == "uri_a_small" # Should fallback to small URI of the first face

def test_fetch_scryfall_image_uri_double_faced_card_no_image_uris_on_face(mock_settings, mock_session):
    """Test fetch_scryfall_image_uri handles double-faced cards with no image_uris on first face."""
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "object": "card",
        "name": "Double Faced Card",
        "card_faces": [
            {
                "object": "card_face",
                "name": "Face A",
                "image_uris": {} # Empty image_uris
            },
            {
                "object": "card_face",
                "name": "Face B",
                "image_uris": {
                    "small": "uri_b_small",
                    "normal": "uri_b_normal",
                    "large": "uri_b_large"
                }
            }
        ]
    }
    mock_session.get.return_value = mock_response

    with patch("mtg_commander_picker.services.scryfall.get_settings", return_value=mock_settings), \
         patch.object(scryfall_module.app_logger, "debug"), \
         patch.object(scryfall_module.app_logger, "warning") as mock_warning:

        result = scryfall_module.fetch_scryfall_image_uri("Double Faced Card")
        assert result == "" # Should return empty string as no usable URI on first face
        # Updated assertion to match the actual logged message when uris is an empty dict
        mock_warning.assert_called_once_with(
            "No image URI found in Scryfall response for 'Double Faced Card'. Response keys: None")


def test_fetch_image_url_success(mock_settings):
    """Test fetch_image_url successfully fetches and returns the image URL."""
    with patch("mtg_commander_picker.services.scryfall.get_settings", return_value=mock_settings), \
         patch("os.path.exists", return_value=False), \
         patch("builtins.open", create=True), \
         patch("pathlib.Path.mkdir"), \
         patch("mtg_commander_picker.services.scryfall.fetch_scryfall_image_uri", return_value="https://example.com/image.jpg"), \
         patch.object(scryfall_module.scryfall_session, "get") as mock_get:

        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.headers = {'Content-Type': 'image/jpeg'}
        # iter_content returns a generator, so we need to mock its behavior
        mock_response.iter_content.return_value = iter([b"chunk1", b"chunk2"])
        mock_get.return_value = mock_response

        result = scryfall_module.fetch_image_url("Lightning Bolt")

    assert result == "/images/lightning_bolt.jpg"



def test_fetch_image_url_fallbacks_to_placeholder(mock_settings):
    """Test fetch_image_url falls back to placeholder if fetch_scryfall_image_uri returns empty."""
    with patch("mtg_commander_picker.services.scryfall.get_settings", return_value=mock_settings), \
         patch("os.path.exists", return_value=False), \
         patch("mtg_commander_picker.services.scryfall.fetch_scryfall_image_uri", return_value=""), \
         patch("mtg_commander_picker.services.scryfall.ensure_image_cache_dir_exists"), \
         patch("mtg_commander_picker.services.scryfall.create_slug", return_value="nonexistent_card_12345"), \
         patch.object(scryfall_module.app_logger, "warning") as mock_warning:


        result = scryfall_module.fetch_image_url("Nonexistent Card 12345")

    assert result == mock_settings.PLACEHOLDER_IMAGE_URL
    mock_warning.assert_called_once_with("Could not provide image for card 'Nonexistent Card 12345'. Returning placeholder.")
