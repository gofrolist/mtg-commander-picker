import logging
import random
from typing import List, Dict, Optional, Tuple, Set

from flask import Blueprint, request, jsonify, abort, Response
from pydantic import BaseModel, ValidationError, Field, field_validator
from werkzeug.routing import BaseConverter

from mtg_commander_picker.config import REQUIRED_COLS, VALID_COLORS, get_settings
from mtg_commander_picker.services import google_sheets_service
from mtg_commander_picker.services.scryfall import fetch_image_url
from mtg_commander_picker.services.sheets import SheetRecord, SheetDataError, CardNotFoundError, CardAlreadyReservedError, SheetUpdateError

# Set the API blueprint prefix to /api/v1
api_bp = Blueprint('api', __name__, url_prefix='/api/v1')
app_logger = logging.getLogger(__name__)


# ─── Custom URL Converter for MTG Colors ─────────────────────────────────────────

class ColorConverter(BaseConverter):
    """
    Custom URL converter that validates if the path segment is a valid MTG color.
    Automatically handles case-insensitivity and aborts with a 400 if invalid.
    """

    def to_python(self, value: str) -> str:
        """Convert path segment to Python object (lowercase color string)."""
        color_lower = value.strip().lower()
        if color_lower not in VALID_COLORS:
            app_logger.warning(f"Invalid color in URL path: '{value}'")
            # Abort with a 400 error if the color is not in the valid list
            abort(400, description=f"Invalid color: {value}. Valid colors are: {', '.join(sorted(list(VALID_COLORS)))}")
        return color_lower  # Return the validated, lowercase color

    def to_url(self, value: str) -> str:
        """Convert Python object back to URL path segment."""
        # Ensure the value is a valid color before converting back to URL
        if value.strip().lower() not in VALID_COLORS:
            app_logger.warning(f"Attempted to build URL with invalid color: '{value}'")
            # This case should ideally not happen if colors are managed correctly
            # but adding a check prevents unexpected behavior.
            return ""  # Or raise an error if strictness is required
        return value  # Return the original value or a standardized lowercase version


# Define Pydantic models for API payloads for automatic validation
class CardResponse(BaseModel):
    """Represents a card object returned by the /cards endpoint."""
    name: Optional[str] = None
    image: Optional[str] = None  # URL to the image


class SelectCardRequest(BaseModel):
    """
    Represents the expected JSON payload for the /select-card endpoint.
    Pydantic handles validation based on type hints and required fields.
    """
    userName: str = Field(..., description="The name of the user making the reservation.")
    cardName: str = Field(..., description="The name of the card to reserve.")
    cardColor: str = Field(..., description="The color of the card to reserve.")

    # This field validator handles color validation for the request body
    @field_validator('cardColor')
    @classmethod
    def validate_card_color(cls, value):
        """Validates that the cardColor is a valid color."""
        if value.strip().lower() not in VALID_COLORS:
            raise ValueError(f"Invalid card color: '{value}'. Must be one of {sorted(list(VALID_COLORS))}")
        return value  # Return the validated value


class SelectCardSuccessResponse(BaseModel):
    """Represents the success JSON response for the /select-card endpoint."""
    message: str
    cardName: str
    cardColor: str
    userName: str


# ─── Helper Functions ────────────────────────────────────────────────────────────

def _check_required_sheet_columns(current_col_map: Dict[str, int], endpoint: str) -> None:
    """
    Checks if all required columns are present in the sheet's column map.
    Aborts with a 500 error if columns are missing.
    """
    if not all(col in current_col_map for col in REQUIRED_COLS):
        missing: List[str] = [col for col in REQUIRED_COLS if col not in current_col_map]
        app_logger.error(f"Required columns missing in sheet data for {endpoint}. Missing: {missing}")
        # Use abort for standardized error response
        abort(500, description="Backend data structure error: Required columns missing")


def _get_user_reserved(records: List[SheetRecord], user_lower: str) -> Tuple[List[SheetRecord], Set[str]]:
    """
    Filters sheet records to find those reserved by a specific user
    and returns the list of reserved records and a set of reserved colors.
    """
    reserved_records = [r for r in records if r.reserved and r.reserved.strip().lower() == user_lower]
    reserved_colors = {r.color.strip().lower() for r in reserved_records if r.color}
    return reserved_records, reserved_colors


