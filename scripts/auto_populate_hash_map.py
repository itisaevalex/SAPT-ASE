#!/usr/bin/env python
"""
Automatically populates the dimer_hash_map.yml based on files in s22_split.

Assumes generate_hash_map_skeleton.py has already been run to create
a dimer_hash_map.yml with hashes from the database and "PLEASE_FILL_ME_IN" values.

This script will:
1. Load the existing dimer_hash_map.yml.
2. Iterate through files in S22_SPLIT_DIR.
3. For each dimer system (_a.xyz and _b.xyz files):
    a. Read their XYZ content.
    b. Concatenate and compute the MD5 hash.
    c. Derive the canonical dimer name from the s22_split filename.
    d. If the hash exists in the loaded map, update its value.
4. Save the updated map back to dimer_hash_map.yml.
"""

import pathlib
import hashlib
import yaml
import os
import re
from collections import defaultdict

# Configuration
# Assuming script is in 'scripts', map in 'data', s22_split in 'data/s22_split'
MAP_FILE = pathlib.Path("..", "data", "dimer_hash_map.yml").resolve()
S22_SPLIT_DIR = pathlib.Path("..", "data", "s22_split").resolve()

TARGET_PRECISION = 7 # Number of decimal places to round coordinates to

def parse_xyz_string(xyz_string: str) -> list[tuple[str, float, float, float]]:
    """Parses a string block of XYZ coordinates into a list of (atom_symbol, x, y, z)."""
    coordinates = []
    lines = xyz_string.strip().split('\n')
    for line in lines:
        parts = line.strip().split()
        if len(parts) == 4:
            try:
                atom = parts[0]
                x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
                coordinates.append((atom, x, y, z))
            except ValueError:
                # Skip lines that don't parse correctly (e.g., potential headers or empty lines)
                pass # Or log a warning
        elif len(parts) == 1 and parts[0].isdigit(): # Handle potential atom count line if not stripped by get_xyz_content
            pass
        elif not parts: # Empty line
            pass
        # else: print(f"Skipping unparsable line: {line}") # For debugging
    return coordinates

def format_coords_to_canonical_string(coordinates: list[tuple[str, float, float, float]], precision: int) -> str:
    """Formats parsed coordinates to a canonical string representation, with specified precision."""
    lines = []
    # Optional: Sort by atom symbol then by x,y,z to make atom order consistent, though complex for true canonicalization
    # For now, assume atom order from file/DB is preserved for hashing unless proven problematic.
    # coordinates.sort() # This would sort by atom symbol, then x, then y, then z.
    for atom, x, y, z in coordinates:
        # Format to specified precision, ensuring consistent string representation
        # Example: f"{atom:<3s} {x:>12.{precision}f} {y:>12.{precision}f} {z:>12.{precision}f}"
        # Simpler fixed format for now to avoid too many f-string issues with width for hashing
        line = f"{atom} {x:.{precision}f} {y:.{precision}f} {z:.{precision}f}"
        lines.append(line)
    return "\n".join(lines)

def get_processed_xyz_content(filepath: pathlib.Path, precision: int) -> str:
    """Reads an XYZ file, parses coordinates, rounds them, and returns a canonical string representation."""
    with open(filepath, 'r', encoding='utf-8') as f:
        full_content = f.read()
    
    parsed_coords = parse_xyz_string(full_content)
    if not parsed_coords:
        # Attempt to see if the first line is atom count and second is comment, then parse rest
        lines = full_content.strip().split('\n')
        if len(lines) > 2 and lines[0].strip().isdigit():
            parsed_coords = parse_xyz_string("\n".join(lines[2:]))

    return format_coords_to_canonical_string(parsed_coords, precision)

