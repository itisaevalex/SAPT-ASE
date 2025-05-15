# saptase/core/logdb.py
"""Handles logging task provenance to a SQLite database."""

import json
import logging
import sqlite3
import time
from enum import Enum
from pathlib import Path
from typing import Optional, Union

from .models import SaptResult

logger = logging.getLogger(__name__)

# Connections are opened in *Write-Ahead Logging* (WAL) mode via PRAGMA below.
# This is safe for multi-process concurrency on a single node and improves
# writer throughput compared to the default rollback journal.

# Define the database schema version (for potential future migrations)
SCHEMA_VERSION = 2


class TaskStatus(Enum):
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class LogDb:
    """Provides an interface to the SQLite provenance database."""

    def __init__(self, db_path: Union[str, Path], wal_mode: bool = True):
        """Initialize and connect to the database.

        Handles potential database corruption by renaming the corrupt file
        and creating a new one.

        Args:
            db_path: Path to the SQLite database file.
            wal_mode: Whether to enable Write-Ahead Logging (WAL) mode.
        """
        self.db_path = Path(db_path)  # Ensure db_path is a Path object
        self.wal_mode = wal_mode
        self.conn: Optional[sqlite3.Connection] = None
        self.cursor: Optional[sqlite3.Cursor] = None

        # Ensure parent directory exists
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(f"Failed to create directory for database {self.db_path.parent}: {e}")
            # Cannot proceed without the directory
            return

        try:
            # First connection attempt
            self._connect_and_initialize()
            logger.info(f"Connected to provenance database: {self.db_path}")

        except sqlite3.DatabaseError as e:
            # Ensure connection is closed if initial attempt failed
            if self.conn:
                try:
                    self.conn.close()
                    logger.debug(
                        "Closed potentially open connection handle before recovery attempt."
                    )
                except sqlite3.Error as close_err:
                    logger.error(f"Error closing failed connection handle: {close_err}")
                finally:
                    self.conn = None  # Ensure it's marked as closed
                    self.cursor = None

            # Check if it's the "malformed" error or similar corruption issue
            if "malformed" in str(e).lower() or "corrupt" in str(e).lower():
                logger.error(
                    f"Database file {self.db_path} appears corrupt or malformed: {e}. Attempting recovery..."
                )
                backup_path = self.db_path.with_suffix(
                    f"{self.db_path.suffix}.bak_{int(time.time())}"
                )  # Add timestamp to avoid collision
                try:
                    logger.warning(f"Renaming corrupt database to {backup_path}")
                    # Ensure the target backup file doesn't exist (unlikely but possible)
                    if backup_path.exists():
                        logger.warning(f"Backup file {backup_path} already exists. Removing.")
                        backup_path.unlink()
                    self.db_path.rename(backup_path)
                    # Second connection attempt (will create a new file)
                    logger.info(f"Attempting to create a fresh database at {self.db_path}")
                    self._connect_and_initialize()
                    logger.info(
                        f"Successfully created and connected to new database: {self.db_path}"
                    )
                except OSError as rename_err:
                    logger.critical(
                        f"Failed to rename corrupt database {self.db_path} to {backup_path}: {rename_err}. Cannot log provenance.",
                        exc_info=True,
                    )
                    # Cannot proceed if rename fails
                    self.conn = None
                    self.cursor = None
                except sqlite3.Error as second_conn_err:
                    logger.critical(
                        f"Failed to connect to or initialize new database {self.db_path} after corruption recovery: {second_conn_err}",
                        exc_info=True,
                    )
                    # Cannot proceed if second connection fails
                    self.conn = None
                    self.cursor = None
                except Exception as recovery_exc:  # Catch any other recovery error
                    logger.critical(
                        f"Unexpected error during database corruption recovery: {recovery_exc}",
                        exc_info=True,
                    )
                    self.conn = None
                    self.cursor = None
            else:
                # If it's a different DatabaseError, log critically and fail
                logger.critical(
                    f"Unexpected DatabaseError connecting to {self.db_path}: {e}", exc_info=True
                )
                self.conn = None
                self.cursor = None
        except sqlite3.Error as e:  # Catch other potential sqlite3 errors during first connect/init
            logger.critical(
                f"Failed to connect to or initialize database {self.db_path}: {e}", exc_info=True
            )
            # Ensure connection is closed if error happened after connect but during init
            if self.conn:
                try:
                    self.conn.close()
                except sqlite3.Error:
                    pass  # Ignore error during close here
            self.conn = None
            self.cursor = None
        except Exception as general_exc:  # Catch any other unexpected error
            logger.critical(
                f"Unexpected error during LogDb initialization for {self.db_path}: {general_exc}",
                exc_info=True,
            )
            if self.conn:
                try:
                    self.conn.close()
                except sqlite3.Error:
                    pass
            self.conn = None
            self.cursor = None

    def _connect_and_initialize(self):
        """Internal helper to connect and setup the DB."""
        # Raises sqlite3.Error on failure
        self.conn = sqlite3.connect(self.db_path, isolation_level=None)  # Autocommit
        self.cursor = self.conn.cursor()

        # Enable WAL mode and set busy-timeout for concurrency safety
        self.cursor.execute("PRAGMA journal_mode=WAL;")
        # Check if WAL mode was set successfully
        journal_mode = self.cursor.execute("PRAGMA journal_mode;").fetchone()
        if journal_mode and journal_mode[0].lower() != "wal":
            logger.warning(
                f"Could not enable WAL journal mode for {self.db_path}. Current mode: {journal_mode[0]}. Concurrency issues might occur."
            )

        self.cursor.execute("PRAGMA busy_timeout=10000;")
        self._initialize_db()  # Create tables if needed

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
                        monomer_a_xyz TEXT,          -- Added for deduplication key
                        monomer_b_xyz TEXT,          -- Added for deduplication key
                        timestamp_utc TEXT,          -- Added for tie-breaking duplicates
                        actual_basis_set TEXT,       -- Basis set finally used, after escalation
                        status TEXT NOT NULL,      -- e.g., COMPLETED, FAILED, RETRYING
                        error_message TEXT,    -- Null if success
                        error_code TEXT, -- Store the SaptError class name on failure
                        error_details TEXT, -- Store traceback or context history JSON
                        elapsed_time REAL,     -- Wall time in seconds
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP -- Original log timestamp
                    )
                """
                )
                self.cursor.execute("CREATE INDEX idx_run_id ON task_log (run_id)")
                self.cursor.execute("CREATE INDEX idx_task_id ON task_log (task_id)")
                logger.info("Created task_log table and indices.")

            # --- New table for successful results --------------------------
            self.cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS results (
                    run_id         TEXT NOT NULL,
                    task_id        TEXT NOT NULL,
                    energies_json  TEXT,
                    PRIMARY KEY (run_id, task_id)
                )
                """
            )
            logger.info("Ensured results table exists.")

            # Check schema version (simple check for now)
            self.cursor.execute("SELECT version FROM schema_version")
            current_version_row = self.cursor.fetchone()
            current_db_version = current_version_row[0] if current_version_row else None
            if str(current_db_version) != str(SCHEMA_VERSION):
                logger.warning(
                    f"Database schema version mismatch. Expected '{SCHEMA_VERSION}', found '{current_db_version}'. May cause issues."
                )
                # TODO: Implement schema migration logic if needed
            # else:
            #    logger.debug(f"Database schema version '{SCHEMA_VERSION}' matches.")

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
        monomer_a_xyz = getattr(result, "monomer_a_xyz", None)
        monomer_b_xyz = getattr(result, "monomer_b_xyz", None)
        timestamp_utc_result = getattr(result, "timestamp_utc", None)
        actual_basis_set = getattr(result, "actual_basis_set", None)

        try:
            self.cursor.execute(
                """
                INSERT INTO task_log (
                    run_id, task_id, attempt_number, basis_set, method,
                    monomer_a_xyz, monomer_b_xyz, timestamp_utc,
                    actual_basis_set, -- Added column
                    status, error_message, error_code, error_details, elapsed_time
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    run_id,
                    result.task_id,
                    attempt_number,  # Now properly 1-based in the result
                    result.basis_set,  # This is the *attempted* basis for this log entry
                    result.method,
                    monomer_a_xyz,
                    monomer_b_xyz,
                    timestamp_utc_result,
                    actual_basis_set,  # Value for new column
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

            # Persist detailed energies only for successful tasks
            if status == "COMPLETED":
                energies_json = json.dumps(getattr(result, "energies", {}))
                self.cursor.execute(
                    """
                    INSERT OR REPLACE INTO results (run_id, task_id, energies_json)
                    VALUES (?, ?, ?)
                    """,
                    (run_id, result.task_id, energies_json),
                )
                logger.debug(
                    f"Persisted energies for successful task {result.task_id} in run {run_id}"
                )

        except sqlite3.Error as e:
            logger.error(f"Failed to log task {result.task_id} result to database: {e}")

    # Alias for backward compatibility
    log_task_result = log_task_attempt

    def fetch_results(self, run_id: str) -> dict[str, dict]:
        """Return {task_id: energies_dict} for a given run."""
        if not self.conn or not self.cursor:
            logger.error("Database not connected, cannot fetch results.")
            return {}
        try:
            with self._connect() as conn:  # Ensure using a valid connection context
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT task_id, energies_json FROM results WHERE run_id = ?",
                    (run_id,),
                )
                # Ensure energies_json is not None before trying to load
                return {
                    tid: json.loads(ej) if ej is not None else {} for tid, ej in cursor.fetchall()
                }
        except sqlite3.Error as e:
            logger.error(f"Failed to fetch results for run_id {run_id}: {e}")
            return {}
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse energies_json for run_id {run_id}: {e}")
            # Potentially return partial results or handle more gracefully
            return {}

    def _connect(self) -> sqlite3.Connection:  # Added type hint for clarity
        """Ensures a valid connection is returned, typically self.conn.

        This is a simplified version. A more robust one might re-establish
        connection if self.conn is None or closed.
        """
        if self.conn is None:
            # This case should ideally be handled by __init__ or a dedicated connect method
            # For now, let's assume if _connect is called, __init__ should have established conn
            # Or, we could try to re-establish:
            # self._connect_and_initialize()
            # if self.conn is None:
            #     raise sqlite3.OperationalError("Failed to establish database connection.")
            logger.warning(
                "Attempting to use _connect when self.conn is None. This might indicate an issue."
            )
            # For the fetch_results, we'll rely on the connection established by __init__
            # This placeholder _connect might need more robust logic if used more broadly.
            # Re-raising to make it clear that connection should exist
            raise sqlite3.OperationalError("Database connection is not available.")
        return self.conn

    def get_task_status(self, task_id: str, run_id: Optional[str] = None) -> Optional[TaskStatus]:
        # This is a simplified stub, actual implementation might query DB
        # For the purpose of this flow, we assume it works or is not critical
        # to the deduplicate logic itself.
        logger.debug(f"get_task_status called for {task_id}, {run_id} - returning None (stub)")
        return None

    def deduplicate(self, overwrite: bool = False) -> int:
        """Identify and remove duplicate task results from the task_log table.

        Duplicates are identified by a canonical key comprising:
        monomer_a_xyz, monomer_b_xyz, basis_set, method.
        Corresponding entries in the 'results' table are also removed.

        Args:
            overwrite: If False (default), keeps the OLDEST (smallest log_id) entry
                       among duplicates and removes newer ones.
                       If True, keeps the NEWEST (largest log_id) entry among
                       duplicates and removes older ones.

        Returns:
            The number of rows removed from task_log.
        """
        if not self.conn or not self.cursor:
            logger.error("Database not connected, cannot perform deduplication.")
            return 0

        total_rows_removed_from_task_log = 0
        try:
            # Define the canonical key fields
            key_fields = ["monomer_a_xyz", "monomer_b_xyz", "basis_set", "method"]
            key_fields_str = ", ".join(key_fields)

            # Find all unique canonical keys that have duplicates
            self.cursor.execute(
                f"""
                SELECT {key_fields_str}, COUNT(*) as count
                FROM task_log
                GROUP BY {key_fields_str}
                HAVING COUNT(*) > 1
            """
            )
            duplicate_groups = self.cursor.fetchall()

            if not duplicate_groups:
                logger.info(f"No duplicate groups found to process. Overwrite={overwrite}.")
                return 0

            for group_key_values in duplicate_groups:
                key_values = group_key_values[:-1]

                where_clauses = []
                for i, field_name in enumerate(key_fields):
                    if key_values[i] is None:
                        where_clauses.append(f"{field_name} IS NULL")
                    else:
                        where_clauses.append(f"{field_name} = ?")
                where_clause_str = " AND ".join(where_clauses)
                params_for_where = tuple(kv for kv in key_values if kv is not None)

                order_by_log_id = "ASC" if not overwrite else "DESC"
                self.cursor.execute(
                    f"""
                    SELECT log_id FROM task_log
                    WHERE {where_clause_str}
                    ORDER BY log_id {order_by_log_id}
                    LIMIT 1
                """,
                    params_for_where,
                )

                row_to_keep = self.cursor.fetchone()
                if not row_to_keep:
                    logger.warning(
                        f"Could not determine row to keep for group {key_values}, skipping."
                    )
                    continue
                log_id_to_keep = row_to_keep[0]

                # Fetch run_id and task_id of rows to be deleted from task_log
                # These are needed to delete corresponding entries from the 'results' table
                params_for_select_deleted = (*params_for_where, log_id_to_keep)
                self.cursor.execute(
                    f"""
                    SELECT run_id, task_id FROM task_log
                    WHERE {where_clause_str} AND log_id != ?
                """,
                    params_for_select_deleted,
                )

                results_to_delete = self.cursor.fetchall()

                deleted_from_results_count = 0
                for run_id_del, task_id_del in results_to_delete:
                    self.cursor.execute(
                        """
                        DELETE FROM results
                        WHERE run_id = ? AND task_id = ?
                    """,
                        (run_id_del, task_id_del),
                    )
                    if self.cursor.rowcount > 0:
                        logger.debug(
                            f"Deleted from results: run_id={run_id_del}, task_id={task_id_del}"
                        )
                        deleted_from_results_count += self.cursor.rowcount

                if deleted_from_results_count > 0:
                    logger.info(
                        f"Removed {deleted_from_results_count} row(s) from 'results' table for duplicate group {key_values}."
                    )

                # Delete duplicate rows from task_log
                params_for_delete_task_log = (*params_for_where, log_id_to_keep)
                delete_task_log_query = f"""
                    DELETE FROM task_log
                    WHERE {where_clause_str} AND log_id != ?
                """
                self.cursor.execute(delete_task_log_query, params_for_delete_task_log)
                rows_removed_for_group_task_log = self.cursor.rowcount
                total_rows_removed_from_task_log += rows_removed_for_group_task_log
                logger.debug(
                    f"Deduplicated group {key_values} in task_log: kept log_id {log_id_to_keep}, removed {rows_removed_for_group_task_log} rows."
                )

            if total_rows_removed_from_task_log > 0:
                self.conn.commit()
                logger.info(
                    f"Successfully removed {total_rows_removed_from_task_log} duplicate rows from task_log. Overwrite={overwrite}."
                )
            else:
                # This case might be hit if duplicate_groups was populated but no rows ended up being deleted
                # (e.g., if row_to_keep was None for all groups, though unlikely)
                logger.info(f"No duplicate rows were removed from task_log. Overwrite={overwrite}.")

        except sqlite3.Error as e:
            logger.error(f"Error during deduplication: {e}", exc_info=True)
            if self.conn:
                try:
                    self.conn.rollback()
                except sqlite3.Error as rb_err:
                    logger.error(f"Rollback failed: {rb_err}")
            return 0

        return total_rows_removed_from_task_log

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
