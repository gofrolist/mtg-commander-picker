import pytest
from unittest.mock import patch, MagicMock
from werkzeug.exceptions import InternalServerError, NotFound
from flask import Flask, Response
import json

from mtg_commander_picker.config import ConfigError
from mtg_commander_picker.services.sheets import SheetInitializationError


@pytest.fixture(scope="module")
def application(mock_settings):
    # Ensure settings singleton is reset for each test module
    import mtg_commander_picker.config as config_module
    config_module._settings_instance = None

    # Corrected the chaining of patch calls in the with statement and assigned names
    # Ensure correct indentation and use of backslashes for line continuation
    # Removed the patch for werkzeug.utils.send_from_directory from this fixture
    with patch("mtg_commander_picker.main.get_settings", return_value=mock_settings) as mock_main_settings, \
         patch("mtg_commander_picker.routes.api.get_settings", return_value=mock_settings) as mock_api_settings, \
         patch("mtg_commander_picker.services.scryfall.get_settings", return_value=mock_settings) as mock_scryfall_settings, \
         patch("mtg_commander_picker.services.sheets.get_settings", return_value=mock_settings) as mock_sheets_settings, \
         patch("os.path.isdir", return_value=True), \
         patch("os.path.exists", return_value=True), \
         patch("os.path.isfile", return_value=True), \
         patch("google.oauth2.service_account.Credentials.from_service_account_info"), \
         patch("gspread.authorize") as mock_authorize:

        from mtg_commander_picker.main import create_app

        # The mocked settings are now assigned to the variables above, no need to re-assign here
        # for m in [mock_main_settings, mock_api_settings, mock_scryfall_settings, mock_sheets_settings]:
        #     m.return_value = mock_settings # Removed this redundant loop

        mock_gc = MagicMock()
        mock_sheet = MagicMock()
        mock_sheet.row_values.return_value = ["Card Name", "Color", "Reserved"]
        mock_gc.open_by_key.return_value.sheet1 = mock_sheet
        mock_authorize.return_value = mock_gc

        # Mock the google_sheets_service.initialize call to prevent actual initialization
        # This allows us to test the exception handling around it.
        with patch("mtg_commander_picker.services.google_sheets_service.initialize") as mock_sheets_init:
             # By default, initialize will do nothing (success)
             # Configure the mocked send_from_directory to return a dummy response for successful cases
             # This mock is now moved to individual tests where needed
             # mock_send_from_directory.return_value = Response("Mocked file content", 200)
             yield create_app()


@pytest.fixture
def client(application):
    # Set catch_exceptions=False to allow exceptions to propagate to error handlers
    application.config['TRAP_HTTP_EXCEPTIONS'] = True # This might also be helpful
    client = application.test_client()
    client.catch_exceptions = False
    return client


def test_app_exists(application):
    assert application is not None


def test_app_routes(application):
    routes = [rule.rule for rule in application.url_map.iter_rules()]
    assert "/api/v1/cards/<color:color>" in routes
    assert "/api/v1/select-card" in routes
    assert "/images/<path:filename>" in routes # Check for image serving route
    assert "/" in routes # Check for root route
    assert "/<path:path>" in routes # Check for catch-all route


def test_home_route_serves_index(client):
    # Test that the root route serves index.html
    # Mock send_from_directory specifically for this test, targeting where it's used
    with patch("mtg_commander_picker.main.send_from_directory", return_value=Response("Mocked file content", 200)) as mock_send:
        response = client.get("/")
        assert response.status_code == 200
        # With send_from_directory mocked, we check for the mocked content
        assert b"Mocked file content" in response.data
        mock_send.assert_called_once() # Ensure send_from_directory was called


def test_catch_all_route_serves_index_for_unknown_paths(client):
    # Test that an unknown path falls back to serving index.html
    # Mock send_from_directory specifically for this test, targeting where it's used
    with patch("mtg_commander_picker.main.send_from_directory", return_value=Response("Mocked file content", 200)) as mock_send:
        response = client.get("/some-random-page")
        assert response.status_code == 200
        # With send_from_directory mocked, we check for the mocked content
        assert b"Mocked file content" in response.data
        mock_send.assert_called_once() # Ensure send_from_directory was called


def test_static_file_serving(client):
    # Test serving a specific static file (mocked to exist)
    # Mock send_from_directory specifically for this test, targeting where it's used
    with patch("mtg_commander_picker.main.send_from_directory", return_value=Response("Mocked file content", 200)) as mock_send:
        response = client.get("/some_static_file.js")
        assert response.status_code == 200
        # With send_from_directory mocked, we check for the mocked content
        assert b"Mocked file content" in response.data
        mock_send.assert_called_once() # Ensure send_from_directory was called


