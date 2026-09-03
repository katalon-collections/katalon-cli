"""Dünner Wrapper um `docker compose` — kein docker-py nötig, CLI reicht."""

from __future__ import annotations

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
