# saptase/core/logdb.py
"""Handles logging task provenance to a SQLite database."""

import logging
import sqlite3
from enum import Enum
from pathlib import Path
from typing import Optional

from .models import SaptResult

logger = logging.getLogger(__name__)

# Connections are opened in *Write-Ahead Logging* (WAL) mode via PRAGMA below.
# This is safe for multi-process concurrency on a single node and improves
# writer throughput compared to the default rollback journal.

# Define the database schema version (for potential future migrations)
SCHEMA_VERSION = "0.1"


class TaskStatus(Enum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class LogDb:
    """Provides an interface to the SQLite provenance database."""

    def __init__(self, db_path: Path = Path("runs/runs.sqlite")):
        """Initialize and connect to the database.

        Args:
            db_path: Path to the SQLite database file.
        """
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)  # Ensure directory exists
        self.conn: Optional[sqlite3.Connection] = None
        self.cursor: Optional[sqlite3.Cursor] = None
        try:
            self.conn = sqlite3.connect(self.db_path, isolation_level=None)  # Autocommit mode
            self.cursor = self.conn.cursor()
            self._initialize_db()
            logger.info(f"Connected to provenance database: {self.db_path}")
        except sqlite3.Error as e:
            logger.error(f"Failed to connect to or initialize database {self.db_path}: {e}")
            self.conn = None
            self.cursor = None

    def _initialize_db(self):
        """Create necessary tables and metadata if they don't exist."""
        if not self.conn or not self.cursor:
            return

        try:
            # Check for schema version table
            self.cursor.execute("PRAGMA table_info(schema_version)")
            if not self.cursor.fetchone():
                self.cursor.execute("CREATE TABLE schema_version (version TEXT PRIMARY KEY)")
                self.cursor.execute(
                    "INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,)
                )
                logger.info("Initialized schema_version table.")

            # Create task_log table if not exists
            self.cursor.execute("PRAGMA table_info(task_log)")
            if not self.cursor.fetchone():
                self.cursor.execute(
                    """
                    CREATE TABLE task_log (
                        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        run_id TEXT NOT NULL,
                        task_id TEXT NOT NULL,       -- Original task ID
                        attempt_number INTEGER NOT NULL,
                        basis_set TEXT,
                        method TEXT,
                        status TEXT NOT NULL,      -- e.g., COMPLETED, FAILED, RETRYING
                        error_message TEXT,    -- Null if success
                        error_code TEXT, -- Store the SaptError class name on failure
                        error_details TEXT, -- Store traceback or context history JSON
                        elapsed_time REAL,     -- Wall time in seconds
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """
                )
                self.cursor.execute("CREATE INDEX idx_run_id ON task_log (run_id)")
                self.cursor.execute("CREATE INDEX idx_task_id ON task_log (task_id)")
                logger.info("Created task_log table and indices.")

            # Check schema version (simple check for now)
            self.cursor.execute("SELECT version FROM schema_version")
            version = self.cursor.fetchone()
            if not version or version[0] != SCHEMA_VERSION:
                logger.warning(
                    f"Database schema version mismatch or missing. Expected '{SCHEMA_VERSION}', found '{version[0] if version else 'None'}'. May cause issues."
                )
                # TODO: Implement schema migration logic if needed

        except sqlite3.Error as e:
            logger.error(f"Database initialization error: {e}")
            raise  # Re-raise to indicate failure

    def log_task_attempt(self, run_id: str, result: SaptResult):
        """Log a task attempt to the database.

        Args:
            run_id: The ID of the current workflow run
            result: The SaptResult containing task outcome details
        """
        if not self.conn or not self.cursor:
            logger.error("Database not connected, cannot log task attempt.")
            return

        # Use TaskStatus enum values for consistency
        status = TaskStatus.COMPLETED.name if result.success else TaskStatus.FAILED.name

        # Get all relevant fields directly from the enriched SaptResult
        attempt_number = getattr(result, "attempt_number", 1)  # Default to 1 if not set
        error_details = getattr(result, "error_details", None)

        try:
            self.cursor.execute(
                """
                INSERT INTO task_log (
                    run_id, task_id, attempt_number, basis_set, method,
                    status, error_message, error_code, error_details, elapsed_time
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    run_id,
                    result.task_id,
                    attempt_number,  # Now properly 1-based in the result
                    result.basis_set,
                    result.method,
                    status,
                    result.error_message if not result.success else None,
                    result.error_code if not result.success else None,
                    error_details,
                    result.elapsed_time,
                ),
            )
            logger.debug(
                f"Logged result for task {result.task_id}, attempt {attempt_number}, status {status}"
            )
        except sqlite3.Error as e:
            logger.error(f"Failed to log task {result.task_id} result to database: {e}")

    # Alias for backward compatibility
    log_task_result = log_task_attempt

    def close(self):
        """Commit changes and close the database connection."""
        if self.conn:
            try:
                # Commit might not be needed in autocommit mode, but good practice
                self.conn.commit()
                self.conn.close()
                logger.info("Provenance database connection closed.")
                self.conn = None
                self.cursor = None
            except sqlite3.Error as e:
                logger.error(f"Error closing database connection: {e}")
