import logging
from .sheets import GoogleSheetsService

app_logger = logging.getLogger(__name__)

# Create the instance, but don't initialize yet
google_sheets_service = GoogleSheetsService()

__all__ = ["google_sheets_service"]
