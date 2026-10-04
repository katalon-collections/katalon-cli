"""Hinweis auf neue katalon-cli-Versionen (PyPI), gecacht und nie störend."""

from __future__ import annotations

import json
import os
import re
import sys
import time
from importlib.metadata import version
from pathlib import Path

import httpx

PYPI_URL = "https://pypi.org/pypi/katalon-cli/json"
CHECK_INTERVAL = 24 * 3600
TIMEOUT = 2.0
DISABLE_ENV = "KATALON_NO_UPDATE_CHECK"


def cache_path() -> Path:
    cache_home = os.environ.get("XDG_CACHE_HOME")
    base = Path(cache_home) if cache_home else Path.home() / ".cache"
    if not base.is_absolute():
        base = Path.home() / ".cache"
    return base / "katalon" / "update-check.json"


def parse_version(raw: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", raw.split("+")[0].split("-")[0]))


def is_newer(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


def _read_cache() -> dict:
    try:
        data = json.loads(cache_path().read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_cache(latest: str) -> None:
    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"checked_at": time.time(), "latest": latest}))


def fetch_latest() -> str:
    with httpx.Client(timeout=TIMEOUT) as client:
        resp = client.get(PYPI_URL)
        resp.raise_for_status()
        return resp.json()["info"]["version"]


def latest_known() -> str | None:
    """Neueste Version laut Cache; fragt PyPI nur, wenn der Cache älter als 24h ist."""
    cache = _read_cache()
    checked_at = cache.get("checked_at")
    latest = cache.get("latest")
    if (
        isinstance(checked_at, (int, float))
        and isinstance(latest, str)
        and 0 <= time.time() - checked_at < CHECK_INTERVAL
    ):
        return latest or None
    try:
        latest = fetch_latest()
        _write_cache(latest)
    except Exception:
        # Auch Fehlschläge cachen, sonst bremst ein Offline-Rechner jeden Aufruf.
        try:
            _write_cache(latest if isinstance(latest, str) else "")
        except OSError:
            pass
        return latest if isinstance(latest, str) and latest else None
    return latest


def update_notice() -> str | None:
    """Hinweistext, wenn eine neuere Version existiert; sonst None. Wirft nie."""
    if os.environ.get(DISABLE_ENV) or not sys.stderr.isatty():
        return None
    try:
        current = version("katalon-cli")
        latest = latest_known()
        if latest and is_newer(latest, current):
            return (
                f"Neue katalon-cli-Version verfügbar: {current} → {latest} "
                f"(uv tool upgrade katalon-cli; Hinweis abschalten: {DISABLE_ENV}=1)"
            )
    except Exception:
        return None
    return None
