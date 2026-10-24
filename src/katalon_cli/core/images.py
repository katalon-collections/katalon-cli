"""Prüft die Fremdservice-Images eines Updates: Major-Wechsel und `requires` des Releases."""

from __future__ import annotations

import operator
import re

from .release import ReleaseImages, ReleaseRequirements

# Compose-Service → Rolle in ReleaseImages/ReleaseRequirements, für die ein Major-Wechsel
# nicht per Image-Tausch geht: Postgres braucht Dump/Restore, Elasticsearch öffnet ein
# Datenverzeichnis einer anderen Major-Version nicht (Rückweg gar nicht).
DATA_SERVICES = {"db": "postgres", "elasticsearch": "elasticsearch"}

_OPS = {">=": operator.ge, "<=": operator.le, "==": operator.eq, ">": operator.gt, "<": operator.lt}


def image_version(image: str) -> tuple[int, ...] | None:
    """Version aus dem Tag (`postgis/postgis:16-3.4` → (16,), `…:8.13.4` → (8, 13, 4))."""
    name = image.rsplit("/", 1)[-1]
    if ":" not in name:
        return None
    match = re.match(r"\d+(?:\.\d+)*", name.split(":", 1)[1])
    return tuple(int(part) for part in match.group(0).split(".")) if match else None


def satisfies(version: tuple[int, ...], spec: str) -> bool:
    """Minimaler Specifier-Vergleich für `requires` (z. B. ">=8.13,<9")."""
    for clause in spec.split(","):
        match = re.fullmatch(r"\s*(>=|<=|==|>|<)\s*(\d+(?:\.\d+)*)\s*", clause)
        if not match:
            raise ValueError(f"Ungültige Versionsanforderung: {spec}")
        bound = tuple(int(part) for part in match.group(2).split("."))
        if not _OPS[match.group(1)](version[: len(bound)], bound):
            return False
    return True


def update_problems(
    current: dict[str, str], target: dict[str, str], requires: ReleaseRequirements
) -> tuple[list[str], list[str]]:
    """(Fehler, Hinweise) für den Wechsel der wirksamen Images `current` → `target`."""
    errors: list[str] = []
    notes: list[str] = []
    for service, role in DATA_SERVICES.items():
        old, new = current.get(service), target.get(service)
        if not new:
            continue
        new_version = image_version(new)
        spec = getattr(requires, role)
        if spec and new_version and not satisfies(new_version, spec):
            errors.append(f"{service}: {new} erfüllt die Anforderung des Releases nicht ({role} {spec}).")
        elif spec and not new_version:
            notes.append(f"{service}: Version von {new} nicht erkennbar, Anforderung {spec} ungeprüft.")
        old_version = image_version(old) if old else None
        if old_version and new_version and old_version[0] != new_version[0]:
            errors.append(
                f"{service}: Major-Wechsel {old} → {new} geht nicht per Image-Tausch "
                "(Postgres: Dump/Restore, Elasticsearch: neues Datenverzeichnis und Reindex)."
            )
    return errors, notes


def rollback_images(current: ReleaseImages, previous: ReleaseImages) -> ReleaseImages:
    """Images für den Rollback: die des vorigen Releases, außer einem neueren Elasticsearch.

    Elasticsearch öffnet ein Datenverzeichnis nicht mehr mit einer älteren Version; die
    Katalon-Version davor läuft mit dem neueren Minor-Release derselben Major-Version."""
    cur, prev = image_version(current.elasticsearch), image_version(previous.elasticsearch)
    if cur and prev and cur[0] == prev[0] and cur > prev:
        return previous.model_copy(update={"elasticsearch": current.elasticsearch})
    return previous
