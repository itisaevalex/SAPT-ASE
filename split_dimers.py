import csv
import math
import os

# Base directories
xyz_dir = os.path.join(
    r"C:\Users\Alex Isaev\Documents\Physics Thesis Automated Multi-Fidelity SAPT(DFT) Workflows\Code\data\s22_xyz"
)
output_dir = os.path.join(
    r"C:\Users\Alex Isaev\Documents\Physics Thesis Automated Multi-Fidelity SAPT(DFT) Workflows\Code\data\s22_split"
)

# Dimer information
dimers = [
    ("2_pyridoxine_2_aminopyridine", "87_2pyridoxine2aminopyridinecomplex.xyz", "-16.71", "HB"),
    ("adenine_thymine_stack", "95_Adeninethyminecomplexstack.xyz", "-12.23", "mix"),
    ("adenine_thymine_watsoncrick", "88_AdeninethymineWatsonCrickcomplex.xyz", "-16.37", "HB"),
    ("ammonia_dimer", "81_Ammoniadimer.xyz", "-3.17", "HB"),
    ("benzene_methane", "83_BenzeneMethanecomplex.xyz", "-1.50", "disp"),
    ("benzene_ammonia", "98_Benzeneammoniacomplex.xyz", "-2.35", "disp"),
    ("benzene_dimer_parallel", "91_Benzenedimerparalleldisplaced.xyz", "-2.73", "disp"),
    ("benzene_dimer_tshape", "100_BenzenedimerTshaped.xyz", "-2.74", "disp"),
    ("benzene_hcn", "99_BenzeneHCNcomplex.xyz", "-4.46", "disp"),
    ("benzene_water", "97_Benzenewatercomplex.xyz", "-3.28", "disp"),
    ("ethene_dimer", "90_Ethenedimer.xyz", "-1.51", "disp"),
    ("ethene_ethyne", "96_Etheneethynecomplex.xyz", "-1.53", "disp"),
    ("formamide_dimer", "85_Formamidedimer.xyz", "-15.96", "HB"),
    ("formic_acid_dimer", "84_Formicaciddimer.xyz", "-18.61", "HB"),
    ("indole_benzene_stack", "94_Indolebenzenecomplexstack.xyz", "-5.22", "mix"),
    ("indole_benzene_tshape", "101_IndolebenzeneTshapecomplex.xyz", "-5.73", "mix"),
    ("methane_dimer", "89_Methanedimer.xyz", "-0.53", "disp"),
    ("phenol_dimer", "102_Phenoldimer.xyz", "-7.05", "HB"),
    ("pyrazine_dimer", "92_Pyrazinedimer.xyz", "-4.42", "mix"),
    ("uracil_dimer_hbonded", "86_Uracildimerhbonded.xyz", "-20.47", "HB"),
    ("uracil_dimer_stack", "93_Uracildimerstack.xyz", "-9.88", "mix"),
    ("water_dimer", "82_Waterdimer.xyz", "-5.02", "HB"),
]


def read_xyz_file(file_path):
    """Read an XYZ file and return the atom count, comment, and atom coordinates."""
    with open(file_path, "r") as f:
        lines = f.readlines()

    num_atoms = int(lines[0].strip())
    comment = lines[1].strip()
    atoms = []

    for i in range(2, 2 + num_atoms):
        parts = lines[i].strip().split()
        if len(parts) >= 4:
            symbol = parts[0]
            x = float(parts[1])
            y = float(parts[2])
            z = float(parts[3])
            atoms.append((symbol, x, y, z))

    return num_atoms, comment, atoms


def distance(atom1, atom2):
    """Calculate the Euclidean distance between two atoms."""
    symbol1, x1, y1, z1 = atom1
    symbol2, x2, y2, z2 = atom2
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2 + (z2 - z1) ** 2)


def split_dimer(file_path, tag):
    """Split a dimer into two monomers based on connectivity."""
    num_atoms, comment, atoms = read_xyz_file(file_path)

    # Build adjacency matrix (atoms within 1.8 Å are connected)
    adjacency = {}
    for i in range(len(atoms)):
        adjacency[i] = []
        for j in range(len(atoms)):
            if i != j and distance(atoms[i], atoms[j]) < 1.8:
                adjacency[i].append(j)

    # BFS to find connected components
    visited = set()
    components = []

    for i in range(len(atoms)):
        if i not in visited:
            component = []
            queue = [i]
            visited.add(i)

            while queue:
                node = queue.pop(0)
                component.append(node)

                for neighbor in adjacency[node]:
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append(neighbor)

            components.append(component)

    # If we found multiple components, use them
    # Otherwise, split in the middle (fallback)
    if len(components) < 2:
        print(f"Warning: Could not identify separate molecules in {file_path}")
        midpoint = len(atoms) // 2
        components = [list(range(midpoint)), list(range(midpoint, len(atoms)))]

    # For molecules like water dimer where we have distinct components
    if len(components) == 2:
        monomer_a_indices = components[0]
        monomer_b_indices = components[1]
    # For more complex cases, we might need to merge some components
    else:
        monomer_a_indices = components[0]
        monomer_b_indices = []
        for i in range(1, len(components)):
            monomer_b_indices.extend(components[i])

    # Create monomer A
    monomer_a = []
    for idx in monomer_a_indices:
        monomer_a.append(atoms[idx])

    # Create monomer B
    monomer_b = []
    for idx in monomer_b_indices:
        monomer_b.append(atoms[idx])

    return (len(monomer_a), f"{tag} A", monomer_a), (len(monomer_b), f"{tag} B", monomer_b)


def write_xyz_file(file_path, num_atoms, comment, atoms):
    """Write atom coordinates to an XYZ file."""
    with open(file_path, "w") as f:
        f.write(f"{num_atoms}\n")
        f.write(f"{comment}\n")
        for atom in atoms:
            symbol, x, y, z = atom
            f.write(f"{symbol}  {x:10.6f}  {y:10.6f}  {z:10.6f}\n")


# Create the output directory if it doesn't exist
if not os.path.exists(output_dir):
    os.makedirs(output_dir)

# Process all dimers and create a new CSV
new_rows = []

for idx, (dimer_id, xyz_file, ref_kcal, interaction_type) in enumerate(dimers, 1):
    # Create index with leading zero for single digits
    idx_str = f"{idx:02d}"

    # Create cluster label
    tag = f"{idx_str}_{dimer_id}"

    # Construct full paths
    xyz_path = os.path.join(xyz_dir, xyz_file)
    a_output_path = os.path.join(output_dir, f"{tag}_A.xyz")
    b_output_path = os.path.join(output_dir, f"{tag}_B.xyz")

    # Split the dimer
    monomer_a, monomer_b = split_dimer(xyz_path, tag)

    # Write the monomer files
    write_xyz_file(a_output_path, *monomer_a)
    write_xyz_file(b_output_path, *monomer_b)

    # Add to new CSV rows
    new_rows.append([idx_str, dimer_id, f"{tag}_A.xyz", f"{tag}_B.xyz", ref_kcal, interaction_type])

    print(f"Processed {tag}")

# Write the new CSV file
csv_path = os.path.join(output_dir, "s22_index.csv")
with open(csv_path, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["idx", "dimer_id", "xyz_A", "xyz_B", "ref_kcal", "interaction_type"])
    writer.writerows(new_rows)

print(f"CSV file written to {csv_path}")
print("All dimers have been processed successfully!")