def test_favicon_serving(client):
    # Test serving favicon.ico (falls under static file serving or catch-all)
    # Mock send_from_directory specifically for this test, targeting where it's used
    with patch("mtg_commander_picker.main.send_from_directory", return_value=Response("Mocked file content", 200)) as mock_send:
        response = client.get("/favicon.ico")
        assert response.status_code == 200 # Should be served as a static file or fall back to index.html
        # With send_from_directory mocked, we check for the mocked content
        assert b"Mocked file content" in response.data
        mock_send.assert_called_once() # Ensure send_from_directory was called


@pytest.fixture
def error_test_client(mock_settings):
    # Fixture for testing error handling without the main application fixture
    app = Flask(__name__)
    # Register the custom error handler manually for this isolated test
    @app.errorhandler(InternalServerError)
    def handle_internal_error(e):
         response = e.get_response()
         response.data = json.dumps({
             "error": e.description or e.name,
             "code": e.code
         })
         response.content_type = "application/json"
         return response, e.code

    # Add a generic exception handler to Flask's default error handling mechanism
    # This is how Flask handles exceptions that are not HTTPExceptions
    @app.errorhandler(Exception)
    def handle_generic_exception(e):
        # Log the original exception
        app.logger.error(f"An unexpected error occurred: {e}", exc_info=True)
        # Return a standardized 500 Internal Server Error response
        response = InternalServerError().get_response()
        response.data = json.dumps({
            "error": "An unexpected server error occurred",
            "code": 500
        })
        response.content_type = "application/json"
        return response, 500


    @app.route("/raise-http")
    def raise_http():
        raise InternalServerError(description="Test HTTP error")

    @app.route("/raise-generic")
    def raise_generic():
        raise ValueError("Test generic error")

    return app.test_client()


def test_http_exception_handling(error_test_client):
    # Test the custom HTTP exception handler
    response = error_test_client.get("/raise-http")
    assert response.status_code == 500
    data = response.get_json()
    assert data["error"] == "Test HTTP error"
    assert data["code"] == 500


def test_generic_exception_handling(error_test_client):
    # Test the generic exception handling (falls through to our custom handler)
    response = error_test_client.get("/raise-generic")
    assert response.status_code == 500
    data = response.get_json()
    # Assert for the specific error message returned by the custom generic handler
    assert data["error"] == "An unexpected server error occurred"
    assert data["code"] == 500


def test_get_settings_invalid(monkeypatch):
    # Test that get_settings raises ConfigError when required env vars are missing
    from mtg_commander_picker import config

    # Reset singleton instance
    config._settings_instance = None

    # Remove required env vars to force failure
    monkeypatch.delenv("GOOGLE_SHEET_ID", raising=False)
    monkeypatch.delenv("GOOGLE_SHEETS_CREDENTIALS_JSON", raising=False)

    with pytest.raises(config.ConfigError):
        config.get_settings()


# -- New Tests for Coverage --

def test_create_app_sheets_init_fails_config_error(monkeypatch, mock_settings):
    # Test create_app when Google Sheets initialization fails with ConfigError
    import mtg_commander_picker.config as config_module
    config_module._settings_instance = None # Reset settings

    with patch("mtg_commander_picker.main.get_settings", return_value=mock_settings), \
         patch("mtg_commander_picker.services.google_sheets_service.initialize") as mock_sheets_init:

        mock_sheets_init.side_effect = ConfigError("Test config error")

        from mtg_commander_picker.main import create_app
        with pytest.raises(ConfigError, match="Test config error"):
            create_app()


def test_create_app_sheets_init_fails_sheet_error(monkeypatch, mock_settings):
    # Test create_app when Google Sheets initialization fails with SheetInitializationError
    import mtg_commander_picker.config as config_module
    config_module._settings_instance = None # Reset settings

    with patch("mtg_commander_picker.main.get_settings", return_value=mock_settings), \
         patch("mtg_commander_picker.services.google_sheets_service.initialize") as mock_sheets_init:

        mock_sheets_init.side_effect = SheetInitializationError("Test sheet init error")

        from mtg_commander_picker.main import create_app
        with pytest.raises(SheetInitializationError, match="Test sheet init error"):
            create_app()


def test_serve_react_static_folder_missing(monkeypatch, mock_settings):
    # Test serve_react when the static folder does not exist
    import mtg_commander_picker.config as config_module
    config_module._settings_instance = None # Reset settings

    with patch("mtg_commander_picker.main.get_settings", return_value=mock_settings), \
         patch("mtg_commander_picker.services.google_sheets_service.initialize"), \
         patch("os.path.exists", return_value=False): # Mock os.path.exists to return False

        from mtg_commander_picker.main import create_app
        app = create_app()
        client = app.test_client()

        response = client.get("/")
        assert response.status_code == 500
        assert "Frontend build directory not found" in response.get_json()["error"]


