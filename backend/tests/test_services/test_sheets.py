import pytest
import json
import time
import gspread
from unittest.mock import patch, MagicMock, call
from mtg_commander_picker.services.sheets import (
    GoogleSheetsService,
    SheetUpdateError,
    SheetInitializationError,
    SheetDataError,
    CardNotFoundError,
    CardAlreadyReservedError,
    SheetRecord,
)
from mtg_commander_picker.config import ConfigError, REQUIRED_COLS, COL_RESERVED, COL_CARD_NAME, COL_COLOR


# Fixture for a basic service instance
@pytest.fixture
def service():
    """Provides a basic GoogleSheetsService instance."""
    return GoogleSheetsService()

# Fixture for a mock settings object
@pytest.fixture
def mock_settings():
    """Provides a mock settings object with necessary attributes."""
    settings = MagicMock()
    settings.GOOGLE_SHEETS_CREDENTIALS_JSON = MagicMock()
    settings.GOOGLE_SHEETS_CREDENTIALS_JSON.get_secret_value.return_value = json.dumps({"type": "service_account"})
    settings.GOOGLE_SHEET_ID = "dummy_sheet_id"
    settings.SHEET_CACHE_TTL_SECONDS = 600 # Default TTL
    return settings

# Fixture for a mock gspread client and sheet
@pytest.fixture
def mock_gspread():
    """Mocks gspread.authorize and returns a mock sheet."""
    mock_gc = MagicMock()
    mock_sheet = MagicMock()
    mock_gc.open_by_key.return_value.sheet1 = mock_sheet
    with patch("mtg_commander_picker.services.sheets.gspread.authorize", return_value=mock_gc) as mock_auth:
        yield mock_sheet, mock_auth

# Helper to create a mock response object for gspread APIError
def create_mock_response(status_code, json_data=None, text_data=""):
    """Creates a mock response object with json and text attributes."""
    mock_res = MagicMock()
    mock_res.status_code = status_code
    if json_data is not None:
        mock_res.json.return_value = json_data
    else:
        # Default JSON structure expected by gspread APIError, including 'code'
        mock_res.json.return_value = {"error": {"code": status_code, "message": text_data, "status": "ERROR"}}
    mock_res.text = text_data
    return mock_res


# --- SheetRecord Tests ---

def test_sheet_record_from_dict():
    """Tests creating a SheetRecord from a dictionary."""
    data = {
        COL_CARD_NAME: "Test Card",
        COL_COLOR: "Blue",
        COL_RESERVED: "User1"
    }
    record = SheetRecord.from_dict(data)
    assert record.card_name == "Test Card"
    assert record.color == "Blue"
    assert record.reserved == "User1"

def test_sheet_record_from_dict_missing_keys():
    """Tests creating a SheetRecord from a dictionary with missing keys."""
    data = {
        COL_CARD_NAME: "Another Card",
        # Missing COL_COLOR and COL_RESERVED
    }
    record = SheetRecord.from_dict(data)
    assert record.card_name == "Another Card"
    assert record.color is None
    assert record.reserved is None

# --- Initialization Tests ---

def test_initialize_success(service, mock_settings, mock_gspread):
    """Tests successful initialization of the service."""
    mock_sheet, mock_auth = mock_gspread
    # Simulate sheet headers including required columns
    mock_sheet.row_values.return_value = REQUIRED_COLS

    with patch("mtg_commander_picker.services.sheets.get_settings", return_value=mock_settings):
        # Mock _refresh_cache to prevent actual data fetch during init test
        with patch.object(service, "_refresh_cache") as mock_refresh:
            service.initialize()

            mock_auth.assert_called_once()
            mock_sheet.row_values.assert_called_once_with(1)
            assert service.initialized is True
            assert service.sheet is mock_sheet
            assert service.col_map == {col: i + 1 for i, col in enumerate(REQUIRED_COLS)}
            mock_refresh.assert_called_once() # Ensure cache is refreshed on success


def test_initialize_invalid_credentials_json(service, mock_settings):
    """Tests initialization with invalid JSON credentials."""
    mock_settings.GOOGLE_SHEETS_CREDENTIALS_JSON.get_secret_value.return_value = "{invalid_json}"
    with patch("mtg_commander_picker.services.sheets.get_settings", return_value=mock_settings):
        with pytest.raises(ConfigError, match="Invalid JSON format"):
            service.initialize()
    assert service.initialized is False


