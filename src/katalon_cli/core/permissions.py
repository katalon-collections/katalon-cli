"""Schreibrechte für Bind-Mounts, in die API und Worker schreiben.

API- und Worker-Image laufen als unprivilegierter User (Dockerfile `USER`). Ein vom
Installer oder per Hand angelegtes Host-Verzeichnis gehört dagegen meist root. Die
UID/GID wird nicht im CLI hinterlegt, sondern zur Laufzeit aus dem Container gelesen
(`id` im api-Service, inkl. eventuellem `user:` aus compose.override.yaml).

Die Korrektur läuft als root in einem Wegwerf-Container desselben Images — dadurch
funktioniert sie auch, wenn die CLI selbst nicht als root läuft. Sie ändert nur Eigentümer
von Einträgen mit falschem Eigentümer, nie Inhalte, und ist damit idempotent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from . import docker

# Container-Pfad des MEDIA_ROOT-Bind-Mounts (compose.yaml.j2, api + worker).
CONTAINER_MEDIA_ROOT = "/var/lib/katalon/media"
# Services, die in CONTAINER_MEDIA_ROOT schreiben.
WRITER_SERVICES = ("api", "worker")
# Service, dessen Image-User als Eigentümer gesetzt wird.
OWNER_SERVICE = "api"


class PermissionFixError(RuntimeError):
    pass


@dataclass(frozen=True)
class ContainerUser:
    uid: int
    gid: int
    name: str = ""

    def __str__(self) -> str:
        label = f"{self.uid}:{self.gid}"
        return f"{label} ({self.name})" if self.name else label


_ID_RE = re.compile(r"uid=(\d+)(?:\(([^)]*)\))?\s+gid=(\d+)")


def parse_id_output(output: str) -> ContainerUser:
    match = _ID_RE.search(output)
    if not match:
        raise PermissionFixError(f"Unerwartete Ausgabe von `id`: {output.strip()!r}")
    return ContainerUser(uid=int(match.group(1)), gid=int(match.group(3)), name=match.group(2) or "")


def _run(instance_dir: Path, service: str, *args: str, root: bool = False):
    user = ["--user", "0:0"] if root else []
    return docker.compose(
        instance_dir,
        "run", "--rm", "--no-deps", "-T", *user, "--entrypoint", args[0], service, *args[1:],
        check=False,
        capture=True,
    )


def container_user(instance_dir: Path, service: str = OWNER_SERVICE) -> ContainerUser:
    """UID/GID, unter der `service` tatsächlich läuft (Image-USER bzw. compose `user:`)."""
    result = _run(instance_dir, service, "id")
    if result.returncode != 0:
        raise PermissionFixError(
            f"UID des {service}-Containers nicht ermittelbar: {(result.stderr or result.stdout).strip()}"
        )
    return parse_id_output(result.stdout)


def chown_args(path: str, user: ContainerUser) -> list[str]:
    """`find`-Aufruf, der nur Einträge mit falschem Eigentümer umstellt (Inhalte bleiben unberührt)."""
    owner = f"{user.uid}:{user.gid}"
    return [
        "find", path, "-xdev",
        "(", "!", "-user", str(user.uid), "-o", "!", "-group", str(user.gid), ")",
        "-exec", "chown", "-h", owner, "{}", "+",
    ]


def is_writable(instance_dir: Path, service: str) -> bool:
    result = _run(instance_dir, service, "test", "-w", CONTAINER_MEDIA_ROOT)
    return result.returncode == 0


def unwritable_services(instance_dir: Path) -> list[str]:
    return [service for service in WRITER_SERVICES if not is_writable(instance_dir, service)]


def fix_media_permissions(instance_dir: Path) -> ContainerUser:
    """Setzt den Eigentümer von MEDIA_ROOT auf den Container-User und prüft danach die Schreibrechte."""
    user = container_user(instance_dir)
    result = _run(instance_dir, OWNER_SERVICE, *chown_args(CONTAINER_MEDIA_ROOT, user), root=True)
    if result.returncode != 0:
        raise PermissionFixError(
            f"Eigentümer von MEDIA_ROOT konnte nicht auf {user} gesetzt werden: "
            f"{(result.stderr or result.stdout).strip()}"
        )
    failing = unwritable_services(instance_dir)
    if failing:
        raise PermissionFixError(
            f"MEDIA_ROOT ist nach der Korrektur für {', '.join(failing)} nicht beschreibbar "
            f"(Eigentümer jetzt {user})."
        )
    return user


def manual_fix_hint(media_root: str, user: ContainerUser | None) -> str:
    owner = f"{user.uid}:{user.gid}" if user else "<UID>:<GID>"
    return f"sudo chown -R {owner} {media_root}"
