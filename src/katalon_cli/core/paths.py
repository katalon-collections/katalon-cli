"""Plattformabhängiger Default-Pfad für Instanzverzeichnisse.

/opt ist Linux-Server-Konvention für selbstverwaltete Dienste und dort meist
nur mit sudo beschreibbar. macOS (lokales Testen/Entwickeln) hat keine
vergleichbare Konvention mit Schreibrechten ohne sudo — dort ins Home.
"""

from __future__ import annotations

import platform
from pathlib import Path


def default_instance_dir() -> Path:
    if platform.system() == "Darwin":
        return Path.home() / "katalon"
    return Path("/opt/katalon")