def test_initialize_missing_credentials(service, mock_settings):
    """Tests initialization when credentials JSON is not set in settings."""
    mock_settings.GOOGLE_SHEETS_CREDENTIALS_JSON = None
    with patch("mtg_commander_picker.services.sheets.get_settings", return_value=mock_settings):
        with pytest.raises(ConfigError, match="credentials JSON is not set"):
            service.initialize()
    assert service.initialized is False


def test_initialize_missing_sheet_id(service, mock_settings):
    """Tests initialization when sheet ID is not set in settings."""
    mock_settings.GOOGLE_SHEET_ID = ""
    with patch("mtg_commander_picker.services.sheets.get_settings", return_value=mock_settings):
        with pytest.raises(ConfigError, match="Google Sheet ID is not set"):
            service.initialize()
    assert service.initialized is False


def test_initialize_gspread_api_error(service, mock_settings):
    """Tests initialization when gspread raises an API error."""
    # Use the helper to create a mock response
    mock_response = create_mock_response(400, text_data="API Error during auth")
    with patch("mtg_commander_picker.services.sheets.gspread.authorize", side_effect=gspread.exceptions.APIError(mock_response)):
         with patch("mtg_commander_picker.services.sheets.get_settings", return_value=mock_settings):
            with pytest.raises(SheetInitializationError, match="Google Sheets API error during setup"):
                service.initialize()
    assert service.initialized is False


def test_initialize_missing_required_columns(service, mock_settings, mock_gspread):
    """Tests initialization when sheet headers are missing required columns."""
    mock_sheet, _ = mock_gspread
    mock_sheet.row_values.return_value = ["Wrong", "Headers"] # Missing required columns

    with patch("mtg_commander_picker.services.sheets.get_settings", return_value=mock_settings):
        with pytest.raises(SheetInitializationError, match="Missing required columns"):
            service.initialize()
    assert service.initialized is False


def test_initialize_unexpected_error(service, mock_settings):
    """Tests initialization when an unexpected error occurs."""
    with patch("mtg_commander_picker.services.sheets.gspread.authorize", side_effect=Exception("Unexpected")):
        with patch("mtg_commander_picker.services.sheets.get_settings", return_value=mock_settings):
            with pytest.raises(SheetInitializationError, match="An unexpected error occurred during Google Sheets setup"):
                service.initialize()
    assert service.initialized is False


# --- Cache Refresh Tests ---

def test_refresh_cache_warns_if_not_initialized(caplog, service):
    """Tests that _refresh_cache warns if the service is not initialized."""
    service.initialized = False
    service._refresh_cache()
    assert any("Sheet not initialized" in line for line in caplog.text.splitlines())
    assert service.sheet_cache == ([], [], {}, service.sheet_cache[3]) # Ensure cache is reset/empty


def test_refresh_cache_success(service, mock_gspread):
    """Tests successful cache refresh."""
    mock_sheet, _ = mock_gspread
    mock_sheet.get_all_records.return_value = [{COL_CARD_NAME: "Card1", COL_COLOR: "Red", COL_RESERVED: ""}]
    mock_sheet.row_values.return_value = REQUIRED_COLS

    service.sheet = mock_sheet # Manually set the sheet as initialize is not called here
    service.col_map = {col: i + 1 for i, col in enumerate(REQUIRED_COLS)} # Manually set col_map
    service.initialized = True

    service._refresh_cache()

    mock_sheet.get_all_records.assert_called_once()
    mock_sheet.row_values.assert_called_once_with(1)
    records, headers, col_map, timestamp = service.sheet_cache
    assert len(records) == 1
    assert records[0].card_name == "Card1"
    assert headers == REQUIRED_COLS
    assert col_map == {col: i + 1 for i, col in enumerate(REQUIRED_COLS)}
    assert timestamp > 0


def test_refresh_cache_gspread_api_error(service, mock_gspread):
    """Tests _refresh_cache when gspread raises an API error."""
    mock_sheet, _ = mock_gspread
    # Use the helper to create a mock response
    mock_response = create_mock_response(400, text_data="API Error during fetch")
    mock_sheet.get_all_records.side_effect = gspread.exceptions.APIError(mock_response)

    service.sheet = mock_sheet
    service.initialized = True
    service.sheet_cache = ([SheetRecord(card_name="Old")], ["OldHeader"], {"OldHeader": 1}, time.time()) # Simulate existing cache

    with pytest.raises(SheetDataError, match="Google Sheets API error during cache refresh"):
        service._refresh_cache()

    # Ensure cache is NOT cleared on API error during refresh
    assert len(service.sheet_cache[0]) == 1
    assert service.sheet_cache[0][0].card_name == "Old"