# Modify the route to accept the color using the custom converter
# The converter handles validation and provides the lowercase color string
# Updated return type hint to use Tuple[Response, int]
@api_bp.route('/cards/<color:color>', methods=['GET'])  # Use <color:color> to use the custom converter
def get_cards(color: str) -> Tuple[Response, int]:
    """
    Retrieves a list of available cards for a given color,
    considering user reservations and limits.
    """
    settings = get_settings()
    # The color validation for the path parameter is now handled by the ColorConverter.
    # The 'color' variable passed to this function is already validated and in lowercase.
    requested_color_lower: str = color  # color is already lowercase from the converter

    # Get userName from query parameters as before
    user: Optional[str] = request.args.get('userName')
    app_logger.info(f"GET /api/v1/cards/{color}?userName={user}")

    # Check service initialization status - This check is still relevant
    if not google_sheets_service.initialized:
        app_logger.error("Google Sheets service not initialized.")
        # Use abort for standardized error response
        abort(500, description="Backend data source not available or configured incorrectly")

    try:
        # Get data from the service instance - returns list of SheetRecord
        # This call can now raise SheetDataError
        records: List[SheetRecord]
        headers: List[str]
        current_col_map: Dict[str, int]
        records, headers, current_col_map = google_sheets_service.get_sheet_data()

        # Use the helper function to check required columns
        # This helper will abort if columns are missing, no need to catch specific error here
        _check_required_sheet_columns(current_col_map, "/api/v1/cards")

    except SheetDataError as e:
        # Catch SheetDataError and return a 500 response
        app_logger.error(f"Error fetching or processing sheet data for /cards: {e}")
        abort(500, description="Error fetching or processing sheet data")
    except Exception as err:
        # Catch any other unexpected errors
        app_logger.error(f"An unexpected error occurred in /cards: {err}")
        abort(500, description="An unexpected server error occurred")

    if user and user.strip():
        user_lower: str = user.strip().lower()
        # Use the helper function to get user's reserved cards and colors
        user_reserved_records, colors_reserved = _get_user_reserved(records, user_lower)

        # If the user has no reservations at all, return an empty list
        if not user_reserved_records:
            app_logger.info(f"User '{user_lower}' has no reserved cards.")
            return jsonify([]), 200

        # Access MAX_RESERVATIONS_PER_USER from the settings object
        app_logger.info(
            f"User '{user_lower}' has {len(colors_reserved)} colors reserved (max {settings.MAX_RESERVATIONS_PER_USER}).")

        # Access MAX_RESERVATIONS_PER_USER from the settings object
        if requested_color_lower in colors_reserved:
            # Find the specific reserved record for this color
            reserved_card_record: Optional[SheetRecord] = next((r for r in user_reserved_records
                                                                if
                                                                r.color and r.color.strip().lower() == requested_color_lower),
                                                               None)
            if reserved_card_record and reserved_card_record.card_name:
                card_name: str = reserved_card_record.card_name
                app_logger.info(
                    f"User '{user_lower}' re-requested color={color}, returning existing card '{card_name}'.")
                # Return a list containing a single CardResponse dataclass instance
                # Pydantic models have a model_dump() or model_dump_json() method for serialization
                return jsonify([CardResponse(name=card_name, image=fetch_image_url(card_name)).model_dump()]), 200
            else:
                app_logger.warning(
                    f"Reserved color {color} found for user {user_lower}, but card record not found or missing name in user_reserved_records list.")
                return jsonify([]), 200  # Return empty list if reserved card couldn't be located

        # Access MAX_RESERVATIONS_PER_USER from the settings object
        if len(colors_reserved) >= settings.MAX_RESERVATIONS_PER_USER:
            app_logger.info(
                f"User '{user_lower}' has reached maximum reservations ({settings.MAX_RESERVATIONS_PER_USER}).")
            # Return all cards reserved by the user, regardless of the requested color
            # Convert SheetRecord instances to CardResponse Pydantic instances and then to dicts
            return jsonify([CardResponse(name=r.card_name, image=fetch_image_url(r.card_name)).model_dump()
                            for r in user_reserved_records if r.card_name]), 200

    # If no user, or user hasn't reserved the requested color, or hasn't reached max reservations
    # Find available cards for the requested color (case-insensitive color match)
    # Filter records (SheetRecord instances)
    available_records: List[SheetRecord] = [r for r in records
                                            if r.color and r.color.strip().lower() == requested_color_lower
                                            and not r.reserved]  # Check if 'reserved' attribute is None or empty string

    # Ensure we don't try to sample more cards than available
    num_picks: int = min(3, len(available_records))
    # Sample from the list of SheetRecord instances
    picks: List[SheetRecord] = random.sample(available_records, num_picks) if available_records else []
    app_logger.info(f"Returning {len(picks)} available cards for color={color}.")
    # Convert sampled SheetRecord instances to CardResponse Pydantic instances and then to dicts
    return jsonify([CardResponse(name=r.card_name, image=fetch_image_url(r.card_name)).model_dump()
                    for r in picks if r.card_name]), 200


