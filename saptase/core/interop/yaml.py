# saptase/core/interop/yaml.py
"""
YAML configuration loading utilities.
"""

import os
from typing import Any, Dict

from ruamel.yaml import YAML


def load_config(config_path: str) -> Dict[str, Any]:
    """
    Load configuration from a YAML file.

    Args:
        config_path: Path to the YAML configuration file.

    Returns:
        A dictionary containing the loaded configuration.

    Raises:
        FileNotFoundError: If the config file does not exist.
        YAMLError: If the file cannot be parsed.
    """
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    yaml = YAML(typ="safe")  # Use safe loader
    try:
        with open(config_path, "r") as f:
            config_data = yaml.load(f)
        if not isinstance(config_data, dict):
            # Ensure the top level is a dictionary
            raise TypeError(f"Expected YAML root to be a dictionary, but got {type(config_data)}")
        return config_data
    except Exception as e:
        # Catch potential ruamel.yaml parsing errors or other issues
        raise Exception(f"Error parsing YAML file {config_path}: {e}") from e
