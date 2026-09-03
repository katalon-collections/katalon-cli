"""GitHub-Release-Metadata für Katalon (nicht katalon-cli selbst)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
from pydantic import BaseModel

GITHUB_REPO = "katalon-collections/katalon"
CACHE_TTL_SECONDS = 3600
CACHE_PATH = Path.home() / ".cache" / "katalon-cli" / "releases.json"


class ReleaseRequirements(BaseModel):
    postgres: str | None = None
    elasticsearch: str | None = None


class ReleaseMetadata(BaseModel):
    version: str
    minimum_installer_version: str
    migration_required: bool
    breaking: bool
    compose_revision: int
    requires: ReleaseRequirements = ReleaseRequirements()


def _fetch_release_asset(tag: str | None) -> dict:
    """Lädt katalon-release.json vom GitHub-Release (tag=None → latest)."""
    ref = "latest" if tag is None else f"tags/{tag}"
    with httpx.Client(timeout=15) as client:
        release = client.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases/{ref}"
        )
        release.raise_for_status()
        data = release.json()

    asset = next(
        (a for a in data["assets"] if a["name"] == "katalon-release.json"), None
    )
    if asset is None:
        raise ValueError(
            f"Release {data.get('tag_name', tag)} hat kein katalon-release.json Asset."
        )
    with httpx.Client(timeout=15, follow_redirects=True) as client:
        asset_resp = client.get(asset["browser_download_url"])
        asset_resp.raise_for_status()
        return asset_resp.json()


def get_latest_release(*, use_cache: bool = True) -> ReleaseMetadata:
    if use_cache and CACHE_PATH.exists():
        age = time.time() - CACHE_PATH.stat().st_mtime
        if age < CACHE_TTL_SECONDS:
            return ReleaseMetadata.model_validate_json(CACHE_PATH.read_text())

    payload = _fetch_release_asset(tag=None)
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(payload))
    return ReleaseMetadata.model_validate(payload)


def get_release(version: str) -> ReleaseMetadata:
    payload = _fetch_release_asset(tag=f"v{version.lstrip('v')}")
    return ReleaseMetadata.model_validate(payload)
