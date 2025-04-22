"""Core data models for SAPTASE."""

from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Dict, List, Optional, Union

import numpy as np


class TaskStatus(Enum):
    """Status of a SAPT calculation task."""

    PENDING = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()


@dataclass
class Molecule:
    """Represents a molecule for SAPT calculations.

    Attributes:
        symbols: List of atomic symbols
        coordinates: Array of atomic coordinates (Å)
        charge: Total charge of the molecule
        multiplicity: Spin multiplicity of the molecule
        name: Optional name for the molecule
    """

    symbols: List[str]
    coordinates: np.ndarray  # Shape (N, 3) for N atoms
    charge: int = 0
    multiplicity: int = 1
    name: Optional[str] = None

    def __post_init__(self) -> None:
        """Validate inputs and convert coordinates to numpy array if needed."""
        if isinstance(self.coordinates, list):
            self.coordinates = np.array(self.coordinates, dtype=float)

        if self.coordinates.shape[0] != len(self.symbols):
            raise ValueError(
                f"Number of symbols ({len(self.symbols)}) must match number of "
                f"coordinates ({self.coordinates.shape[0]})"
            )

        if self.coordinates.shape[1] != 3:
            raise ValueError(f"Coordinates must be 3D, got shape {self.coordinates.shape}")

    def to_xyz_string(self) -> str:
        """Convert molecule to XYZ format string."""
        lines = [str(len(self.symbols))]
        if self.name:
            lines.append(self.name)
        else:
            lines.append("")

        for i, symbol in enumerate(self.symbols):
            x, y, z = self.coordinates[i]
            lines.append(f"{symbol:<2} {x:12.6f} {y:12.6f} {z:12.6f}")

        return "\n".join(lines)

    @classmethod
    def from_xyz_string(cls, xyz_string: str, charge: int = 0, multiplicity: int = 1) -> "Molecule":
        """Create a Molecule instance from an XYZ format string."""
        lines = xyz_string.strip().split("\n")
        num_atoms = int(lines[0])
        name = lines[1].strip()

        symbols = []
        coordinates = []

        for i in range(2, 2 + num_atoms):
            if i >= len(lines):
                raise ValueError(f"Expected {num_atoms} atoms, found only {i - 2}")

            parts = lines[i].split()
            if len(parts) < 4:
                raise ValueError(f"Invalid atom line: {lines[i]}")

            symbol = parts[0]
            x, y, z = float(parts[1]), float(parts[2]), float(parts[3])

            symbols.append(symbol)
            coordinates.append([x, y, z])

        return cls(
            symbols=symbols,
            coordinates=np.array(coordinates),
            charge=charge,
            multiplicity=multiplicity,
            name=name if name else None,
        )

    @classmethod
    def from_xyz_file(
        cls, file_path: Union[str, Path], charge: int = 0, multiplicity: int = 1
    ) -> "Molecule":
        """Create a Molecule instance from an XYZ file."""
        with open(file_path) as f:
            xyz_content = f.read()

        return cls.from_xyz_string(xyz_content, charge, multiplicity)


@dataclass
class SaptTask:
    """A SAPT calculation task for a dimer system.

    Attributes:
        monomer_a: First monomer molecule
        monomer_b: Second monomer molecule
        basis_set: Basis set for the calculation
        method: SAPT method to use
        id: Optional task identifier
        status: Current status of the task
        additional_keywords: Additional keywords for the backend
    """

    monomer_a: Molecule
    monomer_b: Molecule
    basis_set: str = "jun-cc-pVDZ"
    method: str = "sapt0"
    id: Optional[str] = None
    status: TaskStatus = TaskStatus.PENDING
    additional_keywords: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Generate a task ID if none is provided."""
        if self.id is None:
            # Simple ID based on monomer names or number of atoms if no names
            a_name = self.monomer_a.name or f"{len(self.monomer_a.symbols)}atoms"
            b_name = self.monomer_b.name or f"{len(self.monomer_b.symbols)}atoms"
            self.id = f"{a_name}_{b_name}_{self.method}"


@dataclass
class SaptResult:
    """Results from a SAPT calculation.

    Attributes:
        task_id: ID of the task that produced these results
        energies: Dictionary of energy components (in Hartree)
        success: Whether the calculation completed successfully
        error_message: Error message if the calculation failed
        raw_output: Raw output from the backend calculation
        basis_set: The basis set used for this specific calculation attempt.
        method: The method used for this specific calculation attempt.
        # Attributes added during runtime/orchestration:
        elapsed_time: Time taken for the specific attempt (seconds).
        attempt_number: The 0-based index of the attempt that generated this result.
        error_code: Specific error code (e.g., 'BasisIncompatible') if success is False.
        error_details: Additional details about the error or recovery history (e.g., JSON string).
    """

    task_id: str
    energies: Dict[str, float] = field(default_factory=dict)
    success: bool = True
    error_message: Optional[str] = None
    raw_output: Optional[str] = None
    basis_set: Optional[str] = None
    method: Optional[str] = None
    # Runtime populated fields (consider adding defaults if needed)
    elapsed_time: Optional[float] = None
    attempt_number: Optional[int] = None
    error_code: Optional[str] = None
    error_details: Optional[str] = None

    @property
    def total_energy(self) -> float:
        """Get the total SAPT interaction energy in Hartree."""
        if not self.success:
            raise ValueError(
                f"Cannot get total energy for failed calculation: {self.error_message}"
            )

        if not self.energies:
            raise ValueError("No energy components found in result")

        if "total" in self.energies:
            return self.energies["total"]

        # If total is not directly available, sum the components
        components = ["electrostatics", "exchange", "induction", "dispersion"]
        return sum(self.energies.get(comp, 0.0) for comp in components)

    def total_energy_kcal_mol(self) -> float:
        """Get the total SAPT interaction energy in kcal/mol."""
        # Convert from Hartree to kcal/mol (1 Hartree = 627.5095 kcal/mol)
        return self.total_energy * 627.5095