def test_refresh_cache_missing_required_columns(service, mock_gspread):
    """Tests _refresh_cache when sheet headers are missing required columns."""
    mock_sheet, _ = mock_gspread
    mock_sheet.get_all_records.return_value = [{COL_CARD_NAME: "Card1"}]
    mock_sheet.row_values.return_value = ["Wrong", "Headers"] # Missing required columns

    service.sheet = mock_sheet
    service.initialized = True
    service.sheet_cache = ([SheetRecord(card_name="Old")], ["OldHeader"], {"OldHeader": 1}, time.time()) # Simulate existing cache

    with pytest.raises(SheetDataError, match="Missing required columns in Google Sheet headers"):
        service._refresh_cache()

    # Ensure cache is NOT cleared on data integrity error during refresh
    assert len(service.sheet_cache[0]) == 1
    assert service.sheet_cache[0][0].card_name == "Old"


def test_refresh_cache_unexpected_error(service, mock_gspread):
    """Tests _refresh_cache when an unexpected error occurs."""
    mock_sheet, _ = mock_gspread
    mock_sheet.get_all_records.side_effect = Exception("Unexpected")

    service.sheet = mock_sheet
    service.initialized = True
    service.sheet_cache = ([SheetRecord(card_name="Old")], ["OldHeader"], {"OldHeader": 1}, time.time()) # Simulate existing cache

    with pytest.raises(SheetDataError, match="An unexpected error occurred during cache refresh"):
        service._refresh_cache()

    # Ensure cache is NOT cleared on unexpected error during refresh
    assert len(service.sheet_cache[0]) == 1
    assert service.sheet_cache[0][0].card_name == "Old"


# --- Get Sheet Data Tests ---

def test_get_sheet_data_cache_hit(service, mock_settings):
    """Tests retrieving data from a valid cache."""
    service.initialized = True
    # Simulate a valid cache
    cached_records = [SheetRecord(card_name="CachedCard", color="Green", reserved="")]
    cached_headers = REQUIRED_COLS
    cached_col_map = {col: i + 1 for i, col in enumerate(REQUIRED_COLS)}
    service.sheet_cache = (cached_records, cached_headers, cached_col_map, time.time())

    with patch("mtg_commander_picker.services.sheets.get_settings", return_value=mock_settings):
        with patch.object(service, "_refresh_cache") as mock_refresh:
            records, headers, col_map = service.get_sheet_data()

            mock_refresh.assert_not_called() # Cache should not be refreshed
            assert records == cached_records
            assert headers == cached_headers
            assert col_map == cached_col_map


def test_get_sheet_data_cache_expired(service, mock_settings):
    """Tests retrieving data when the cache has expired."""
    service.initialized = True
    # Simulate an expired cache
    expired_timestamp = time.time() - mock_settings.SHEET_CACHE_TTL_SECONDS - 1
    service.sheet_cache = ([], [], {}, expired_timestamp) # Empty cache, but timestamp is old

    # Mock _refresh_cache to simulate successful refresh
    refreshed_records = [SheetRecord(card_name="RefreshedCard", color="Blue", reserved="")]
    refreshed_headers = REQUIRED_COLS
    refreshed_col_map = {col: i + 1 for i, col in enumerate(REQUIRED_COLS)}
    with patch.object(service, "_refresh_cache") as mock_refresh:
        # Configure the mock _refresh_cache to update the service's cache
        def side_effect_refresh():
            service.sheet_cache = (refreshed_records, refreshed_headers, refreshed_col_map, time.time())
        mock_refresh.side_effect = side_effect_refresh

        with patch("mtg_commander_picker.services.sheets.get_settings", return_value=mock_settings):
            records, headers, col_map = service.get_sheet_data()

            mock_refresh.assert_called_once() # Cache should be refreshed
            assert records == refreshed_records
            assert headers == refreshed_headers
            assert col_map == refreshed_col_map


