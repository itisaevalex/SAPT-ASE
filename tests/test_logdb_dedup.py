import sqlite3
from pathlib import Path

import pytest
from saptase.core.logdb import LogDb
from saptase.core.models import Molecule, SaptResult, SaptTask

# Define common molecule strings for testing
MOL_A_XYZ = """1
H
H 0.0 0.0 0.0"""

MOL_B_XYZ_1 = """1
H
H 0.0 0.0 0.8"""  # Original

MOL_B_XYZ_2 = """1
F
F 0.0 0.0 0.8"""  # Different molecule

# Define common Molecule objects
MOL_A = Molecule.from_xyz_string(MOL_A_XYZ)
MOL_B_1 = Molecule.from_xyz_string(MOL_B_XYZ_1)
MOL_B_2 = Molecule.from_xyz_string(MOL_B_XYZ_2)


def _insert_dummy_data(db: LogDb):
    """Inserts a mix of unique and duplicate data."""
    # Task 1: Original
    SaptTask(
        id="task1_orig", monomer_a=MOL_A, monomer_b=MOL_B_1, basis_set="sto-3g", method="sapt0"
    )
    result1_orig = SaptResult(
        task_id="task1_orig",
        success=True,
        energies={"total": -1.0},
        basis_set="sto-3g",
        method="sapt0",
        monomer_a_xyz=MOL_A_XYZ,
        monomer_b_xyz=MOL_B_XYZ_1,
        timestamp_utc="2023-01-01T00:00:00Z",
        attempt_number=1,
        elapsed_time=0.1,
    )
    db.log_task_attempt(run_id="run1", result=result1_orig)  # log_id should be 1

    # Task 2: Duplicate of Task 1 (same key: monA, monB, basis, method), newer timestamp & different energy
    SaptTask(id="task2_dup", monomer_a=MOL_A, monomer_b=MOL_B_1, basis_set="sto-3g", method="sapt0")
    result2_dup = SaptResult(
        task_id="task2_dup",
        success=True,
        energies={"total": -1.1},
        basis_set="sto-3g",
        method="sapt0",
        monomer_a_xyz=MOL_A_XYZ,
        monomer_b_xyz=MOL_B_XYZ_1,
        timestamp_utc="2023-01-01T01:00:00Z",
        attempt_number=1,
        elapsed_time=0.1,
    )
    db.log_task_attempt(run_id="run1", result=result2_dup)  # log_id should be 2

    # Task 3: Another Duplicate of Task 1, newest timestamp & different energy
    SaptTask(
        id="task3_newest_dup",
        monomer_a=MOL_A,
        monomer_b=MOL_B_1,
        basis_set="sto-3g",
        method="sapt0",
    )
    result3_newest_dup = SaptResult(
        task_id="task3_newest_dup",
        success=True,
        energies={"total": -1.2},
        basis_set="sto-3g",
        method="sapt0",
        monomer_a_xyz=MOL_A_XYZ,
        monomer_b_xyz=MOL_B_XYZ_1,
        timestamp_utc="2023-01-01T02:00:00Z",
        attempt_number=1,
        elapsed_time=0.1,
    )
    db.log_task_attempt(run_id="run1", result=result3_newest_dup)  # log_id should be 3

    # Task 4: Unique task (different basis set)
    SaptTask(
        id="task4_unique_basis",
        monomer_a=MOL_A,
        monomer_b=MOL_B_1,
        basis_set="6-31g",
        method="sapt0",
    )
    result4_unique_basis = SaptResult(
        task_id="task4_unique_basis",
        success=True,
        energies={"total": -2.0},
        basis_set="6-31g",
        method="sapt0",
        monomer_a_xyz=MOL_A_XYZ,
        monomer_b_xyz=MOL_B_XYZ_1,
        timestamp_utc="2023-01-01T03:00:00Z",
        attempt_number=1,
        elapsed_time=0.1,
    )
    db.log_task_attempt(run_id="run1", result=result4_unique_basis)  # log_id should be 4

    # Task 5: Unique task (different monomer B)
    SaptTask(
        id="task5_unique_monB",
        monomer_a=MOL_A,
        monomer_b=MOL_B_2,
        basis_set="sto-3g",
        method="sapt0",
    )
    result5_unique_monB = SaptResult(
        task_id="task5_unique_monB",
        success=True,
        energies={"total": -3.0},
        basis_set="sto-3g",
        method="sapt0",
        monomer_a_xyz=MOL_A_XYZ,
        monomer_b_xyz=MOL_B_XYZ_2,
        timestamp_utc="2023-01-01T04:00:00Z",
        attempt_number=1,
        elapsed_time=0.1,
    )
    db.log_task_attempt(run_id="run1", result=result5_unique_monB)  # log_id should be 5

    # Total 5 rows initially: 3 are duplicates of each other, 2 are unique.
    # Duplicate set: task1_orig (log_id 1), task2_dup (log_id 2), task3_newest_dup (log_id 3)


