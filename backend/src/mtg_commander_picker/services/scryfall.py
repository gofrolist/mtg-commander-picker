import json
import logging
import os
import re
from typing import Dict, Any
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from mtg_commander_picker.config import get_settings

app_logger = logging.getLogger(__name__)

# ─── Constants ───────────────────────────────────────────────────────────────────

# Precompile the regex for slug creation for performance
# This regex matches any character that is NOT a word character (\w, which includes letters, numbers, and underscore)
# or a hyphen (-). It replaces one or more such characters with a single underscore.
SLUG_NON_ALPHANUMERIC_REGEX = re.compile(r'[^\w-]+')

# Precompile the regex for cleaning up multiple consecutive underscores
SLUG_MULTIPLE_UNDERSCORE_REGEX = re.compile(r'_{2,}')


# ─── Initialization / Setup ─────────────────────────────────────────────────────

def ensure_image_cache_dir_exists() -> None:
    """Ensures the image cache directory exists."""
    # Access IMAGE_CACHE_DIR from the settings object
    settings = get_settings()

    if not os.path.exists(settings.IMAGE_CACHE_DIR):
        try:
            # Access IMAGE_CACHE_DIR from the settings object
            os.makedirs(settings.IMAGE_CACHE_DIR)
            app_logger.info(f"Created image cache directory: {settings.IMAGE_CACHE_DIR}")
        except OSError as err:
            app_logger.error(f"Error creating image cache directory {settings.IMAGE_CACHE_DIR}: {err}")
            # Depending on criticality, you might want to exit or raise an error here
            # if image caching is essential and the directory cannot be created.


# Create a requests Session for reusing HTTP connections to Scryfall
# This improves performance by reusing the underlying TCP connection
scryfall_session = requests.Session()

def get_retry_strategy() -> Retry:
    settings = get_settings()
    try:
        strategy = Retry(
            total=settings.SCRYFALL_RETRY_TOTAL,
            backoff_factor=settings.SCRYFALL_BACKOFF_FACTOR,
            status_forcelist=settings.SCRYFALL_STATUS_FORCELIST,
            allowed_methods=["HEAD", "GET", "OPTIONS"]
        )
        app_logger.info(
            f"Scryfall retry strategy configured: Total={settings.SCRYFALL_RETRY_TOTAL}, "
            f"Backoff={settings.SCRYFALL_BACKOFF_FACTOR}, Statuses={settings.SCRYFALL_STATUS_FORCELIST}")
        return strategy
    except AttributeError as e:
        app_logger.warning(f"Scryfall retry settings not found: {e}. Using defaults.")
    except Exception as e:
        app_logger.error(f"Unexpected error in retry strategy config: {e}. Using defaults.")

    return Retry(
        total=3,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS"]
    )

# Create an HTTP adapter with the retry strategy
def configure_scryfall_session():
    adapter = HTTPAdapter(max_retries=get_retry_strategy())
    scryfall_session.mount("http://", adapter)
    scryfall_session.mount("https://", adapter)
    app_logger.info("Requests session with retry logic configured for Scryfall API.")


# ─── Helper Functions ────────────────────────────────────────────────────────────

def create_slug(text: str) -> str:
    """
    Creates a URL-friendly slug from a string using precompiled regex patterns.
    Replaces non-alphanumeric characters (excluding underscore and hyphen) with underscores,
    and cleans up multiple consecutive underscores.
    """
    if not isinstance(text, str):
        app_logger.warning(f"Attempted to create slug from non-string type: {type(text)}")
        return ""

    slug: str = text.strip().lower()  # Strip whitespace and convert to lowercase

    # Use the precompiled regex for substitution of non-alphanumeric chars
    slug = SLUG_NON_ALPHANUMERIC_REGEX.sub('_', slug)

    # Remove leading/trailing underscores that might result from substitution
    slug = slug.strip('_')

    # Use the precompiled regex for cleaning up multiple consecutive underscores
    slug = SLUG_MULTIPLE_UNDERSCORE_REGEX.sub('_', slug)

    return slug


