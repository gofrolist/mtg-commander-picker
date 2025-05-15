import json
import logging
import os
import sys
from typing import Tuple, Optional

from flask import Flask, send_from_directory, abort, Response
from flask_cors import CORS
from werkzeug.exceptions import HTTPException
from werkzeug.utils import safe_join

from mtg_commander_picker.config import get_settings, ConfigError
from mtg_commander_picker.routes.api import api_bp, ColorConverter
from mtg_commander_picker.services import google_sheets_service
from mtg_commander_picker.services.sheets import SheetInitializationError

# ─── Setup Logging ───────────────────────────────────────────────────────────────
# Configure basic logging. In a production environment, you'd likely use a
# more sophisticated logging setup (e.g., Gunicorn's logging).
# Moved basicConfig call here to ensure it runs before other loggers are used
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
app_logger = logging.getLogger(__name__)


# ─── Application Factory ─────────────────────────────────────────────────────────

application: Optional[Flask] = None

def create_app(config_object=None) -> Flask:
    """
    An application factory function to create the Flask app.
    Allows for easier testing and configuration management.
    """
    if config_object is None:
        config_object = get_settings()
    # Set the static_folder to 'build' where the React app build resides
    # Use instance_relative_config=True if you plan to use instance config files
    app = Flask(__name__, static_folder="build")

    # Load configuration from the provided config_object (Pydantic settings instance)
    # We don't need app.config.from_object here because we are using the settings object directly
    # app.config.from_object(config_object) # Not strictly necessary with Pydantic settings

    CORS(app)  # Enable CORS for the application

    # Set Flask's logger level based on DEV_MODE from settings
    app.logger.setLevel(logging.DEBUG if config_object.DEV_MODE else logging.INFO)

    # Register the custom ColorConverter with the Flask application's URL map
    app.url_map.converters['color'] = ColorConverter
    app_logger.info("Custom ColorConverter registered with Flask app.")

    # Register the API blueprint
    app.register_blueprint(api_bp)

    # ─── Custom Error Handlers ───────────────────────────────────────────────────────
    # Define error handlers to return standardized JSON responses

    @app.errorhandler(HTTPException)
    # Updated return type hint to use Tuple[Response, int]
    def handle_http_exception(http_exc: HTTPException) -> Tuple[Response, int]:
        """Return JSON instead of HTML for HTTP errors."""
        # start with the correct headers and status code from the error
        response = http_exc.get_response()
        # replace the body with json
        response.data = json.dumps({
            "error": http_exc.description or http_exc.name,  # Use description if available, otherwise name
            "code": http_exc.code
        })
        response.content_type = "application/json"
        app_logger.error(f"HTTP Exception {http_exc.code}: {http_exc.description}")
        # Explicitly return the response and status code as a tuple
        return response, http_exc.code

    # --- Route to serve cached images ---
    @app.route('/images/<path:filename>')
    # Updated return type hint to use Tuple[Response, int]
    # Removed explicit return type hint as we are letting HTTPException propagate
    def serve_image(filename: str): # Removed return type hint
        """
        Serves cached images from the image cache directory securely.
        Relies on werkzeug.utils.safe_join to prevent directory traversal,
        and the HTTPException handler to catch NotFound if traversal is attempted.
        """
        # Use safe_join to prevent directory traversal attacks.
        # safe_join raises werkzeug.exceptions.NotFound for invalid paths.
        # We remove the explicit None check and let the error handler catch NotFound.
        # The filepath variable is not needed here as send_from_directory handles joining internally
        # filepath: Optional[str] = safe_join(settings.IMAGE_CACHE_DIR, filename) # Removed unused assignment

        # send_from_directory is also generally safe, but safe_join adds an extra layer.
        # send_from_directory will also raise NotFound if the file doesn't exist.
        # The HTTPException handler will catch this as well.
        app_logger.info(f"Attempting to serve cached image: {filename}")
        # Access IMAGE_CACHE_DIR from the settings object
        # Allow send_from_directory to raise NotFound if the file is not found
        # The HTTPException handler will then catch it and return 404
        return send_from_directory(config_object.IMAGE_CACHE_DIR, filename) # Removed explicit status code


    # ─── React catch-all (serves index.html) ────────────────────────────────────────
    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    # Updated return type hint to use Tuple[Response, int]
    def serve_react(path: str) -> Tuple[Response, int]:
        """
        Serves the React frontend build's index.html for all routes not
        handled by the API, enabling client-side routing.
        Handles serving static assets from the build directory securely.
        Uses werkzeug.utils.safe_join and send_from_directory to prevent
        directory traversal, and the HTTPException handler for errors.
        """
        app_logger.debug(f"serve_react called with path: {path}")

        # Check if the static folder is set and exists
        if not app.static_folder or not os.path.exists(app.static_folder):
            app_logger.error(
                f"Frontend static folder not found: {app.static_folder}. Ensure the React build is in this directory.")
            # Use abort for standardized error response
            abort(500, description="Frontend build directory not found")

        # Explicitly serve index.html for the root path ('')
        if not path:
            index_path: str = os.path.join(app.static_folder, 'index.html')
            if os.path.exists(index_path) and os.path.isfile(index_path):
                app_logger.debug("Serving index.html for root path.")
                return send_from_directory(app.static_folder, 'index.html'), 200
            else:
                app_logger.error(
                    f"index.html not found in static folder: {app.static_folder}. Frontend build is likely incomplete or missing.")
                abort(500, description="index.html not found in frontend build")

        # For non-root paths, use safe_join and try to serve the specific file
        # Use safe_join to construct the full path to prevent directory traversal
        # safe_join will return None or raise NotFound if the path is invalid/unsafe
        safe_path: Optional[str] = safe_join(app.static_folder, path)

        # If safe_join returns None or if the file doesn't exist at the safe path
        if safe_path is None or not os.path.exists(safe_path):
            # If the specific file is not found or path is unsafe, fall back to index.html
            index_path: str = os.path.join(app.static_folder, 'index.html')
            if os.path.exists(index_path) and os.path.isfile(index_path):
                app_logger.debug(
                    f"File '{path}' not found or unsafe path, attempting to serve index.html for client-side routing.")
                # Explicitly return the response and status code as a tuple (200 OK)
                return send_from_directory(app.static_folder, 'index.html'), 200
            else:
                app_logger.error(
                    f"index.html not found in static folder: {app.static_folder}. Frontend build is likely incomplete or missing.")
                # Use abort for standardized error response
                abort(500, description="index.html not found in frontend build")

        # If safe_join returned a valid path and the file exists, serve it directly
        try:
            app_logger.debug(f"Attempting to serve static file from safe path: {safe_path}")
            # send_from_directory is also generally safe, but safe_join adds an extra layer.
            # send_from_directory will also raise NotFound if the file doesn't exist (though checked above)
            # The HTTPException handler will catch this.
            # We pass the directory and the filename relative to the directory
            return send_from_directory(app.static_folder, path), 200
        except HTTPException as init_err:
            # Re-raise HTTPExceptions so the generic handler can process them.
            app_logger.error(f"HTTPException serving static file {path}: {init_err}")
            raise init_err
        except Exception as serve_error:
            app_logger.error(f"An unexpected error occurred serving static file {path}: {serve_error}")
            # Use abort for standardized error response for other exceptions
            abort(500, description="An unexpected server error occurred serving static file")

    # Initialize the Google Sheets service here, catching potential errors
    # This ensures the service is initialized when the app is created by the factory
    try:
        google_sheets_service.initialize()
    except (ConfigError, SheetInitializationError) as config_exc:
        # Log the critical error but don't exit here.
        # The caller of create_app should handle the exception (e.g., in __main__).
        app_logger.critical(f"Application failed to initialize Google Sheets service: {config_exc}")
        # Re-raise the exception to signal initialization failure
        raise config_exc

    return app  # Return the created Flask app instance


# ─── Global App Instance for WSGI servers and 'flask run' ───────────────────────
# This line calls the factory to create the app instance and makes it available
# at the module level, which is required by tools like 'flask run' and WSGI servers.
if os.environ.get("RUN_ENV") != "TEST":
    try:
        application = create_app()
    except (ConfigError, SheetInitializationError) as e:
        # If initialization fails here, log the error (already done in create_app)
        # and exit the process gracefully.
        sys.exit(1)

# ─── APP LAUNCH (for direct execution) ──────────────────────────────────────────
if __name__ == '__main__':
    try:
        host = "0.0.0.0"
        port = int(os.environ.get("PORT", 8080))
        settings = get_settings()
        application.run(host=host, port=port, debug=settings.DEV_MODE)
    except ConfigError as e:
        app_logger.error(f"Startup failed: {e}")
        sys.exit(1)
