"""GitHub-Release-Metadata für Katalon (nicht katalon-cli selbst)."""

from __future__ import annotations

import httpx
from pydantic import BaseModel, Field

GITHUB_REPO = "katalon-collections/katalon"


class ReleaseRequirements(BaseModel):
    postgres: str | None = None
    elasticsearch: str | None = None


class ReleaseEnvVar(BaseModel):
    """Neu hinzugekommene Umgebungsvariable eines Releases (katalon-release.json)."""

    key: str
    description: str = ""
    required: bool = False
    secret: bool = False
    default: str | None = None


class DeprecatedEnvVar(BaseModel):
    """Veraltete Umgebungsvariable eines Releases (katalon-release.json)."""

    key: str
    note: str = ""


class ReleaseMetadata(BaseModel):
    version: str
    minimum_installer_version: str
    migration_required: bool
    breaking: bool
    compose_revision: int
    requires: ReleaseRequirements = ReleaseRequirements()
    env_vars: list[ReleaseEnvVar] = Field(default_factory=list)
    deprecated_env_vars: list[DeprecatedEnvVar] = Field(default_factory=list)


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

def get_release_notes(tag: str) -> str:
    """Lädt den Changelog-Text (Release-Body) für einen Tag."""
    with httpx.Client(timeout=15) as client:
        release = client.get(
            f"https://api.github.com/repos/{GITHUB_REPO}/releases/tags/{tag}"
        )
        release.raise_for_status()
        return release.json().get("body") or ""


def _fetch_releases() -> list[dict]:
    """Lädt alle veröffentlichten Katalon-Releases."""
    releases: list[dict] = []
    url: str | None = f"https://api.github.com/repos/{GITHUB_REPO}/releases"
    params: dict[str, int] | None = {"per_page": 100}
    with httpx.Client(timeout=15) as client:
        while url:
            response = client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, list):
                raise ValueError("GitHub-Releases-Antwort ist keine Liste.")
            releases.extend(data)
            url = response.links.get("next", {}).get("url")
            params = None
    return releases


def _version_key(version: str) -> tuple[int, int, int]:
    parts = version.lstrip("v").split(".")
    if len(parts) != 3 or not all(part.isdigit() for part in parts):
        raise ValueError(f"Ungültige Release-Version: {version}")
    return int(parts[0]), int(parts[1]), int(parts[2])


def get_releases_between(installed_version: str, target_version: str) -> list[ReleaseMetadata]:
    """Lädt Metadaten aller veröffentlichten Releases im Update-Pfad."""
    lower = _version_key(installed_version)
    upper = _version_key(target_version)
    if upper <= lower:
        return []

    releases: list[tuple[tuple[int, int, int], str]] = []
    for release in _fetch_releases():
        if release.get("draft") or release.get("prerelease"):
            continue
        tag = str(release.get("tag_name", ""))
        try:
            version = _version_key(tag)
        except ValueError:
            continue
        if lower < version <= upper:
            releases.append((version, tag))

    return [
        ReleaseMetadata.model_validate(_fetch_release_asset(tag))
        for _, tag in sorted(releases)
    ]


def get_latest_release() -> ReleaseMetadata:
    payload = _fetch_release_asset(tag=None)
    return ReleaseMetadata.model_validate(payload)


def get_release(version: str) -> ReleaseMetadata:
    payload = _fetch_release_asset(tag=f"v{version.lstrip('v')}")
    return ReleaseMetadata.model_validate(payload)