def test_get_sheet_data_cache_empty(service, mock_settings):
    """Tests retrieving data when the cache is empty."""
    service.initialized = True
    # Simulate an empty cache with a recent timestamp (still needs refresh if empty)
    service.sheet_cache = ([], [], {}, time.time())

    # Mock _refresh_cache to simulate successful refresh
    refreshed_records = [SheetRecord(card_name="RefreshedCard", color="Blue", reserved="")]
    refreshed_headers = REQUIRED_COLS
    refreshed_col_map = {col: i + 1 for i, col in enumerate(REQUIRED_COLS)}
    with patch.object(service, "_refresh_cache") as mock_refresh:
        # Configure the mock _refresh_cache to update the service's cache
        def side_effect_refresh():
            service.sheet_cache = (refreshed_records, refreshed_headers, refreshed_col_map, time.time())
        mock_refresh.side_effect = side_effect_refresh

        with patch("mtg_commander_picker.services.sheets.get_settings", return_value=mock_settings):
            records, headers, col_map = service.get_sheet_data()

            mock_refresh.assert_called_once() # Cache should be refreshed
            assert records == refreshed_records
            assert headers == refreshed_headers
            assert col_map == refreshed_col_map


def test_get_sheet_data_refresh_fails(service, mock_settings):
    """Tests retrieving data when cache refresh fails."""
    service.initialized = True
    # Simulate an expired cache
    expired_timestamp = time.time() - mock_settings.SHEET_CACHE_TTL_SECONDS - 1
    service.sheet_cache = ([], [], {}, expired_timestamp)

    with patch.object(service, "_refresh_cache", side_effect=SheetDataError("Refresh failed")):
        with patch("mtg_commander_picker.services.sheets.get_settings", return_value=mock_settings):
            with pytest.raises(SheetDataError, match="Refresh failed"):
                service.get_sheet_data()

# --- Update Card Reservation Tests ---

def test_update_card_reservation_raises_if_not_initialized(service):
    """Tests that update_card_reservation raises SheetUpdateError if not initialized."""
    service.initialized = False
    with pytest.raises(SheetUpdateError, match="not initialized"):
        service.update_card_reservation("CardName", "Color", "User")


def test_update_card_reservation_not_found(service, mock_gspread):
    """Tests update_card_reservation when the card is not found."""
    mock_sheet, _ = mock_gspread
    # Simulate sheet data where the card is not present
    mock_sheet.get_all_records.return_value = [
        {COL_CARD_NAME: "Another Card", COL_COLOR: "Red", COL_RESERVED: ""}
    ]
    mock_sheet.row_values.return_value = REQUIRED_COLS

    service.sheet = mock_sheet
    service.col_map = {col: i + 1 for i, col in enumerate(REQUIRED_COLS)}
    service.initialized = True

    with patch.object(service, "_refresh_cache") as mock_refresh:
        # Expecting CardNotFoundError directly now
        with pytest.raises(CardNotFoundError, match="Card 'MissingCard' with color 'Green' not found"):
            service.update_card_reservation("MissingCard", "Green", "User")

        # Cache should be attempted to be refreshed on failure
        mock_refresh.assert_called_once()


def test_update_card_reservation_missing_required_columns_before_update(service, mock_gspread):
    """Tests update_card_reservation when required columns are missing in the pre-update fetch."""
    mock_sheet, _ = mock_gspread
    # Simulate sheet data with missing required columns
    mock_sheet.get_all_records.return_value = [{COL_CARD_NAME: "Card1", COL_COLOR: "Red", COL_RESERVED: ""}]
    mock_sheet.row_values.return_value = ["Wrong", "Headers"] # Missing required columns

    service.sheet = mock_sheet
    service.col_map = {col: i + 1 for i, col in enumerate(REQUIRED_COLS)}
    service.initialized = True

    with patch.object(service, "_refresh_cache") as mock_refresh:
        # Expecting SheetDataError directly now
        # Updated regex to match the actual error message raised when required columns are missing
        with pytest.raises(SheetDataError, match=f"Required columns missing in latest sheet data for update_card_reservation. Missing: {['Card Name', 'Color', 'Reserved']}".replace('[', '\\[').replace(']', '\\]')):
             service.update_card_reservation("Card1", "Red", "User")

        # Cache should be attempted to be refreshed on failure
        mock_refresh.assert_called_once()