# Updated return type hint to use Tuple[Response, int]
@api_bp.route('/select-card', methods=['POST'])
def select_card() -> Tuple[Response, int]:
    """
    Allows a user to reserve a specific card if it's available and
    the user has not reached their reservation limit for that color or overall.
    Updates the Google Sheet and refreshes the cache.
    """
    settings = get_settings()
    # Check service initialization status - This check is still relevant
    if not google_sheets_service.initialized:
        app_logger.error("Google Sheets service not initialized.")
        # Use abort for standardized error response
        abort(500, description="Backend data source not available or configured incorrectly")

    try:
        # Use Pydantic model to validate the incoming JSON data
        # Pydantic's model_validate_json will now also run the validate_card_color validator
        request_payload = SelectCardRequest.model_validate_json(request.data)
        user: str = request_payload.userName
        card: str = request_payload.cardName
        color: str = request_payload.cardColor  # This value is already validated by Pydantic

        app_logger.info(f"POST /api/v1/select-card user={user} card={card} color={color}")

        user_lower: str = user.strip().lower()
        color_lower: str = color.strip().lower()  # Still need lowercase for comparisons


    except ValidationError as e:
        # Catch Pydantic validation errors and return a 400 response
        app_logger.warning(f"Request payload validation error for select-card: {e.errors()}")
        abort(400, description=f"Invalid request payload: {e.errors()}")
    except Exception as err:
        # Catch other potential errors during request processing before sheet interaction
        app_logger.error(f"Error processing select-card request data: {err}")
        abort(400, description="Error processing request data")

    # Before attempting reservation, check user's current reservations
    try:
        # Get data from the service instance - this call can now raise SheetDataError
        records: List[SheetRecord]
        headers: List[str]
        current_col_map: Dict[str, int]
        records, headers, current_col_map = google_sheets_service.get_sheet_data()

        # Use the helper function to check required columns
        _check_required_sheet_columns(current_col_map, "/api/v1/select-card")

        # Use the helper function to get user's reserved cards and colors
        user_reserved_records, colors_reserved = _get_user_reserved(records, user_lower)


    except SheetDataError as e:
        # Catch SheetDataError during the pre-check and return a 500 response
        app_logger.error(f"Error fetching or processing sheet data for select-card pre-check: {e}")
        abort(500, description="Error fetching or processing sheet data")
    except Exception as err:
        # Catch any other unexpected errors during the pre-check
        app_logger.error(f"An unexpected error occurred during select-card pre-check: {err}")
        abort(500, description="An unexpected server error occurred during pre-check")

    # Access MAX_RESERVATIONS_PER_USER from the settings object
    app_logger.info(
        f"User '{user_lower}' has {len(colors_reserved)} colors reserved (max {settings.MAX_RESERVATIONS_PER_USER}).")

    # Check if user has already reserved a card of this color
    if color_lower in colors_reserved:
        app_logger.warning(f"User '{user_lower}' attempted to reserve duplicate color {color}.")
        # Use abort for standardized error response
        abort(409, description=f"You have already reserved a card of this color ({color})")

    # Check if user has reached the maximum number of reservations
    # Access MAX_RESERVATIONS_PER_USER from the settings object
    if len(colors_reserved) >= settings.MAX_RESERVATIONS_PER_USER:
        app_logger.warning(
            f"User '{user_lower}' has reached maximum reservations ({settings.MAX_RESERVATIONS_PER_USER}).")
        # Use abort for standardized error response
        abort(409, description=f"Maximum reservations reached ({settings.MAX_RESERVATIONS_PER_USER})")

    # Attempt to update the sheet - this call can now raise specific SheetUpdateError exceptions
    try:
        google_sheets_service.update_card_reservation(card, color, user)
        app_logger.info(f"Reservation successful for card '{card}' by user '{user_lower}'.")
        # Return SelectCardSuccessResponse Pydantic instance (will be serialized to JSON by jsonify)
        # Use model_dump() for serialization
        return jsonify(SelectCardSuccessResponse(message="success", cardName=card, cardColor=color,
                                                 userName=user_lower).model_dump()), 200  # OK

    except CardNotFoundError as e:
        # Catch CardNotFoundError and return a 404 response
        app_logger.warning(f"Reservation failed: Card not found - {e}")
        abort(404, description=str(e))
    except CardAlreadyReservedError as e:
        # Catch CardAlreadyReservedError and return a 409 response
        app_logger.warning(f"Reservation failed: Card already reserved - {e}")
        # Include who reserved it in the response if available
        description = str(e)
        if e.reserved_by:
            description = f"Card already reserved by {e.reserved_by}"
        abort(409, description=description)
    except SheetUpdateError as e:
        # Catch other SheetUpdateErrors and return a 500 response
        app_logger.error(f"Sheet update error during reservation for '{card}': {e}")
        abort(500, description="Error updating reservation in Google Sheet")
    except Exception as err:
        # Catch any other unexpected errors during the update attempt
        app_logger.error(f"An unexpected error occurred during reservation update for '{card}': {err}")
        abort(500, description="An unexpected server error occurred during update")