@pytest.fixture
def db_with_duplicates(tmp_path: Path) -> LogDb:
    db_path = tmp_path / "test_dedup.sqlite"
    db = LogDb(db_path=db_path)
    _insert_dummy_data(db)
    return db


def get_all_task_ids(db_path: Path) -> set[str]:
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT task_id FROM task_log")
    rows = cursor.fetchall()
    conn.close()
    return {row[0] for row in rows}


def test_deduplicate_keep_oldest(db_with_duplicates: LogDb, tmp_path: Path):
    """Test deduplicate with overwrite=False (default), expecting oldest to be kept."""
    db_path = tmp_path / "test_dedup.sqlite"

    # Initial state: 5 rows
    assert len(get_all_task_ids(db_path)) == 5

    # Deduplicate (keep oldest)
    removed_ids_list = db_with_duplicates.deduplicate_tasks(overwrite=False)

    # 3 duplicates (task1, task2, task3) -> task1 (oldest) kept, task2 & task3 removed.
    # 2 unique rows (task4, task5) remain untouched.
    # Total removed = 2
    assert len(removed_ids_list) == 2

    # Final state: 5 - 2 = 3 rows
    remaining_ids = get_all_task_ids(db_path)
    assert len(remaining_ids) == 3

    # Check that the oldest of the duplicates ('task1_orig') and uniques are present
    assert "task1_orig" in remaining_ids
    assert "task4_unique_basis" in remaining_ids
    assert "task5_unique_monB" in remaining_ids

    # Check that the newer duplicates are gone
    assert "task2_dup" not in remaining_ids
    assert "task3_newest_dup" not in remaining_ids


def test_deduplicate_keep_newest(tmp_path: Path):
    """Test deduplicate with overwrite=True, expecting newest to be kept."""
    # Need a fresh DB for this test to ensure log_ids are predictable
    db_path = tmp_path / "test_dedup_newest.sqlite"
    db = LogDb(db_path=db_path)
    _insert_dummy_data(db)

    # Initial state: 5 rows
    assert len(get_all_task_ids(db_path)) == 5

    # Deduplicate (keep newest)
    removed_ids_list = db.deduplicate_tasks(overwrite=True)

    # 3 duplicates (task1, task2, task3) -> task3 (newest) kept, task1 & task2 removed.
    # 2 unique rows (task4, task5) remain untouched.
    # Total removed = 2
    assert len(removed_ids_list) == 2

    # Final state: 5 - 2 = 3 rows
    remaining_ids = get_all_task_ids(db_path)
    assert len(remaining_ids) == 3

    # Check that the newest of the duplicates ('task3_newest_dup') and uniques are present
    assert "task3_newest_dup" in remaining_ids
    assert "task4_unique_basis" in remaining_ids
    assert "task5_unique_monB" in remaining_ids

    # Check that the older duplicates are gone
    assert "task1_orig" not in remaining_ids
    assert "task2_dup" not in remaining_ids