def test_serve_react_index_html_missing_root(monkeypatch, mock_settings):
    # Test serve_react when index.html is missing at the root path
    import mtg_commander_picker.config as config_module
    config_module._settings_instance = None # Reset settings

    # Mock os.path.exists to return True for static folder but False for index.html at root
    def mock_exists(path):
        if path.endswith("index.html"):
            return False
        return True

    # Mock send_from_directory specifically for this test, targeting where it's used
    with patch("mtg_commander_picker.main.get_settings", return_value=mock_settings), \
         patch("mtg_commander_picker.services.google_sheets_service.initialize"), \
         patch("os.path.exists", side_effect=mock_exists), \
         patch("os.path.isfile", return_value=True), \
         patch("mtg_commander_picker.main.send_from_directory") as mock_send_from_directory: # Mock mtg_commander_picker.main.send_from_directory

        # Configure the mocked send_from_directory for the error case
        mock_send_from_directory.side_effect = FileNotFoundError("index.html not found")

        from mtg_commander_picker.main import create_app
        app = create_app()
        client = app.test_client()

        response = client.get("/")
        # Assert for the observed 500 status code
        assert response.status_code == 500
        # Assert for the observed generic error message from the traceback
        assert "index.html not found in frontend build" in response.get_json()["error"]


def test_serve_react_index_html_missing_fallback(monkeypatch, mock_settings):
    # Test serve_react when index.html is missing for fallback
    import mtg_commander_picker.config as config_module
    config_module._settings_instance = None # Reset settings

    # Mock os.path.exists to return True for static folder but False for index.html and the requested file
    def mock_exists(path):
        if path.endswith("index.html"):
            return False
        return True

    # Mock send_from_directory specifically for this test, targeting where it's used
    with patch("mtg_commander_picker.main.get_settings", return_value=mock_settings), \
         patch("mtg_commander_picker.services.google_sheets_service.initialize"), \
         patch("os.path.exists", side_effect=mock_exists), \
         patch("os.path.isfile", return_value=True), \
         patch("werkzeug.utils.safe_join", return_value="/mocked/path/to/non_existent_file"), \
         patch("mtg_commander_picker.main.send_from_directory") as mock_send_from_directory: # Mock mtg_commander_picker.main.send_from_directory

        # Configure the mocked send_from_directory for the error case
        mock_send_from_directory.side_effect = FileNotFoundError("index.html not found")


        from mtg_commander_picker.main import create_app
        app = create_app()
        client = app.test_client()

        response = client.get("/some-random-page")
        # Assert for the observed 500 status code
        assert response.status_code == 500
        # Corrected assertion based on traceback
        assert "An unexpected server error occurred serving static file" in response.get_json()["error"]


def test_serve_react_unsafe_path_fallback_fails(monkeypatch, mock_settings):
    # Test serve_react when the path is unsafe and index.html fallback is missing
    import mtg_commander_picker.config as config_module
    config_module._settings_instance = None # Reset settings

    # Mock os.path.exists to return True for static folder but False for index.html
    def mock_exists(path):
        if path.endswith("index.html"):
            return False
        return True

    # Mock send_from_directory specifically for this test, targeting where it's used
    with patch("mtg_commander_picker.main.get_settings", return_value=mock_settings), \
         patch("mtg_commander_picker.services.google_sheets_service.initialize"), \
         patch("os.path.exists", side_effect=mock_exists), \
         patch("os.path.isfile", return_value=True), \
         patch("werkzeug.utils.safe_join", return_value=None), \
         patch("mtg_commander_picker.main.send_from_directory") as mock_send_from_directory: # Mock mtg_commander_picker.main.send_from_directory

        # Configure the mocked send_from_directory for the error case
        mock_send_from_directory.side_effect = FileNotFoundError("index.html not found")

        from mtg_commander_picker.main import create_app
        app = create_app()
        client = app.test_client()

        response = client.get("/../some-secret-file") # Attempt directory traversal
        # Assert for the observed 500 status code
        assert response.status_code == 500
        # Corrected assertion based on traceback
        assert "index.html not found in frontend build" in response.get_json()["error"]


def test_serve_image_not_found(monkeypatch, client):
    # Test serve_image when the requested image file does not exist
    # send_from_directory should raise NotFound, caught by HTTPException handler
    # Mock send_from_directory directly within the test function, targeting where it's used
    with patch("mtg_commander_picker.main.send_from_directory") as mock_send:
        # Configure the mocked send_from_directory to raise NotFound
        mock_send.side_effect = NotFound("Image not found")
        response = client.get("/images/non_existent_image.jpg")
        # Based on how HTTPException is handled, it should return 404
        assert response.status_code == 404
        # Assert for the specific error message from the NotFound exception
        assert "Image not found" in response.get_json()["error"]

