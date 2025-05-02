import os
import glob

# Path to the s22_split directory
split_dir = r"C:\Users\Alex Isaev\Documents\Physics Thesis Automated Multi-Fidelity SAPT(DFT) Workflows\Code\data\s22_split"

# Get all XYZ files
xyz_files = glob.glob(os.path.join(split_dir, "*.xyz"))

for file_path in xyz_files:
    # Read the current content
    with open(file_path, "r") as f:
        lines = f.readlines()

    # Check if we need to add an empty line
    if len(lines) >= 2 and lines[1].strip() and not lines[1].isspace():
        # Insert an empty line after the first line
        fixed_lines = [lines[0], "\n"] + lines[1:]

        # Write the fixed content back
        with open(file_path, "w") as f:
            f.writelines(fixed_lines)

        print(f"Fixed: {os.path.basename(file_path)}")
    else:
        print(f"Already correct: {os.path.basename(file_path)}")

print("All XYZ files have been processed.")
