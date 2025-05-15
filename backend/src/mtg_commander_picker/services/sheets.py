import json
import logging
import time
from dataclasses import dataclass, field
from typing import List, Dict, Any, Tuple, Optional

import gspread
from google.oauth2.service_account import Credentials

# Import ConfigError from config
from mtg_commander_picker.config import get_settings, REQUIRED_COLS, COL_RESERVED, COL_CARD_NAME, COL_COLOR, SCOPE, ConfigError

app_logger = logging.getLogger(__name__)


# ─── Custom Exceptions ───────────────────────────────────────────────────────────

class SheetError(Exception):
    """Base exception for Google Sheets service errors."""
    pass


class SheetInitializationError(SheetError):
    """Exception raised for errors during Google Sheets service initialization."""
    pass


class SheetDataError(SheetError):
    """Exception raised for errors fetching or processing sheet data."""
    pass


class SheetUpdateError(SheetError):
    """Base exception for errors during a sheet update operation."""
    pass


class CardNotFoundError(SheetUpdateError):
    """Exception raised when a card is not found during an update attempt."""
    pass


class CardAlreadyReservedError(SheetUpdateError):
    """Exception raised when a card is already reserved during an update attempt."""

    def __init__(self, message: str, reserved_by: Optional[str] = None):
        super().__init__(message)
        self.reserved_by = reserved_by


# Define a dataclass to represent a single row (record) from the Google Sheet
@dataclass
class SheetRecord:
    """Represents a single record (row) from the Google Sheet."""
    card_name: Optional[str] = field(default=None)
    color: Optional[str] = field(default=None)
    reserved: Optional[str] = field(default=None)

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> 'SheetRecord':
        """Creates a SheetRecord instance from a dictionary row."""
        return SheetRecord(
            card_name=data.get(COL_CARD_NAME),
            color=data.get(COL_COLOR),
            reserved=data.get(COL_RESERVED)
        )


