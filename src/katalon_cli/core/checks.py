"""Preflight-Checks für `katalon install` und `katalon doctor`."""

from __future__ import annotations

import shutil
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path

MIN_FREE_DISK_GB = 5


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


def check_docker() -> CheckResult:
    if not shutil.which("docker"):
        return CheckResult("Docker", False, "nicht gefunden — https://docs.docker.com/get-docker/")
    version = subprocess.run(["docker", "--version"], capture_output=True, text=True)
    return CheckResult("Docker", True, version.stdout.strip())


def check_compose() -> CheckResult:
    probe = subprocess.run(["docker", "compose", "version"], capture_output=True, text=True)
    if probe.returncode == 0:
        return CheckResult("Docker Compose", True, probe.stdout.strip())
    if shutil.which("docker-compose"):
        return CheckResult("Docker Compose", True, "docker-compose (standalone)")
    return CheckResult("Docker Compose", False, "nicht gefunden")


def check_disk_space(path: Path, min_gb: int = MIN_FREE_DISK_GB) -> CheckResult:
    path.mkdir(parents=True, exist_ok=True)
    free_gb = shutil.disk_usage(path).free / (1024**3)
    ok = free_gb >= min_gb
    return CheckResult(
        "Diskspace", ok, f"{free_gb:.1f} GB frei (min. {min_gb} GB) in {path}"
    )

def check_openssl() -> CheckResult:
    if not shutil.which("openssl"):
        return CheckResult("OpenSSL", False, "nicht gefunden — für TLS-Modus 'standalone' erforderlich")
    return CheckResult("OpenSSL", True, "gefunden")


def check_ports(ports: list[int]) -> CheckResult:
    busy = []
    for port in ports:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                busy.append(port)
    if busy:
        return CheckResult("Ports", False, f"belegt: {', '.join(map(str, busy))}")
    return CheckResult("Ports", True, f"frei: {', '.join(map(str, ports))}")


def run_all(
    instance_dir: Path, ports: list[int] | None = None, need_openssl: bool = False
) -> list[CheckResult]:
    results = [check_docker(), check_compose(), check_disk_space(instance_dir)]
    if ports:
        results.append(check_ports(ports))
    if need_openssl:
        results.append(check_openssl())
    return results
