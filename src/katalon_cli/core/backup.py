"""Backup vor jedem Update, Restore für Rollback. Kein Alembic-Downgrade — s. Plan."""

from __future__ import annotations

import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import docker


class BackupError(RuntimeError):
    pass


def create_backup(instance_dir: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M")
    backup_dir = instance_dir / "backups" / timestamp
    backup_dir.mkdir(parents=True, exist_ok=True)

    dump = docker.compose(
        instance_dir,
        "exec",
        "-T",
        "db",
        "pg_dump",
        "-U",
        "katalon",
        "katalon",
        check=True,
        capture=True,
    )
    (backup_dir / "pg_dump.sql").write_text(dump.stdout)

    for name in (".env", "installation.json"):
        src = instance_dir / name
        if src.exists():
            shutil.copy2(src, backup_dir / name)

    return backup_dir


def restore_backup(instance_dir: Path, backup_dir: Path) -> None:
    dump_file = backup_dir / "pg_dump.sql"
    if not dump_file.exists():
        raise BackupError(f"Kein pg_dump.sql in {backup_dir}")

    docker.compose(instance_dir, "exec", "-T", "db", "dropdb", "-U", "katalon", "katalon")
    docker.compose(instance_dir, "exec", "-T", "db", "createdb", "-U", "katalon", "katalon")
    subprocess.run(
        [*docker.compose_command(), *docker.compose_files(instance_dir),
         "exec", "-T", "db", "psql", "-U", "katalon", "katalon"],
        input=dump_file.read_text(),
        cwd=instance_dir,
        text=True,
        check=True,
    )

    for name in (".env", "installation.json"):
        src = backup_dir / name
        if src.exists():
            shutil.copy2(src, instance_dir / name)


def latest_backup(instance_dir: Path) -> Path | None:
    backups_dir = instance_dir / "backups"
    if not backups_dir.exists():
        return None
    candidates = sorted(backups_dir.iterdir(), reverse=True)
    return candidates[0] if candidates else None
