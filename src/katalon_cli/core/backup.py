"""Backup vor jedem Update, Restore für Rollback. Kein Alembic-Downgrade — s. Plan."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

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


def dump_format(dump: Path) -> str:
    """'custom' für pg_dump -Fc (Magic `PGDMP`), sonst 'sql' (Plain-Text)."""
    with dump.open("rb") as fh:
        return "custom" if fh.read(5) == b"PGDMP" else "sql"


def restore_dump(
    instance_dir: Path,
    dump: Path,
    on_progress: Callable[[int], None] | None = None,
    chunk_size: int = 1024 * 1024,
) -> str:
    """Ersetzt die DB `katalon` durch den Dump. Gibt das erkannte Format zurück.

    Die Datei wird in Blöcken an pg_restore/psql gestreamt; `on_progress` bekommt
    die bisher gesendeten Bytes.
    """
    if not dump.is_file():
        raise BackupError(f"Dump nicht gefunden: {dump}")
    fmt = dump_format(dump)

    docker.compose(
        instance_dir, "exec", "-T", "db", "dropdb", "-U", "katalon", "--if-exists", "--force", "katalon"
    )
    docker.compose(instance_dir, "exec", "-T", "db", "createdb", "-U", "katalon", "katalon")

    if fmt == "custom":
        tool = ["pg_restore", "-U", "katalon", "-d", "katalon", "--no-owner", "--exit-on-error"]
    else:
        tool = ["psql", "-U", "katalon", "-d", "katalon", "-q", "-v", "ON_ERROR_STOP=1"]

    sent = 0
    with tempfile.TemporaryFile() as err, dump.open("rb") as src:
        proc = subprocess.Popen(
            [*docker.compose_command(), *docker.compose_files(instance_dir), "exec", "-T", "db", *tool],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=err,
            cwd=instance_dir,
        )
        assert proc.stdin is not None
        try:
            while chunk := src.read(chunk_size):
                proc.stdin.write(chunk)
                sent += len(chunk)
                if on_progress:
                    on_progress(sent)
            proc.stdin.close()
        except BrokenPipeError:
            pass  # Tool ist vorzeitig beendet — Fehlertext steht unten in stderr
        returncode = proc.wait()
        err.seek(0)
        message = err.read().decode(errors="replace").strip()

    if returncode != 0:
        raise BackupError(f"Restore fehlgeschlagen ({tool[0]}, Exit {returncode}):\n{message[-2000:]}")
    return fmt
