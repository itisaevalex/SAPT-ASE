-- scripts/migrations/002_backfill_actual_basis.sql
UPDATE task_log
SET actual_basis_set = basis_set
WHERE actual_basis_set IS NULL; 