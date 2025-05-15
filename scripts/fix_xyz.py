import pathlib
import sys


def sanitize_xyz_file(file_path: pathlib.Path):
    """
    Sanitizes an XYZ file in-place.
    Ensures:
    1. Exactly one comment line (the second line).
    2. The file ends with a single trailing newline.
    """
    try:
        lines = file_path.read_text().splitlines()

        if not lines:
            print(f"Warning: Skipped empty file: {file_path}", file=sys.stderr)
            return

        atom_count_line = lines[0]
        comment_line = lines[1] if len(lines) > 1 else ""
        atom_coordinate_lines = lines[2:]

        content_parts = [atom_count_line.strip("\r\n")]
        content_parts.append(comment_line.strip("\r\n"))

        for atom_line in atom_coordinate_lines:
            content_parts.append(atom_line.strip("\r\n"))

        new_content = "\n".join(content_parts)
        # Ensure a single trailing newline for the whole file
        new_content = new_content.rstrip("\n\r") + "\n"

        file_path.write_text(new_content)
        # print(f"Sanitized: {file_path}")

    except Exception as e:
        print(f"Error processing file {file_path}: {e}", file=sys.stderr)


def main():
    scripts_dir = pathlib.Path(__file__).parent
    project_root = scripts_dir.parent
    data_dir = project_root / "data" / "s22_split"

    if not data_dir.exists():
        print(f"Error: Directory not found: {data_dir}", file=sys.stderr)
        sys.exit(1)

    xyz_files_a = list(data_dir.glob("*_a.xyz"))
    xyz_files_b = list(data_dir.glob("*_b.xyz"))
    all_xyz_files = sorted(xyz_files_a + xyz_files_b)

    if not all_xyz_files:
        print(f"No XYZ files found in {data_dir} to sanitize.", file=sys.stderr)
        return

    print(f"Found {len(all_xyz_files)} XYZ files to process in {data_dir}...")
    for xyz_file in all_xyz_files:
        sanitize_xyz_file(xyz_file)

    print(f"Finished sanitizing {len(all_xyz_files)} files.")


if __name__ == "__main__":
    main()
