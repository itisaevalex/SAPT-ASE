# tests/test_logdb_actual_basis.py
import sqlite3

from saptase.core.logdb import LogDb
from saptase.core.models import SaptResult


def test_actual_basis_is_saved(tmp_path):
    db_path = tmp_path / "runs.sqlite"
    db = LogDb(db_path)

    res = SaptResult(
        task_id="dummy",
        success=True,
        basis_set="jun-cc-pVDZ",  # requested
        method="sapt0",
        actual_basis_set="def2-SVPD",  # escalated
        energies={"elst": -1.0, "disp": -0.5},
        attempt_number=1,
        elapsed_time=0.1,
    )
    db.log_task_attempt(run_id="runX", result=res)

    with sqlite3.connect(db_path) as con:
        row = con.execute("SELECT actual_basis_set FROM task_log WHERE task_id='dummy'").fetchone()
    assert row and row[0] == "def2-SVPD"