def fetch_scryfall_image_uri(card_name: str) -> str:
    """Fetches the image URI for a card from the Scryfall API using the session."""
    configure_scryfall_session()
    settings = get_settings()
    if not card_name:
        app_logger.warning("Attempted to fetch Scryfall URI with empty card name.")
        # Access PLACEHOLDER_IMAGE_URL from the settings object
        return settings.PLACEHOLDER_IMAGE_URL

    # Use quote from requests.utils for proper URL encoding
    url: str = f"https://api.scryfall.com/cards/named?exact={quote(card_name)}"
    app_logger.debug(f"Fetching Scryfall URI for '{card_name}' from {url}")

    try:
        # Use the configured session for the GET request
        resp: requests.Response = scryfall_session.get(url, timeout=15)
        resp.raise_for_status()  # Raise an HTTPError for bad responses (4xx or 5xx)
        data: Dict[str, Any] = resp.json()

        # Prioritize 'normal', then 'large', then 'small' image URIs
        # Also handle 'card_faces' for double-faced cards
        uris: Dict[str, str] = data.get('image_uris') or (
                data.get('card_faces') and data['card_faces'][0].get('image_uris')) or {}
        image_uri: str = uris.get('normal') or uris.get('large') or uris.get('small') or ''

        if not image_uri:
            app_logger.warning(
                f"No image URI found in Scryfall response for '{card_name}'. Response keys: {uris.keys() if uris else 'None'}")

        return image_uri

    except requests.exceptions.Timeout:
        app_logger.error(f"Scryfall API request timed out for '{card_name}'.")
        # Access PLACEHOLDER_IMAGE_URL from the settings object
        return settings.PLACEHOLDER_IMAGE_URL
    except requests.exceptions.RequestException as err:
        # This will catch HTTPError (from raise_for_status) and other request-related errors
        app_logger.error(f"Scryfall API request error for '{card_name}': {err}")
        # Access PLACEHOLDER_IMAGE_URL from the settings object
        return settings.PLACEHOLDER_IMAGE_URL
    except json.JSONDecodeError:
        app_logger.error(f"Failed to decode JSON response from Scryfall for '{card_name}'.")
        # Access PLACEHOLDER_IMAGE_URL from the settings object
        return settings.PLACEHOLDER_IMAGE_URL
    except Exception as err:
        app_logger.error(f"An unexpected error occurred fetching Scryfall URI for '{card_name}': {err}")
        # Access PLACEHOLDER_IMAGE_URL from the settings object
        return settings.PLACEHOLDER_IMAGE_URL


# ─── Lazy-caching helper: return cached image path or fetch & cache on demand ───
def fetch_image_url(card_name: str) -> str:
    """Returns the local URL for a card image, fetching and caching if necessary."""
    # Ensure directory exists before trying to save, although it should be created on module load
    settings = get_settings()
    ensure_image_cache_dir_exists()  # Added defensive call

    if not card_name:
        app_logger.warning("Attempted to fetch image URL for empty card name.")
        # Access PLACEHOLDER_IMAGE_URL from the settings object
        return settings.PLACEHOLDER_IMAGE_URL

    slug: str = create_slug(card_name)
    if not slug:
        app_logger.warning(f"Could not create slug for card name '{card_name}'.")
        # Access PLACEHOLDER_IMAGE_URL from the settings object
        return settings.PLACEHOLDER_IMAGE_URL

    filename: str = f"{slug}.jpg"
    # Access IMAGE_CACHE_DIR from the settings object
    filepath: str = os.path.join(settings.IMAGE_CACHE_DIR, filename)

    if os.path.exists(filepath):
        app_logger.debug(f"Serving cached image for '{card_name}' from {filepath}")
        return f"/images/{filename}"

    remote_url: str = fetch_scryfall_image_uri(card_name)
    if remote_url:
        try:
            app_logger.info(f"Lazy-caching image for '{card_name}' from {remote_url}")
            # Use the configured session for the GET request with stream=True for large files
            resp: requests.Response = scryfall_session.get(remote_url, timeout=15, stream=True)
            resp.raise_for_status()  # Raise an HTTPError for bad responses (4xx or 5xx)

            # --- Stream Validation: Check Content-Type before writing ---
            content_type = resp.headers.get('Content-Type', '')
            if not content_type.lower().startswith('image/'):
                app_logger.warning(
                    f"Downloaded content for '{card_name}' from {remote_url} is not an image. Content-Type: {content_type}")
                # Close the response stream
                resp.close()
                # Access PLACEHOLDER_IMAGE_URL from the settings object
                return settings.PLACEHOLDER_IMAGE_URL
            # ----------------------------------------------------------

            with open(filepath, 'wb') as f:
                # Use iter_content to efficiently download large files
                for chunk in resp.iter_content(chunk_size=8192):
                    # Filter out keep-alive chunks
                    if chunk:
                        f.write(chunk)
            app_logger.info(f"Successfully cached image for '{card_name}' to {filepath}")
            return f"/images/{filename}"
        except requests.exceptions.RequestException as err:
            # This will catch HTTPError (from raise_for_status) and other request-related errors,
            # including those caught by the retry strategy if retries are exhausted.
            app_logger.error(f"Failed to lazy-cache '{card_name}' from {remote_url}: {err}")
        except IOError as err:
            app_logger.error(f"Failed to write lazy-cached image file for '{card_name}' to {filepath}: {err}")
        except Exception as err:
            app_logger.error(f"An unexpected error occurred during lazy-caching for '{card_name}': {err}")

    app_logger.warning(f"Could not provide image for card '{card_name}'. Returning placeholder.")
    return settings.PLACEHOLDER_IMAGE_URL