def test_deduplicate_no_duplicates(tmp_path: Path):
    """Test deduplicate on a DB with no duplicates."""
    db_path = tmp_path / "test_no_dup.sqlite"
    db = LogDb(db_path=db_path)

    # Insert unique data only
    SaptTask(id="task1", monomer_a=MOL_A, monomer_b=MOL_B_1, basis_set="sto-3g", method="sapt0")
    result1 = SaptResult(
        task_id="task1",
        success=True,
        energies={"total": -1.0},
        basis_set="sto-3g",
        method="sapt0",
        monomer_a_xyz=MOL_A_XYZ,
        monomer_b_xyz=MOL_B_XYZ_1,
        attempt_number=1,
        elapsed_time=0.1,
    )
    db.log_task_attempt(run_id="run1", result=result1)

    SaptTask(
        id="task2", monomer_a=MOL_A, monomer_b=MOL_B_1, basis_set="6-31g", method="sapt0"
    )  # Different basis
    result2 = SaptResult(
        task_id="task2",
        success=True,
        energies={"total": -2.0},
        basis_set="6-31g",
        method="sapt0",
        monomer_a_xyz=MOL_A_XYZ,
        monomer_b_xyz=MOL_B_XYZ_1,
        attempt_number=1,
        elapsed_time=0.1,
    )
    db.log_task_attempt(run_id="run1", result=result2)

    assert len(get_all_task_ids(db_path)) == 2

    removed_count_false = db.deduplicate_tasks(overwrite=False)
    assert len(removed_count_false) == 0
    assert len(get_all_task_ids(db_path)) == 2  # Count should not change

    removed_count_true = db.deduplicate_tasks(overwrite=True)
    assert len(removed_count_true) == 0
    assert len(get_all_task_ids(db_path)) == 2  # Count should not change