# Define the GoogleSheetsService class
class GoogleSheetsService:
    def __init__(self):
        """
        Initializes the GoogleSheetsService.
        Connection and initial cache refresh happen in initialize().
        """
        self.sheet: Optional[gspread.Worksheet] = None
        self.col_map: Dict[str, int] = {}
        self.initialized: bool = False  # Flag to indicate successful initialization

        # Cache for sheet data: (list of SheetRecord, headers, col_map, timestamp)
        self.sheet_cache: Tuple[List[SheetRecord], List[str], Dict[str, int], float] = ([], [], {}, 0)

        # Lock for cache access (Placeholder - multiprocessing.Lock will be needed for multi-worker)
        # self._cache_lock: Optional[Lock] = None # Uncomment and initialize in post_fork if using multiprocessing.Lock

    # Updated return type hint: now raises exceptions on failure
    def initialize(self) -> None:
        """
        Initializes the Google Sheets connection and retrieves headers.
        Raises SheetInitializationError or ConfigError on failure.
        """
        app_logger.info("Attempting to initialize Google Sheets service...")
        settings = get_settings()

        # Reset state before attempting initialization
        self.sheet = None
        self.col_map = {}
        self.initialized = False

        # Pydantic validation in config.py now raises ConfigError
        # We still check here for clarity, but the primary validation is in config.py
        if not settings.GOOGLE_SHEETS_CREDENTIALS_JSON:
            msg = "Google Sheets credentials JSON is not set."
            app_logger.error(msg)
            # Raise ConfigError if settings were somehow loaded without this required field
            raise ConfigError(msg)
        if not settings.GOOGLE_SHEET_ID:
            msg = "Google Sheet ID is not set."
            app_logger.error(msg)
            # Raise ConfigError if settings were somehow loaded without this required field
            raise ConfigError(msg)

        try:
            # Access the secret value from SecretStr
            creds_dict: Dict[str, Any] = json.loads(settings.GOOGLE_SHEETS_CREDENTIALS_JSON.get_secret_value())
            creds: Credentials = Credentials.from_service_account_info(creds_dict, scopes=SCOPE)

            gc: gspread.Client = gspread.authorize(creds)
            self.sheet = gc.open_by_key(settings.GOOGLE_SHEET_ID).sheet1
            app_logger.info(f"Successfully connected to Google Sheets with ID: {settings.GOOGLE_SHEET_ID}")

            headers: List[str] = self.sheet.row_values(1)
            self.col_map = {h: i + 1 for i, h in enumerate(headers)}
            app_logger.info(f"Sheet headers: {headers}")

            # Validate required columns exist
            missing: List[str] = [col for col in REQUIRED_COLS if col not in self.col_map]
            if missing:
                msg = f"Missing required columns in Google Sheet: {missing}. Google Sheets functionality may be limited or disabled."
                app_logger.error(msg)
                raise SheetInitializationError(msg)  # Use SheetInitializationError for sheet structure issues

            # Initial cache refresh after successful connection
            self._refresh_cache()

            self.initialized = True
            app_logger.info("Google Sheets service initialization completed successfully.")

        except json.JSONDecodeError as err:
            msg = f"Invalid JSON format for Google Sheets credentials: {err}"
            app_logger.error(msg)
            # Raise ConfigError as this is an issue with the provided credentials format
            raise ConfigError(msg) from err
        except gspread.exceptions.APIError as err:
            msg = f"Google Sheets API error during setup: {err}"
            app_logger.error(msg)
            raise SheetInitializationError(msg) from err
        except Exception as err:
            msg = f"An unexpected error occurred during Google Sheets setup: {err}"
            app_logger.error(msg)
            raise SheetInitializationError(msg) from err

    # Updated return type hint: now raises exceptions on failure
    def _refresh_cache(self) -> None:
        """
        Fetches the latest data from the Google Sheet and updates the cache.
        Raises SheetDataError on failure to fetch or process data.
        """
        if not self.sheet:
            app_logger.warning("Cannot refresh sheet cache: Sheet not initialized.")
            # Ensure cache is empty if sheet is None
            self.sheet_cache = ([], [], {}, time.time())
            # Don't raise here, as initialize handles the primary connection failure
            return

        try:
            app_logger.info("Refreshing Google Sheet data cache...")
            records_dicts: List[Dict[str, Any]] = self.sheet.get_all_records()
            headers: List[str] = self.sheet.row_values(1)
            current_col_map: Dict[str, int] = {h: i + 1 for i, h in enumerate(headers)}

            records: List[SheetRecord] = [SheetRecord.from_dict(record_dict) for record_dict in records_dicts]

            # Validate required columns exist in the fetched headers
            missing: List[str] = [col for col in REQUIRED_COLS if col not in current_col_map]
            if missing:
                msg = f"Cache refresh failed: Missing required columns in Google Sheet headers: {missing}. Cache will not be updated."
                app_logger.error(msg)
                # Keep the old cache if exists, otherwise empty
                if not self.sheet_cache[0]:
                    self.sheet_cache = ([], [], {}, time.time())
                raise SheetDataError(msg)  # Raise exception on data integrity issue

            self.sheet_cache = (records, headers, current_col_map, time.time())
            app_logger.info(f"Google Sheet data cache refreshed successfully with {len(records)} records.")

        except gspread.exceptions.APIError as err:
            msg = f"Google Sheets API error during cache refresh: {err}"
            app_logger.error(msg)
            raise SheetDataError(msg) from err

        except Exception as err:
            if isinstance(err, SheetDataError):
                raise  # Let already-handled SheetDataError bubble up cleanly
            msg = f"An unexpected error occurred during cache refresh: {err}"
            app_logger.error(msg)
            raise SheetDataError(msg) from err


    def get_sheet_data(self) -> Tuple[List[SheetRecord], List[str], Dict[str, int]]:
        """
        Retrieves sheet data from the cache, refreshing it if necessary.
        Returns (list of SheetRecord, headers, col_map).
        Raises SheetDataError if cache refresh fails.
        """
        settings = get_settings()

        records, headers, cached_col_map, timestamp = self.sheet_cache
        if not records or (time.time() - timestamp) > settings.SHEET_CACHE_TTL_SECONDS:
            app_logger.info("Sheet cache expired or empty, attempting refresh.")
            # _refresh_cache now raises SheetDataError on failure, which get_sheet_data will propagate
            self._refresh_cache()
            # After successful refresh, get the updated cache
            records, headers, cached_col_map, _ = self.sheet_cache

        return records, headers, cached_col_map

    # Updated return type hint: now raises exceptions on failure
    def update_card_reservation(self, card_name: str, card_color: str, user_name: str) -> None:
        """
        Updates the reservation status of a card in the Google Sheet.
        Fetches latest data directly from the sheet before updating to minimize race conditions.
        Refreshes the cache after a successful or failed write.
        Raises SheetUpdateError, CardNotFoundError, or CardAlreadyReservedError on failure.
        """
        if not self.sheet or not self.initialized:
            msg = "Cannot update reservation: Google Sheets service not initialized."
            app_logger.error(msg)
            raise SheetUpdateError(msg)

        try:
            app_logger.info(f"Fetching latest sheet data before updating reservation for '{card_name}'...")
            try:
                # Fetch latest data directly from the sheet
                latest_records_dicts: List[Dict[str, Any]] = self.sheet.get_all_records()
                latest_headers: List[str] = self.sheet.row_values(1)
                latest_col_map: Dict[str, int] = {h: i + 1 for i, h in enumerate(latest_headers)}
            except (gspread.exceptions.APIError, Exception) as err:
                # Catch gspread API errors and any other unexpected errors during the initial fetch
                msg = f"An error occurred during data fetch for update_card_reservation for '{card_name}': {err}"
                app_logger.error(msg)
                try:
                    self._refresh_cache()
                except SheetDataError:
                    pass
                raise SheetDataError(msg) from err # Raise SheetDataError for fetch errors


            # Check for missing required columns after fetching headers
            missing_required: List[str] = [col for col in REQUIRED_COLS if col not in latest_col_map]
            if missing_required:
                msg = f"Required columns missing in latest sheet data for update_card_reservation. Missing: {missing_required}"
                app_logger.error(msg)
                # Attempt to refresh cache on data integrity issue during update fetch
                try:
                    self._refresh_cache()
                except SheetDataError:
                    pass  # Ignore cache refresh error if the primary issue is sheet data
                # Raise SheetDataError for data structure problems during fetch/validation
                raise SheetDataError(msg)

            # Check for the specific reserved column after confirming required columns exist
            reserved_col_index: Optional[int] = latest_col_map.get(COL_RESERVED)
            if reserved_col_index is None:
                 # This case should ideally be caught by the missing_required check if COL_RESERVED is in REQUIRED_COLS
                 # but keeping this check explicit adds robustness.
                msg = f"'{COL_RESERVED}' column not found in latest col_map during update."
                app_logger.error(msg)
                try:
                    self._refresh_cache()
                except SheetDataError:
                    pass
                # Raise SheetDataError for data structure problems during fetch/validation
                raise SheetDataError(msg)


            latest_records: List[SheetRecord] = [SheetRecord.from_dict(record_dict) for record_dict in
                                                 latest_records_dicts]


            user_lower: str = user_name.strip().lower()
            color_lower: str = card_color.strip().lower()

            target_sheet_row_index: int = -1
            reserved_by_user: Optional[str] = None

            for i, rec in enumerate(latest_records):
                name_field: Optional[str] = rec.card_name
                c: Optional[str] = rec.color

                if name_field == card_name and c and c.strip().lower() == color_lower:
                    # +2 because get_all_records is 0-indexed, and sheet rows are 1-indexed, plus the header row
                    target_sheet_row_index = i + 2
                    reserved_by_user = rec.reserved
                    app_logger.info(
                        f"Card match found in latest sheet data at row {target_sheet_row_index} for '{card_name}' ({card_color}). Reserved status: {reserved_by_user if reserved_by_user else 'Available'}")
                    break

            if target_sheet_row_index == -1:
                msg = f"Card '{card_name}' with color '{card_color}' not found in latest sheet data for update."
                app_logger.warning(msg)
                try:
                    self._refresh_cache()
                except SheetDataError:
                    pass
                # Raise CardNotFoundError directly
                raise CardNotFoundError(msg)

            if reserved_by_user and reserved_by_user.strip():
                msg = f"Card '{card_name}' ({card_color}) already reserved by {reserved_by_user} in the latest data. Reservation attempt failed."
                app_logger.warning(msg)
                try:
                    self._refresh_cache()
                except SheetDataError:
                    pass
                # Raise CardAlreadyReservedError directly
                raise CardAlreadyReservedError(msg, reserved_by=reserved_by_user.strip())

            app_logger.info("Card is available for reservation in the latest data. Proceeding with update.")

            app_logger.info(
                f"Attempting to update sheet cell R{target_sheet_row_index}C{reserved_col_index} with '{user_lower}'.")

            # Perform the sheet update
            self.sheet.update_cell(target_sheet_row_index, reserved_col_index, user_lower)
            app_logger.info(f"Successfully updated sheet for card '{card_name}' reservation by '{user_lower}'.")

            # Crucially, refresh the cache after a successful write to keep it in sync
            try:
                self._refresh_cache()
            except SheetDataError as err:
                app_logger.error(f"Cache refresh failed after successful update: {err}")
                # Decide if this should be a critical failure or just logged.
                # For now, we log and allow the update to be considered successful.


        except (CardNotFoundError, CardAlreadyReservedError, SheetDataError) as err:
            # Catch CardNotFoundError, CardAlreadyReservedError, and SheetDataError specifically and re-raise them directly
            # This includes SheetDataError raised during the initial fetch or data validation
            raise err # Re-raise the caught exception directly
        except gspread.exceptions.APIError as err:
            # Catch gspread API errors specifically that occur after the initial fetch/validation block
            # (e.g., during update_cell)
            msg = f"Google Sheets API error during update_card_reservation for '{card_name}': {err}"
            app_logger.error(msg)
            try:
                self._refresh_cache()
            except SheetDataError:
                pass
            raise SheetUpdateError(msg) from err # Wrap gspread API errors in SheetUpdateError
        except Exception as err:
            # Catch any other truly unexpected errors that occur after the initial fetch/validation block
            msg = f"An unexpected error occurred during update_card_reservation for '{card_name}': {err}"
            app_logger.error(msg)
            try:
                self._refresh_cache()
            except SheetDataError:
                pass
            raise SheetUpdateError(msg) from err # Wrap other unexpected errors in SheetUpdateError