def main():
    if not MAP_FILE.exists():
        print(f"ERROR: Map file not found at {MAP_FILE}")
        print("Please run generate_hash_map_skeleton.py first.")
        return

    if not S22_SPLIT_DIR.exists() or not S22_SPLIT_DIR.is_dir():
        print(f"ERROR: S22_SPLIT_DIR not found or not a directory at {S22_SPLIT_DIR}")
        return

    with open(MAP_FILE, 'r', encoding='utf-8') as f_yaml:
        db_hash_to_name_map = yaml.safe_load(f_yaml)

    if not db_hash_to_name_map:
        print(f"Map file {MAP_FILE} is empty or invalid.")
        return

    print(f"Loaded {len(db_hash_to_name_map)} hashes from {MAP_FILE}")

    s22_files = list(S22_SPLIT_DIR.glob("*.xyz"))
    monomer_files = defaultdict(dict)

    # Group _a.xyz and _b.xyz files by their base name
    # e.g. 01_Helium_dimer_a.xyz -> base_name = 01_Helium_dimer
    for f_path in s22_files:
        match_a = re.match(r"(.+)_a\.xyz$", f_path.name, re.IGNORECASE)
        match_b = re.match(r"(.+)_b\.xyz$", f_path.name, re.IGNORECASE)
        
        base_name = None
        monomer_type = None

        if match_a:
            base_name = match_a.group(1)
            monomer_type = 'a'
        elif match_b:
            base_name = match_b.group(1)
            monomer_type = 'b'
        
        if base_name and monomer_type:
            monomer_files[base_name][monomer_type] = f_path

    updated_count = 0
    still_to_fill_count = 0
    s22_hashes_not_in_db = defaultdict(str)

    print(f"Found {len(monomer_files)} potential dimer systems in {S22_SPLIT_DIR}")

    for canonical_name_base, files in monomer_files.items():
        if 'a' in files and 'b' in files:
            file_a = files['a']
            file_b = files['b']

            try:
                # Process s22_split files to match target precision
                xyz_a_processed_content = get_processed_xyz_content(file_a, TARGET_PRECISION)
                xyz_b_processed_content = get_processed_xyz_content(file_b, TARGET_PRECISION)
                if not xyz_a_processed_content or not xyz_b_processed_content:
                    print(f"Warning: Could not parse/process XYZ for {canonical_name_base}. Skipping.")
                    continue
            except Exception as e:
                print(f"Warning: Error processing XYZ files for {canonical_name_base}: {e}")
                continue
            
            # `generate_hash_map_skeleton.py` now creates hashes for the YAML key via direct concatenation of DB strings.
            # We assume those DB strings effectively represent coordinates at TARGET_PRECISION.
            # For s22_split files, we process them to match this assumed DB precision and format,
            # and then directly concatenate these processed strings for hashing.
            combo_s22_processed_concatenated = xyz_a_processed_content + xyz_b_processed_content
            s22_file_hash = hashlib.md5(combo_s22_processed_concatenated.encode('utf-8')).hexdigest()

            if s22_file_hash in db_hash_to_name_map:
                if db_hash_to_name_map[s22_file_hash] == "PLEASE_FILL_ME_IN":
                    db_hash_to_name_map[s22_file_hash] = canonical_name_base
                    updated_count += 1
                    print(f"  Matched DB hash {s22_file_hash} to s22_split: {canonical_name_base}")
                elif db_hash_to_name_map[s22_file_hash] != canonical_name_base:
                    print(f"  Warning: DB hash {s22_file_hash} already mapped to '{db_hash_to_name_map[s22_file_hash]}', but s22_split suggests '{canonical_name_base}'. Check manually.")
            else:
                s22_hashes_not_in_db[canonical_name_base] = s22_file_hash
        else:
            print(f"Warning: Missing monomer_a or monomer_b for {canonical_name_base} in {S22_SPLIT_DIR}")

    # Count remaining PLEASE_FILL_ME_IN
    for h_val in db_hash_to_name_map.values():
        if h_val == "PLEASE_FILL_ME_IN":
            still_to_fill_count +=1

    print(f"\n--- Summary ---")
    print(f"Updated {updated_count} entries in the hash map.")
    if still_to_fill_count > 0:
        print(f"{still_to_fill_count} entries in the map still need manual labeling ('PLEASE_FILL_ME_IN').")
    else:
        print("All entries in the hash map appear to be populated.")

    if s22_hashes_not_in_db:
        print("\nThe following S22 systems' XYZ hashes were not found in the database-derived map (dimer_hash_map.yml):")
        for name, h in s22_hashes_not_in_db.items():
            print(f"  - {name} (Hash: {h})")

    try:
        with MAP_FILE.open("w", encoding='utf-8') as f_yaml:
            yaml.safe_dump(db_hash_to_name_map, f_yaml, sort_keys=True)
        print(f"Successfully saved updated map to: {MAP_FILE}")
    except Exception as e:
        print(f"ERROR: Could not write updated YAML mapping file {MAP_FILE}: {e}")

if __name__ == "__main__":
    main()
