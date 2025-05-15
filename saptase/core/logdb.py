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
        self.db_path = Path(db_path)
        self.wal_mode = wal_mode
        self.conn: Optional[sqlite3.Connection] = None
        self.cursor: Optional[sqlite3.Cursor] = None
        self._closed = False  # For idempotent close

        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.error(f"Failed to create directory for database {self.db_path.parent}: {e}")
            return  # Cannot proceed

        try:
            self._connect_and_initialize_db()
            logger.info(f"Connected to provenance database: {self.db_path}")
        except sqlite3.DatabaseError as e:
            # Check if it's a corruption error
            if "malformed" in str(e).lower() or "corrupt" in str(e).lower():
                self._recover_from_corruption(e)
            else:
                logger.critical(
                    f"Unexpected DatabaseError connecting to {self.db_path}: {e}", exc_info=True
                )
                self._safe_close()  # Ensure resources are released
                # Propagate or handle as a critical failure
                raise
        except Exception as general_exc:  # Catch any other unexpected error during init
            logger.critical(
                f"Unexpected error during LogDb initialization for {self.db_path}: {general_exc}",
                exc_info=True,
            )
            self._safe_close()
            raise  # Or handle as appropriate

    def _connect_and_initialize_db(self):
        """Internal helper to connect, setup WAL/timeout, and initialize schema."""
        # Ensure any previous connection is closed before re-attempting
        self._safe_close()
        self._closed = False  # Reset closed state

        try:
            self.conn = sqlite3.connect(self.db_path, isolation_level=None)  # Autocommit
            self.cursor = self.conn.cursor()

            if self.wal_mode:
                self.cursor.execute("PRAGMA journal_mode=WAL;")
                journal_mode = self.cursor.execute("PRAGMA journal_mode;").fetchone()
                if not (journal_mode and journal_mode[0].lower() == "wal"):
                    logger.warning(
                        f"Could not enable WAL journal mode for {self.db_path}. Current mode: {journal_mode[0]}. Concurrency issues might occur."
                    )

            self.cursor.execute("PRAGMA busy_timeout=10000;")
            self._initialize_schema()  # Renamed from _initialize_db for clarity
        except sqlite3.Error as e:
            logger.error(f"Error during database connection or initial setup: {e}")
            self._safe_close()  # Clean up on error
            raise  # Re-raise to be caught by __init__ or caller

    def _recover_from_corruption(self, original_exception: sqlite3.DatabaseError):
        """Handles database corruption by backing up the old file and creating a new one."""
        logger.error(
            f"Database file {self.db_path} appears corrupt or malformed: {original_exception}. Attempting recovery..."
        )
        self._safe_close()  # Ensure connection related to corrupt DB is closed

        backup_path = self.db_path.with_suffix(f"{self.db_path.suffix}.bak_{int(time.time())}")
        try:
            logger.warning(f"Renaming corrupt database to {backup_path}")
            if backup_path.exists():  # Should be rare
                logger.warning(f"Backup file {backup_path} already exists. Removing before rename.")
                backup_path.unlink()
            self.db_path.rename(backup_path)

            logger.info(f"Attempting to create a fresh database at {self.db_path}")
            self._connect_and_initialize_db()  # Try to connect and init the new DB
            logger.info(f"Successfully created and connected to new database: {self.db_path}")
        except OSError as rename_err:
            logger.critical(
                f"Failed to rename corrupt database {self.db_path} to {backup_path}: {rename_err}. Cannot log provenance.",
                exc_info=True,
            )
            # Mark as unusable
            self.conn = None
            self.cursor = None
            self._closed = True
            raise ConnectionError(
                f"Failed to recover from DB corruption for {self.db_path}"
            ) from rename_err
        except sqlite3.Error as second_conn_err:
            logger.critical(
                f"Failed to connect/initialize new database {self.db_path} after corruption recovery: {second_conn_err}",
                exc_info=True,
            )
            self.conn = None
            self.cursor = None
            self._closed = True
            raise ConnectionError(
                f"Failed to initialize new DB after corruption for {self.db_path}"
            ) from second_conn_err
        except Exception as recovery_exc:
            logger.critical(
                f"Unexpected error during database corruption recovery: {recovery_exc}",
                exc_info=True,
            )
            self.conn = None
            self.cursor = None
            self._closed = True
            raise ConnectionError(
                f"Unexpected error during DB recovery for {self.db_path}"
            ) from recovery_exc

    def _initialize_schema(self):  # Renamed from _initialize_db
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

    def __enter__(self):
        """Enter the runtime context related to this object."""
        if self._closed or not self.conn:  # If init failed or already closed
            # Try to re-establish connection if it makes sense for your use case
            # For now, let's assume __init__ must succeed or it's an error to re-enter
            logger.warning(
                f"LogDb context entered but connection for {self.db_path} is not active or was closed."
            )
            # Optionally, could try self._connect_and_initialize_db() again if appropriate
            # but this might hide issues if __init__ failed critically.
            # If __init__ failed, conn might be None.
            if not self.conn:
                raise sqlite3.OperationalError(
                    f"Cannot enter context, LogDb for {self.db_path} was not properly initialized or is closed."
                )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit the runtime context related to this object, ensuring DB connection is closed."""
        self.close()

    def _safe_close(self):
        """Internal helper to close connection and cursor without raising new errors during cleanup."""
        if self.cursor:
            try:
                self.cursor.close()
            except sqlite3.Error as e:
                logger.debug(f"Error closing cursor for {self.db_path} (suppressed): {e}")
            finally:
                self.cursor = None
        if self.conn:
            try:
                self.conn.close()
            except sqlite3.Error as e:
                logger.debug(f"Error closing connection for {self.db_path} (suppressed): {e}")
            finally:
                self.conn = None
        self._closed = True

    def close(self):
        """Close the database connection if it's open. Idempotent."""
        if not self._closed and self.conn:
            logger.info(f"Closing provenance database connection: {self.db_path}")
            self._safe_close()
        # else:
        # logger.debug(f"Connection to {self.db_path} already closed or never opened.")

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

    def deduplicate_tasks(self, overwrite: bool = False) -> list[int]:
        """Identify and remove duplicate task results from the task_log table.

        Duplicates are identified by a canonical key comprising:
        monomer_a_xyz, monomer_b_xyz, COALESCE(actual_basis_set, basis_set), method.
        Corresponding entries in the 'results' table are also removed.

        Args:
            overwrite: If False (default), keeps the OLDEST (smallest log_id) entry
                       among duplicates and removes newer ones.
                       If True, keeps the NEWEST (largest log_id) entry among
                       duplicates and removes older ones.

        Returns:
            A list of log_ids removed from task_log.
        """
        if not self.conn or not self.cursor:
            logger.error("Database not connected, cannot perform deduplication.")
            return []  # Return empty list

        removed_log_ids_from_task_log: list[int] = []  # Store removed log_ids
        try:
            # Define the canonical key fields, using COALESCE for basis set
            key_fields_for_select = [
                "monomer_a_xyz",
                "monomer_b_xyz",
                "COALESCE(actual_basis_set, basis_set) AS effective_basis",
                "method",
            ]
            key_fields_for_group_by = [
                "monomer_a_xyz",
                "monomer_b_xyz",
                "effective_basis",
                "method",
            ]  # Use alias for GROUP BY

            # Fields to use in WHERE clauses (without alias for COALESCE)

            select_key_fields_str = ", ".join(key_fields_for_select)
            group_by_key_fields_str = ", ".join(key_fields_for_group_by)

            # Find all unique canonical keys that have duplicates
            # Note: SQLite might require the COALESCE expression directly in GROUP BY if alias isn't recognized there in all versions.
            # Using the alias `effective_basis` should be fine for modern SQLite.
            self.cursor.execute(
                f"""
                SELECT {select_key_fields_str}, COUNT(*) as count
                FROM task_log
                GROUP BY {group_by_key_fields_str}
                HAVING COUNT(*) > 1
            """
            )
            duplicate_groups = self.cursor.fetchall()

            if not duplicate_groups:
                logger.info(f"No duplicate groups found to process. Overwrite={overwrite}.")
                return []  # Return empty list

            for group_key_values_with_count in duplicate_groups:
                # group_key_values are (monomer_a_xyz, monomer_b_xyz, effective_basis, method)
                group_key_values = group_key_values_with_count[:-1]  # Exclude count

                # Construct WHERE clause for selecting all tasks in this duplicate group
                [
                    "monomer_a_xyz IS ?" if group_key_values[0] is None else "monomer_a_xyz = ?",
                    "monomer_b_xyz IS ?" if group_key_values[1] is None else "monomer_b_xyz = ?",
                    # For effective_basis, we need to check both actual_basis_set and basis_set matching the COALESCE logic
                    "( (actual_basis_set IS ? AND basis_set IS ?) OR (actual_basis_set = ? AND actual_basis_set IS NOT NULL) OR (basis_set = ? AND actual_basis_set IS NULL) )",
                    "method IS ?" if group_key_values[3] is None else "method = ?",
                ]

                # Parameters for the WHERE clause based on the group_key_values
                # group_key_values[0] = monomer_a_xyz
                # group_key_values[1] = monomer_b_xyz
                # group_key_values[2] = effective_basis (from COALESCE)
                # group_key_values[3] = method
                [
                    group_key_values[0],
                    group_key_values[1],
                    # Params for COALESCE logic:
                    group_key_values[
                        2
                    ],  # actual_basis_set IS effective_basis (when basis_set IS also effective_basis, handles NULL actual_basis_set correctly)
                    group_key_values[
                        2
                    ],  # basis_set IS effective_basis (when actual_basis_set IS effective_basis)
                    group_key_values[
                        2
                    ],  # actual_basis_set = effective_basis (actual_basis_set IS NOT NULL case)
                    group_key_values[
                        2
                    ],  # basis_set = effective_basis (actual_basis_set IS NULL case)
                    group_key_values[3],
                ]

                # Refine parameter list to remove Nones if "IS ?" was used, or adjust based on exact SQL needs for COALESCE matching
                # This part is tricky. Let's simplify the WHERE to directly use COALESCE.
                where_clauses_for_coalesce = [
                    (
                        f"{key_fields_for_group_by[0]} IS ?"
                        if group_key_values[0] is None
                        else f"{key_fields_for_group_by[0]} = ?"
                    ),
                    (
                        f"{key_fields_for_group_by[1]} IS ?"
                        if group_key_values[1] is None
                        else f"{key_fields_for_group_by[1]} = ?"
                    ),
                    (
                        "COALESCE(actual_basis_set, basis_set) IS ?"
                        if group_key_values[2] is None
                        else "COALESCE(actual_basis_set, basis_set) = ?"
                    ),
                    (
                        f"{key_fields_for_group_by[3]} IS ?"
                        if group_key_values[3] is None
                        else f"{key_fields_for_group_by[3]} = ?"
                    ),
                ]
                where_clause_str = " AND ".join(where_clauses_for_coalesce)
                # Params for the simplified WHERE clause using group_key_values directly
                current_params_for_where = [val for val in group_key_values]

                order_by_log_id = "ASC" if not overwrite else "DESC"
                self.cursor.execute(
                    f"""
                    SELECT log_id FROM task_log
                    WHERE {where_clause_str}
                    ORDER BY timestamp_utc {order_by_log_id}, log_id {order_by_log_id}
                    LIMIT 1
                """,
                    current_params_for_where,
                )

                row_to_keep_tuple = self.cursor.fetchone()
                if not row_to_keep_tuple:
                    logger.warning(
                        f"Could not determine row to keep for group {group_key_values}, skipping."
                    )
                    continue
                log_id_to_keep = row_to_keep_tuple[0]

                # Fetch log_id, run_id, and task_id of rows to be deleted from task_log
                params_for_select_deleted = (*current_params_for_where, log_id_to_keep)
                self.cursor.execute(
                    f"""
                    SELECT log_id, run_id, task_id FROM task_log
                    WHERE {where_clause_str} AND log_id != ?
                """,
                    params_for_select_deleted,
                )
                rows_to_delete_info = self.cursor.fetchall()

                deleted_from_results_count = 0
                current_group_removed_log_ids = []

                for log_id_del, run_id_del, task_id_del in rows_to_delete_info:
                    current_group_removed_log_ids.append(log_id_del)
                    # Delete from 'results' table first
                    self.cursor.execute(
                        """
                        DELETE FROM results
                        WHERE run_id = ? AND task_id = ?
                          AND NOT EXISTS (SELECT 1 FROM task_log tl WHERE tl.run_id = results.run_id AND tl.task_id = results.task_id AND tl.log_id = ?)
                        """,
                        (run_id_del, task_id_del, log_id_del),
                    )
                    if self.cursor.rowcount > 0:
                        logger.debug(
                            f"Deleted from results: run_id={run_id_del}, task_id={task_id_del} (associated with log_id {log_id_del})"
                        )
                        deleted_from_results_count += self.cursor.rowcount

                if deleted_from_results_count > 0:
                    logger.info(
                        f"Removed {deleted_from_results_count} row(s) from 'results' table for duplicate group based on effective key {group_key_values}."
                    )

                # Delete duplicate rows from task_log
                if current_group_removed_log_ids:
                    # Use a placeholder list for executemany or loop
                    placeholders = ", ".join("?" for _ in current_group_removed_log_ids)
                    delete_task_log_query = f"""
                        DELETE FROM task_log
                        WHERE log_id IN ({placeholders})
                    """
                    self.cursor.execute(delete_task_log_query, current_group_removed_log_ids)
                    rows_removed_for_group_task_log = self.cursor.rowcount
                    removed_log_ids_from_task_log.extend(current_group_removed_log_ids)
                    logger.debug(
                        f"Deduplicated group with effective key {group_key_values} in task_log: kept log_id {log_id_to_keep}, removed {rows_removed_for_group_task_log} rows (log_ids: {current_group_removed_log_ids})."
                    )

            if removed_log_ids_from_task_log:  # Check if any IDs were actually collected
                self.conn.commit()  # Commit only if changes were made
                logger.info(
                    f"Successfully removed {len(removed_log_ids_from_task_log)} duplicate rows from task_log. IDs: {removed_log_ids_from_task_log}. Overwrite={overwrite}."
                )
            else:
                logger.info(
                    f"No duplicate rows were identified or removed from task_log based on effective basis. Overwrite={overwrite}."
                )

        except sqlite3.Error as e:
            logger.error(f"Error during deduplication: {e}", exc_info=True)
            if self.conn:
                try:
                    self.conn.rollback()
                except sqlite3.Error as rb_err:
                    logger.error(f"Rollback failed: {rb_err}")
            return []  # Return empty list on error

        return removed_log_ids_from_task_log