def test_update_card_reservation_missing_reserved_column_before_update(service, mock_gspread):
    """Tests update_card_reservation when the reserved column is missing in the pre-update fetch."""
    mock_sheet, _ = mock_gspread
    # Simulate sheet data with missing reserved column
    headers_without_reserved = [col for col in REQUIRED_COLS if col != COL_RESERVED]
    mock_sheet.get_all_records.return_value = [{COL_CARD_NAME: "Card1", COL_COLOR: "Red"}]
    mock_sheet.row_values.return_value = headers_without_reserved

    service.sheet = mock_sheet
    service.col_map = {col: i + 1 for i, col in enumerate(REQUIRED_COLS)}
    service.initialized = True

    with patch.object(service, "_refresh_cache") as mock_refresh:
        # Expecting SheetDataError directly now
        # Updated regex to match the actual error message raised when the reserved column is missing
        with pytest.raises(SheetDataError, match=f"Required columns missing in latest sheet data for update_card_reservation. Missing: {['Reserved']}".replace('[', '\\[').replace(']', '\\]')):
             service.update_card_reservation("Card1", "Red", "User")

        # Cache should be attempted to be refreshed on failure
        mock_refresh.assert_called_once()


def test_update_card_reservation_already_reserved(service, mock_gspread):
    """Tests update_card_reservation when the card is already reserved."""
    mock_sheet, _ = mock_gspread
    # Simulate sheet data where the card is already reserved
    reserved_user = "ExistingUser"
    mock_sheet.get_all_records.return_value = [
        {COL_CARD_NAME: "Card1", COL_COLOR: "Red", COL_RESERVED: reserved_user}
    ]
    mock_sheet.row_values.return_value = REQUIRED_COLS

    service.sheet = mock_sheet
    service.col_map = {col: i + 1 for i, col in enumerate(REQUIRED_COLS)}
    service.initialized = True

    with patch.object(service, "_refresh_cache") as mock_refresh:
        # Expecting CardAlreadyReservedError directly now
        with pytest.raises(CardAlreadyReservedError) as exc_info:
            service.update_card_reservation("Card1", "Red", "NewUser")

        assert f"Card 'Card1' (Red) already reserved by {reserved_user}" in str(exc_info.value)
        assert exc_info.value.reserved_by == reserved_user

        # Cache should be attempted to be refreshed on failure
        mock_refresh.assert_called_once()


def test_update_card_reservation_success(service, mock_gspread):
    """Tests successful update of card reservation."""
    mock_sheet, _ = mock_gspread
    card_name = "CardToReserve"
    card_color = "Blue"
    user_name = "TestUser"
    user_lower = user_name.lower()

    # Simulate sheet data where the card is available
    mock_sheet.get_all_records.return_value = [
        {COL_CARD_NAME: "Another Card", COL_COLOR: "Red", COL_RESERVED: ""},
        {COL_CARD_NAME: card_name, COL_COLOR: card_color, COL_RESERVED: ""}, # Target card
        {COL_CARD_NAME: "Yet Another Card", COL_COLOR: "Green", COL_RESERVED: "SomeoneElse"},
    ]
    mock_sheet.row_values.return_value = REQUIRED_COLS

    service.sheet = mock_sheet
    service.col_map = {col: i + 1 for i, col in enumerate(REQUIRED_COLS)}
    service.initialized = True

    # Mock _refresh_cache to simulate successful refresh after update
    with patch.object(service, "_refresh_cache") as mock_refresh:
        service.update_card_reservation(card_name, card_color, user_name)

        # Verify get_all_records and row_values were called before update
        mock_sheet.get_all_records.assert_called_once()
        mock_sheet.row_values.assert_called_once_with(1)

        # Verify update_cell was called with the correct row and value
        # The target row index is 2 (1-based index for the second record)
        reserved_col_index = service.col_map[COL_RESERVED]
        mock_sheet.update_cell.assert_called_once_with(3, reserved_col_index, user_lower)

        # Verify cache refresh was attempted after successful update
        mock_refresh.assert_called_once()


