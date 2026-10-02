"""Benutzerweit gespeicherter Pfad zur Katalon-Instanz."""

from __future__ import annotations

import os
from pathlib import Path


def instance_config_path() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME")
    base = Path(config_home) if config_home else Path.home() / ".config"
    if not base.is_absolute():
        base = Path.home() / ".config"
    return base / "katalon" / "instance"


def default_instance_dir() -> Path:
    config = instance_config_path()
    if config.exists():
        value = config.read_text().strip()
        if not value or not Path(value).is_absolute():
            raise ValueError(f"Ungültiger Instanzpfad in {config}: absoluter Pfad erforderlich.")
        return Path(value)
    return Path.home() / "katalon"


def save_instance_dir(path: Path) -> None:
    config = instance_config_path()
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(str(path.expanduser().resolve()) + "\n")
