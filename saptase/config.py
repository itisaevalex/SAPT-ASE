"""SAPTASE global configuration defaults.

This module centralises user-tweakable defaults so they can be consumed across
code without sprinkling *magic strings* everywhere.  In a future release these
could be populated from a YAML/INI file or environment variables, but for now
hard-coded constants are sufficient.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
import os

__all__ = ["ExecutionConfig", "EXECUTION"]


@dataclass(slots=True)
class ExecutionConfig:  # noqa: D101 – simple value object
    scratch_root: Optional[str] = None  # ``None`` ⇒ system temp dir
    keep_scratch: bool = False


# *Singleton* holding the defaults.  Importing modules should use
# ``from saptase.config import EXECUTION`` and read attributes directly.
_env_root = os.getenv("SAPTASE_SCRATCH_ROOT")
_env_keep = os.getenv("SAPTASE_KEEP_SCRATCH")

EXECUTION = ExecutionConfig(
    scratch_root=_env_root if _env_root else None,
    keep_scratch=(_env_keep.lower() in {"1", "true", "yes"}) if _env_keep else False,
)
