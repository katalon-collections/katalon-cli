"""Dünner Wrapper um `docker compose` — kein docker-py nötig, CLI reicht."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

class DockerError(RuntimeError):
    pass


def compose_command() -> list[str]:
    if shutil.which("docker") is None:
        raise DockerError("Docker ist nicht installiert oder nicht im PATH.")
    probe = subprocess.run(
        ["docker", "compose", "version"], capture_output=True, text=True
    )
    if probe.returncode == 0:
        return ["docker", "compose"]
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    raise DockerError("Docker Compose ist nicht installiert.")


def compose_files(instance_dir: Path) -> list[str]:
    files = ["-f", str(instance_dir / "compose.yaml")]
    override = instance_dir / "compose.override.yaml"
    if override.exists():
        files += ["-f", str(override)]
    return files


def compose(
    instance_dir: Path, *args: str, check: bool = True, capture: bool = False
) -> subprocess.CompletedProcess:
    cmd = [*compose_command(), *compose_files(instance_dir), *args]
    return subprocess.run(
        cmd,
        cwd=instance_dir,
        check=check,
        text=True,
        capture_output=capture,
    )


def config_images(instance_dir: Path, compose_file: Path | None = None) -> dict[str, str]:
    """Images je Service, wie Compose sie startet (inkl. compose.override.yaml)."""
    files = ["-f", str(compose_file or instance_dir / "compose.yaml")]
    override = instance_dir / "compose.override.yaml"
    if override.exists():
        files += ["-f", str(override)]
    result = subprocess.run(
        [*compose_command(), "--project-directory", str(instance_dir), *files, "config", "--format", "json"],
        cwd=instance_dir,
        check=True,
        text=True,
        capture_output=True,
    )
    services = json.loads(result.stdout).get("services", {})
    return {name: svc["image"] for name, svc in services.items() if svc.get("image")}


def reload_nginx(instance_dir: Path) -> None:
    """`up -d` erstellt nginx nicht neu, wenn nur die gemountete nginx.conf sich ändert."""
    compose(instance_dir, "exec", "-T", "nginx", "nginx", "-t")
    compose(instance_dir, "exec", "-T", "nginx", "nginx", "-s", "reload")


def is_healthy(instance_dir: Path, service: str = "api") -> bool:
    result = compose(
        instance_dir, "ps", "--format", "json", service, check=False, capture=True
    )
    return result.returncode == 0 and '"Health":"healthy"' in (result.stdout or "")


def is_running(instance_dir: Path, service: str = "db") -> bool:
    result = compose(
        instance_dir, "ps", "--status", "running", "-q", service, check=False, capture=True
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def wait_for_db(instance_dir: Path, timeout: int = 30) -> bool:
    for _ in range(timeout):
        result = compose(
            instance_dir,
            "exec",
            "-T",
            "db",
            "pg_isready",
            check=False,
            capture=True,
        )
        if result.returncode == 0:
            return True
        time.sleep(1)
    return False
