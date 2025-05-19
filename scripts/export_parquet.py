#!/usr/bin/env python3
#  scripts/export_parquet.py
"""
Join task_log + results into a tidy Parquet for analysis.

Examples
--------
python scripts/export_parquet.py \
       --db   runs/combined_runs.sqlite \
       --out  analysis_data/pauling.parquet
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path

import pandas as pd

# ---------------------------  CONFIGURATION FLAGS  ----------------------------
USE_LAST_SUCCESS      = True   # False → first success (attempt_number == 1)
DERIVE_DIMER_ID       = True   # False → skip dimer_id column
RENAME_METHOD_TO_BACKEND = True
# ------------------------------------------------------------------------------

def fetch_meta(conn: sqlite3.Connection) -> pd.DataFrame:
    """Return one row per *successful* task with metadata columns."""
    # --- choose the success-row selection logic --------------------------------
    if USE_LAST_SUCCESS:
        success_clause = """
        log_id IN (SELECT MAX(log_id)
                   FROM task_log
                   WHERE status='COMPLETED'
                   GROUP BY run_id, task_id)
        """
    else:
        success_clause = "status='COMPLETED' AND attempt_number = 1"

    # --- build SELECT list -----------------------------------------------------
    select_cols = [
        "run_id",
        "task_id",
        "COALESCE(actual_basis_set, basis_set) AS basis_set",
        "method",  # will rename to backend later if desired
        "dimer_name"  # Use the new canonical dimer_name from task_log
    ]
    if DERIVE_DIMER_ID is False:
        select_cols.append("monomer_a_xyz")  # keep xyz if you need it

    sql = f"SELECT {', '.join(select_cols)} FROM task_log WHERE {success_clause}"
    df = pd.read_sql_query(sql, conn)

    # -- optional post-processing ----------------------------------------------
    if RENAME_METHOD_TO_BACKEND:
        df = df.rename(columns={"method": "backend"})
    if 'dimer_name' in df.columns:
        df = df.rename(columns={'dimer_name': 'dimer_id'})
    return df

def fetch_energies(conn: sqlite3.Connection) -> pd.DataFrame:
    res = pd.read_sql_query(
        "SELECT run_id, task_id, energies_json FROM results", conn
    )

    # Helper function to transform the single energy dictionary into a list of 
    # {'component': name, 'energy_kcal': value} dicts, which can then be exploded.
    def transform_energy_dict(json_str, run_id, task_id):
        if json_str is None:
            return []
        try:
            energy_data = json.loads(json_str)
            # Ensure it's a dictionary
            if not isinstance(energy_data, dict):
                print(f"Warning: Expected a dictionary for energies_json, but got {type(energy_data)} for task {task_id} in run {run_id}. Skipping.")
                return []
            
            # Convert the dict to a list of {'component': ..., 'energy_kcal': ...}
            transformed_list = []
            for component, energy_kcal in energy_data.items():
                transformed_list.append({'component': component, 'energy_kcal': energy_kcal})
            return transformed_list
            
        except json.JSONDecodeError:
            print(f"Warning: Malformed JSON for task {task_id} in run {run_id}: {json_str[:100]}...")
            return []

    # Apply the transformation and then explode
    # We need run_id and task_id in the lambda to pass to transform_energy_dict for better warnings
    res['energies_list'] = res.apply(
        lambda row: transform_energy_dict(row['energies_json'], row['run_id'], row['task_id']), axis=1
    )
    
    energies_long = res.explode('energies_list')
    
    # Filter out rows where 'energies_list' might be None or not a dict after explosion
    # (e.g., if transform_energy_dict returned an empty list and explode created a row with NaN)
    energies_long = energies_long[energies_long['energies_list'].notna() & 
                                  energies_long['energies_list'].apply(lambda x: isinstance(x, dict))]

    # Now, 'energies_list' contains individual component dictionaries
    # Convert this column of dictionaries into 'component' and 'energy_kcal' columns
    component_series = energies_long['energies_list'].apply(lambda d: d.get('component'))
    energy_series = energies_long['energies_list'].apply(lambda d: d.get('energy_kcal'))

    # Assign these series to new columns in the DataFrame
    final_df = pd.DataFrame({
        'run_id': energies_long['run_id'],
        'task_id': energies_long['task_id'],
        'component': component_series,
        'energy_hartree': energy_series  # Store raw energy as Hartree
    })
    
    return final_df

def main(db: Path, out_: Path):
    out_.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db) as conn:
        meta = fetch_meta(conn)
        energies = fetch_energies(conn)

    df = (
        energies
        .merge(meta, on=["run_id", "task_id"], how="left", validate="m:1")
    )

    # Process basis_set column if it exists and df is not empty
    # Keeping dropna ensures every row has a basis_set and associated metadata,
    # which simplifies downstream analysis as per user requirements.
    df_processed = df
    if not df_processed.empty and 'basis_set' in df_processed.columns:
        df_processed = df_processed.dropna(subset=["basis_set"])
        if not df_processed.empty:
            df_processed = df_processed.astype({"basis_set": "category"})
    
    # Create energy_kcal column from energy_hartree
    if not df_processed.empty and 'energy_hartree' in df_processed.columns:
        HARTREE_TO_KCAL = 627.5095
        df_processed['energy_kcal'] = df_processed['energy_hartree'] * HARTREE_TO_KCAL

    df_processed.to_parquet(out_, index=False)
    print(f"✨  {len(df_processed):,} rows → {out_}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db",  type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    try:
        main(args.db, args.out)
    except Exception as e:
        import traceback
        print("--- FULL TRACEBACK ---")
        print(traceback.format_exc())
        print("--- END TRACEBACK ---")
