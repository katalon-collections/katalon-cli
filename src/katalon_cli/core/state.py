"""installation.json — Single Source of Truth für die laufende Instanz."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic import BaseModel, Field

STATE_FILENAME = "installation.json"


class HistoryEntry(BaseModel):
    version: str
    compose_revision: int
    action: str  # "install" | "update" | "rollback"
    at: datetime


class InstallationState(BaseModel):
    version: str
    compose_revision: int
    base_url: str
    tls_mode: str  # "standalone" | "behind-proxy" | "none"
    installed_at: datetime
    history: list[HistoryEntry] = Field(default_factory=list)

    @classmethod
    def load(cls, instance_dir: Path) -> "InstallationState":
        path = instance_dir / STATE_FILENAME
        if not path.exists():
            raise FileNotFoundError(
                f"{path} nicht gefunden — ist dies ein Katalon-Instanzverzeichnis?"
            )
        return cls.model_validate_json(path.read_text())

    def save(self, instance_dir: Path) -> None:
        path = instance_dir / STATE_FILENAME
        path.write_text(self.model_dump_json(indent=2))

    def record(self, version: str, compose_revision: int, action: str) -> None:
        self.history.append(
            HistoryEntry(
                version=version,
                compose_revision=compose_revision,
                action=action,
                at=datetime.now(timezone.utc),
            )
        )
        self.version = version
        self.compose_revision = compose_revision

    def previous(self) -> HistoryEntry | None:
        """Letzter History-Eintrag vor dem aktuellen Stand, für Rollback."""
        if len(self.history) < 2:
            return None
        return self.history[-2]


def instance_dir_or_raise(path: Path) -> Path:
    if not (path / STATE_FILENAME).exists():
        raise FileNotFoundError(
            f"Kein Katalon in {path} gefunden (installation.json fehlt). "
            "Erst `katalon install` ausführen."
        )
    return path
