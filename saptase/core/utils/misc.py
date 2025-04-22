"""Miscellaneous utility functions."""


def format_energy_delta(
    delta: float,
    tolerance: float,
    converged: bool,
    unit: str = "kcal/mol", # Or Hartree?
    precision: int = 4
) -> str:
    """Formats a user-friendly string for energy convergence check.

    Args:
        delta: The absolute energy difference.
        tolerance: The convergence tolerance.
        converged: Whether the component is considered converged.
        unit: The energy unit (default: kcal/mol).
        precision: Decimal precision for formatting.

    Returns:
        A formatted string indicating convergence status.
    """
    status = "Converged" if converged else "NOT Converged"
    comparison = "<=" if converged else ">"
    # Convert Hartree to kcal/mol if needed (assuming delta/tolerance are Hartree)
    # 1 Hartree = 627.5095 kcal/mol
    conversion_factor = 627.5095 if unit == "kcal/mol" else 1.0
    delta_disp = delta * conversion_factor
    tolerance_disp = tolerance * conversion_factor

    return (
        f"{status} (ΔE = {delta_disp:.{precision}f} {comparison} "
        f"{tolerance_disp:.{precision}f} {unit})"
    )