def test_update_card_reservation_success_refresh_fails(service, mock_gspread, caplog):
    """Tests successful update of card reservation when subsequent cache refresh fails."""
    mock_sheet, _ = mock_gspread
    card_name = "CardToReserve"
    card_color = "Blue"
    user_name = "TestUser"
    user_lower = user_name.lower()

    # Simulate sheet data where the card is available
    mock_sheet.get_all_records.return_value = [
        {COL_CARD_NAME: card_name, COL_COLOR: card_color, COL_RESERVED: ""}, # Target card
    ]
    mock_sheet.row_values.return_value = REQUIRED_COLS

    service.sheet = mock_sheet
    service.col_map = {col: i + 1 for i, col in enumerate(REQUIRED_COLS)}
    service.initialized = True

    # Mock _refresh_cache to raise an error
    with patch.object(service, "_refresh_cache", side_effect=SheetDataError("Cache refresh failed after update")) as mock_refresh:
        service.update_card_reservation(card_name, card_color, user_name)

        # Verify update_cell was called
        reserved_col_index = service.col_map[COL_RESERVED]
        mock_sheet.update_cell.assert_called_once_with(2, reserved_col_index, user_lower)

        # Verify cache refresh was attempted
        mock_refresh.assert_called_once()

        # Verify the error was logged
        assert any("Cache refresh failed after successful update" in record.message for record in caplog.records)


def test_update_card_reservation_gspread_api_error_during_fetch(service, mock_gspread):
    """Tests update_card_reservation when gspread raises APIError during the initial fetch."""
    mock_sheet, _ = mock_gspread
    # Mock a response object with json and text attributes
    mock_response = create_mock_response(400, text_data="API Error during fetch")
    mock_sheet.get_all_records.side_effect = gspread.exceptions.APIError(mock_response)

    service.sheet = mock_sheet
    service.col_map = {col: i + 1 for i, col in enumerate(REQUIRED_COLS)}
    service.initialized = True

    with patch.object(service, "_refresh_cache") as mock_refresh:
        # Expecting SheetDataError for API errors during fetch
        # Updated regex to match the actual error message
        with pytest.raises(SheetDataError, match=r"An error occurred during data fetch for update_card_reservation for 'Card1': APIError: \[400\]: API Error during fetch"):
            service.update_card_reservation("Card1", "Red", "User")

        # Cache should be attempted to be refreshed on failure
        mock_refresh.assert_called_once()


def test_update_card_reservation_gspread_api_error_during_update(service, mock_gspread):
    """Tests update_card_reservation when gspread raises APIError during the update_cell call."""
    mock_sheet, _ = mock_gspread
    card_name = "CardToReserve"
    card_color = "Blue"
    user_name = "TestUser"

    # Simulate sheet data where the card is available
    mock_sheet.get_all_records.return_value = [
        {COL_CARD_NAME: "Card1", COL_COLOR: "Red", COL_RESERVED: ""}, # Target card
    ]
    mock_sheet.row_values.return_value = REQUIRED_COLS

    # Simulate API error during update_cell
    # Mock a response object with json and text attributes
    mock_response = create_mock_response(400, text_data="API Error during update")
    mock_sheet.update_cell.side_effect = gspread.exceptions.APIError(mock_response)

    service.sheet = mock_sheet
    service.col_map = {col: i + 1 for i, col in enumerate(REQUIRED_COLS)}
    service.initialized = True

    with patch.object(service, "_refresh_cache") as mock_refresh:
        # Expecting SheetUpdateError for API errors during update_cell
        # Updated regex to match the actual error message
        with pytest.raises(SheetUpdateError, match=r"Google Sheets API error during update_card_reservation for 'Card1': APIError: \[400\]: API Error during update"):
            service.update_card_reservation("Card1", "Red", "User")

        # Cache should be attempted to be refreshed on failure
        mock_refresh.assert_called_once()


def test_update_card_reservation_unexpected_error(service, mock_gspread):
    """Tests update_card_reservation when an unexpected error occurs."""
    mock_sheet, _ = mock_gspread
    # Simulate an unexpected error during the initial fetch
    mock_sheet.get_all_records.side_effect = Exception("Unexpected error during fetch")

    service.sheet = mock_sheet
    service.col_map = {col: i + 1 for i, col in enumerate(REQUIRED_COLS)}
    service.initialized = True

    with patch.object(service, "_refresh_cache") as mock_refresh:
        # Expecting SheetDataError for unexpected errors during fetch/processing
        # Updated regex to match the actual error message
        with pytest.raises(SheetDataError, match=r"An error occurred during data fetch for update_card_reservation for 'Card1': Unexpected error during fetch"):
            service.update_card_reservation("Card1", "Red", "User")

        # Cache should be attempted to be refreshed on failure
        mock_refresh.assert_called_once()
