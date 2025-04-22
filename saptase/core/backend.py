"""Backend implementations for SAPT calculations."""

from abc import ABC, abstractmethod

try:
    import psi4
except ImportError:
    psi4 = None  # Allow running the module without Psi4 installed

from .models import SaptResult, SaptTask, TaskStatus


class SaptBackend(ABC):
    """Abstract base class for SAPT calculation backends."""

    @abstractmethod
    def calculate(self, task: SaptTask) -> SaptResult:
        """Perform a SAPT calculation for the given task.

        Args:
            task: The SAPT calculation task to perform

        Returns:
            A SaptResult containing the calculation results
        """
        pass


class Psi4Backend(SaptBackend):
    """Backend for SAPT calculations using Psi4.

    For MVP, this implements only single-threaded SAPT0 with jun-cc-pVDZ.
    """

    def __init__(self, memory: str = "2GB"):
        """Initialize the Psi4 backend.

        Args:
            memory: Memory allocation for Psi4
        """
        self.memory = memory

        if psi4 is None:
            raise ImportError("Psi4 is required for this backend but could not be imported")

    def calculate(self, task: SaptTask) -> SaptResult:
        """Perform a SAPT calculation using Psi4.

        Args:
            task: The SAPT calculation task to perform

        Returns:
            A SaptResult containing the calculation results
        """
        # Create a result object with the task ID
        result = SaptResult(task_id=task.id)

        try:
            # Update task status
            task.status = TaskStatus.RUNNING

            # Initialize Psi4
            psi4.core.clean()
            psi4.set_memory(self.memory)
            psi4.core.set_output_file("psi4_output.dat", False)

            # Create a dimer molecule with fragments
            a_xyz = task.monomer_a.to_xyz_string().split("\n", 2)[2]  # Skip atom count and comment
            b_xyz = task.monomer_b.to_xyz_string().split("\n", 2)[2]  # Skip atom count and comment

            # Format the molecule for Psi4 with fragment separation
            molecule_str = (
                f"{task.monomer_a.charge} {task.monomer_a.multiplicity} / "
                f"{task.monomer_b.charge} {task.monomer_b.multiplicity}\n"
                f"--\n"
                f"{a_xyz}\n"
                f"--\n"
                f"{b_xyz}\n"
            )

            # Set up the Psi4 molecule
            psi4_mol = psi4.geometry(molecule_str)

            # Set basis set and other options
            psi4.set_options(
                {
                    "basis": task.basis_set,
                    "scf_type": "df",  # Use density fitting for speed
                    "freeze_core": "true",  # Freeze core orbitals
                    **task.additional_keywords,
                }
            )

            # Run the SAPT calculation
            psi4.energy(task.method, molecule=psi4_mol)

            # Extract SAPT energy components
            result.energies = {
                "total": psi4.variable("SAPT TOTAL ENERGY"),
                "electrostatics": psi4.variable("SAPT ELST ENERGY"),
                "exchange": psi4.variable("SAPT EXCH ENERGY"),
                "induction": psi4.variable("SAPT IND ENERGY"),
                "dispersion": psi4.variable("SAPT DISP ENERGY"),
            }

            # Get the output
            try:
                with open("psi4_output.dat") as f:
                    result.raw_output = f.read()
            except FileNotFoundError:
                pass

            # Update status
            task.status = TaskStatus.COMPLETED
            result.success = True

        except Exception as e:
            # Handle any errors
            task.status = TaskStatus.FAILED
            result.success = False
            result.error_message = str(e)

        return result


class CamCaspBackend(SaptBackend):
    """Backend for SAPT calculations using CamCASP.

    This is a placeholder for future implementation.
    """

    def calculate(self, task: SaptTask) -> SaptResult:
        """Placeholder for CamCASP calculation.

        Args:
            task: The SAPT calculation task to perform

        Returns:
            A SaptResult containing the calculation results
        """
        raise NotImplementedError("CamCASP backend is not implemented in MVP")


class Sapt2020Backend(SaptBackend):
    """Backend for SAPT calculations using SAPT2020.

    This is a placeholder for future implementation.
    """

    def calculate(self, task: SaptTask) -> SaptResult:
        """Placeholder for SAPT2020 calculation.

        Args:
            task: The SAPT calculation task to perform

        Returns:
            A SaptResult containing the calculation results
        """
        raise NotImplementedError("SAPT2020 backend is not implemented in MVP")
