from unittest.mock import MagicMock, patch

from saptase.cli import _get_db_path  # If needed for testing _get_db_path directly

# Assuming saptase.cli.main and saptase.cli._get_db_path are accessible
# and LogDb is in saptase.core.logdb
from saptase.cli import main as saptase_main


@patch("saptase.cli.LogDb")  # Patch LogDb where it's used in the cli module
def test_cli_db_vacuum(MockLogDb, tmp_path):
    """Test the 'saptase db vacuum' CLI command."""
    # Arrange
    custom_db_name = "vacuum_test.sqlite"
    custom_db_path = tmp_path / custom_db_name

    mock_logdb_instance = MagicMock()
    MockLogDb.return_value = mock_logdb_instance
    mock_logdb_instance.vacuum_db.return_value = True  # Simulate successful vacuum

    # Act
    saptase_main(["db", "vacuum", "--db-path", str(custom_db_path)])

    # Assert
    MockLogDb.assert_called_once_with(str(custom_db_path))
    mock_logdb_instance.vacuum_db.assert_called_once()
    mock_logdb_instance.close.assert_called_once()


@patch("saptase.cli.LogDb")
def test_cli_db_delete_failed(MockLogDb, tmp_path):
    """Test the 'saptase db delete-failed' CLI command."""
    custom_db_path = tmp_path / "delete_failed_test.sqlite"

    mock_logdb_instance = MagicMock()
    MockLogDb.return_value = mock_logdb_instance
    mock_logdb_instance.delete_failed_tasks.return_value = 5  # Simulate 5 tasks deleted

    saptase_main(["db", "delete-failed", "--db-path", str(custom_db_path)])

    MockLogDb.assert_called_once_with(str(custom_db_path))
    mock_logdb_instance.delete_failed_tasks.assert_called_once()
    mock_logdb_instance.close.assert_called_once()


@patch("saptase.cli.LogDb")
def test_cli_db_deduplicate(MockLogDb, tmp_path):
    """Test the 'saptase db deduplicate' CLI command."""
    custom_db_path = tmp_path / "dedup_test.sqlite"

    mock_logdb_instance = MagicMock()
    MockLogDb.return_value = mock_logdb_instance
    mock_logdb_instance.deduplicate_tasks.return_value = [1, 2, 3]  # Simulate 3 removed IDs

    saptase_main(
        [
            "db",
            "deduplicate",
            "--db-path",
            str(custom_db_path),
            "--overwrite",  # Test with overwrite flag
        ]
    )

    MockLogDb.assert_called_once_with(str(custom_db_path))
    mock_logdb_instance.deduplicate_tasks.assert_called_once_with(overwrite=True)
    mock_logdb_instance.close.assert_called_once()


# Optional: Test _get_db_path directly if its logic is complex
@patch("saptase.cli.load_config")  # Mock if config loading is involved
# @patch('pathlib.Path.exists') # Removed as _get_db_path doesn't use it
@patch("saptase.cli.logger")  # To suppress warnings or check them
def test_get_db_path_logic(mock_logger, mock_load_config, tmp_path):
    """Test the _get_db_path helper function directly."""
    args_mock = MagicMock()

    # Case 1: --db-path provided via args
    args_mock.db_path = str(tmp_path / "args_db.sqlite")
    assert _get_db_path(args_mock, None) == str(tmp_path / "args_db.sqlite")

    # Case 2: db_path from config
    args_mock.db_path = None
    config_mock = {"provenance": {"db_path": str(tmp_path / "config_db.sqlite")}}
    assert _get_db_path(args_mock, config_mock) == str(tmp_path / "config_db.sqlite")

    # Case 3: Default path
    args_mock.db_path = None
    config_mock_no_db = {}
    # Simulate that default_db_path.parent.exists() is true if it's part of _get_db_path logic
    # For current _get_db_path, it doesn't check existence, just returns default string
    default_path = "runs/runs.sqlite"
    assert _get_db_path(args_mock, config_mock_no_db) == default_path
    mock_logger.warning.assert_called_with(
        f"Database path not specified, defaulting to: {default_path}"
    )
