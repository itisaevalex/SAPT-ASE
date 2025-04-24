"""Ensure LogDb enables WAL mode and busy-timeout automatically."""

import sqlite3

from saptase.core.logdb import LogDb


def test_logdb_wal(tmp_path):
    db_path = tmp_path / "prov.sqlite"

    # First connection via LogDb should set WAL + timeout
    log1 = LogDb(db_path)

    # Second raw sqlite3 connection
    conn2 = sqlite3.connect(db_path)
    cur2 = conn2.cursor()
    cur2.execute("PRAGMA journal_mode;")
    mode = cur2.fetchone()[0].lower()
    assert mode == "wal"

    # Cleanup
    log1.close()
    conn2.close()