def test_deduplicate_actual_basis_considered(tmp_path: Path):
    """Test that deduplication correctly uses COALESCE(actual_basis_set, basis_set)."""
    db_path = tmp_path / "test_dedup_actual_basis.sqlite"
    db = LogDb(db_path=db_path)

    # Task 1: Original, basis_set='sto-3g', actual_basis_set=NULL
    SaptTask(
        id="task1_orig_null_actual",
        monomer_a=MOL_A,
        monomer_b=MOL_B_1,
        basis_set="sto-3g",
        method="sapt0",
    )
    result1 = SaptResult(
        task_id="task1_orig_null_actual",
        success=True,
        energies={"total": -1.0},
        basis_set="sto-3g",
        actual_basis_set=None,
        method="sapt0",
        monomer_a_xyz=MOL_A_XYZ,
        monomer_b_xyz=MOL_B_XYZ_1,
        timestamp_utc="2023-01-01T00:00:00Z",
        attempt_number=1,
        elapsed_time=0.1,
    )
    db.log_task_attempt(run_id="run1", result=result1)  # log_id 1

    # Task 2: Duplicate of Task 1 by effective key, basis_set='6-31g', actual_basis_set='sto-3g' (escalated to same as Task1's original)
    # This should be considered a duplicate of Task 1 if effective_basis is 'sto-3g'
    SaptTask(
        id="task2_dup_actual_matches_orig",
        monomer_a=MOL_A,
        monomer_b=MOL_B_1,
        basis_set="6-31g",
        method="sapt0",
    )
    result2 = SaptResult(
        task_id="task2_dup_actual_matches_orig",
        success=True,
        energies={"total": -1.1},
        basis_set="6-31g",
        actual_basis_set="sto-3g",
        method="sapt0",
        monomer_a_xyz=MOL_A_XYZ,
        monomer_b_xyz=MOL_B_XYZ_1,
        timestamp_utc="2023-01-01T01:00:00Z",
        attempt_number=1,
        elapsed_time=0.1,
    )
    db.log_task_attempt(run_id="run1", result=result2)  # log_id 2

    # Task 3: Unique because actual_basis_set is different ('6-31g')
    SaptTask(
        id="task3_unique_actual_differs",
        monomer_a=MOL_A,
        monomer_b=MOL_B_1,
        basis_set="sto-3g",
        method="sapt0",
    )
    result3 = SaptResult(
        task_id="task3_unique_actual_differs",
        success=True,
        energies={"total": -1.2},
        basis_set="sto-3g",
        actual_basis_set="6-31g",
        method="sapt0",  # Effective basis is '6-31g'
        monomer_a_xyz=MOL_A_XYZ,
        monomer_b_xyz=MOL_B_XYZ_1,
        timestamp_utc="2023-01-01T02:00:00Z",
        attempt_number=1,
        elapsed_time=0.1,
    )
    db.log_task_attempt(run_id="run1", result=result3)  # log_id 3

    # Task 4: Duplicate of Task 1 by effective key, basis_set='sto-3g', actual_basis_set='sto-3g'
    SaptTask(
        id="task4_dup_actual_is_orig",
        monomer_a=MOL_A,
        monomer_b=MOL_B_1,
        basis_set="sto-3g",
        method="sapt0",
    )
    result4 = SaptResult(
        task_id="task4_dup_actual_is_orig",
        success=True,
        energies={"total": -1.3},
        basis_set="sto-3g",
        actual_basis_set="sto-3g",
        method="sapt0",  # Effective basis is 'sto-3g'
        monomer_a_xyz=MOL_A_XYZ,
        monomer_b_xyz=MOL_B_XYZ_1,
        timestamp_utc="2023-01-01T03:00:00Z",
        attempt_number=1,
        elapsed_time=0.1,
    )
    db.log_task_attempt(run_id="run1", result=result4)  # log_id 4

    # Initial state: 4 rows
    assert len(get_all_task_ids(db_path)) == 4

    # Deduplicate (keep oldest)
    # Task 1 (effective sto-3g, log_id 1)
    # Task 2 (effective sto-3g, log_id 2)
    # Task 3 (effective 6-31g, log_id 3)
    # Task 4 (effective sto-3g, log_id 4)
    # Expected: Task 1 kept. Task 2 and 4 removed. Task 3 kept.
    removed_log_ids = db.deduplicate_tasks(overwrite=False)
    assert len(removed_log_ids) == 2
    assert sorted(removed_log_ids) == [2, 4]  # log_id 2 and 4 removed

    remaining_ids = get_all_task_ids(db_path)
    assert len(remaining_ids) == 2
    assert "task1_orig_null_actual" in remaining_ids  # Kept (oldest of sto-3g effective)
    assert "task3_unique_actual_differs" in remaining_ids  # Kept (unique 6-31g effective)
    assert "task2_dup_actual_matches_orig" not in remaining_ids
    assert "task4_dup_actual_is_orig" not in remaining_ids

    # Clean up and try overwrite=True
    db.close()
    db_path.unlink()
    db = LogDb(db_path=db_path)
    # _insert_dummy_data(db) # This was causing the issue by adding 5 extra rows

    # Re-inserting the specific 4 tasks for overwrite=True test
    db.log_task_attempt(run_id="run1", result=result1)  # log_id 1 again in new db
    db.log_task_attempt(run_id="run1", result=result2)  # log_id 2
    db.log_task_attempt(run_id="run1", result=result3)  # log_id 3
    db.log_task_attempt(run_id="run1", result=result4)  # log_id 4

    assert len(get_all_task_ids(db_path)) == 4
    # Deduplicate (keep newest)
    # Expected: Task 4 kept. Task 1 and 2 removed. Task 3 kept.
    removed_log_ids_newest = db.deduplicate_tasks(overwrite=True)
    assert len(removed_log_ids_newest) == 2
    # log_ids 1 and 2 should be removed (task1_orig_null_actual, task2_dup_actual_matches_orig)
    assert sorted(removed_log_ids_newest) == [1, 2]

    remaining_ids_newest = get_all_task_ids(db_path)
    assert len(remaining_ids_newest) == 2
    assert "task4_dup_actual_is_orig" in remaining_ids_newest  # Kept (newest of sto-3g effective)
    assert "task3_unique_actual_differs" in remaining_ids_newest  # Kept (unique 6-31g effective)
    assert "task1_orig_null_actual" not in remaining_ids_newest
    assert "task2_dup_actual_matches_orig" not in remaining_ids_newest

    db.close()
