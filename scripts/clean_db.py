import argparse
from pathlib import Path

from saptase.core.logdb import LogDb


def clean_database(db_path: str):
    """Clean a database by removing duplicates and failed tasks."""
    db_path = Path(db_path)
    if not db_path.exists():
        print(f"Error: Database file {db_path} does not exist!")
        return

    print(f"Cleaning database: {db_path}")
    logdb = LogDb(db_path)

    # Remove duplicates, keeping the newest entries
    removed_ids = logdb.deduplicate_tasks(overwrite=True)
    print(f"Removed {len(removed_ids)} duplicate entries")

    # Clean up failed tasks
    failed_removed = logdb.delete_failed_tasks()
    print(f"Removed {failed_removed} failed tasks")

    # Vacuum the database to reclaim space
    logdb.vacuum_db()
    print("Database vacuumed")

    logdb.close()


def main():
    parser = argparse.ArgumentParser(
        description="Clean a SAPT database by removing duplicates and failed tasks."
    )
    parser.add_argument("db_path", help="Path to the SQLite database file to clean")
    args = parser.parse_args()

    clean_database(args.db_path)


if __name__ == "__main__":
    main()
