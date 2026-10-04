"""Suchindex-Neuaufbau: Task anstoßen und Fortschritt aus den Worker-Logs lesen."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from . import docker


class ReindexError(RuntimeError):
    pass


ENQUEUE_SCRIPT = """
from katalon.workers.index_tasks import reindex_all_task
print("TASK_ID=" + reindex_all_task.delay().id)
"""

# Zählt pro Typ genau die Datensätze, die bulk_reindex_type_task indiziert.
TOTALS_SCRIPT = """
import json
from sqlalchemy import func, select
from katalon.core.schemas import RECORD_TYPES
from katalon.workers.index_tasks import _make_session, _record_models, _run

models = _record_models()
Session, engine = _make_session()

async def go():
    out = {}
    async with Session() as s:
        for t in RECORD_TYPES:
            m = models[t]
            q = select(func.count()).select_from(m)
            if hasattr(m, "deleted_at"):
                q = q.where(m.deleted_at.is_(None))
            out[t] = (await s.execute(q)).scalar_one()
    return out

try:
    print("TOTALS=" + json.dumps(_run(go())))
finally:
    _run(engine.dispose())
"""

_BUILDING = re.compile(r"building (\d+) index docs for '(\w+)'")
_BUILT = re.compile(r"(\d+)/(\d+) docs built for '(\w+)'")
_INDEXED = re.compile(r"successfully indexed (\d+) records for '(\w+)'")
_FINISHED = re.compile(r"Task katalon\.reindex_all\[(?P<id>[0-9a-f-]+)\] (?P<state>succeeded|raised|failed)")
_RECEIVED = re.compile(r"Task katalon\.reindex_all\[(?P<id>[0-9a-f-]+)\] received")


@dataclass
class Progress:
    """Fortschritt eines reindex_all-Laufs, abgeleitet aus Worker-Logzeilen."""

    started: bool = False
    finished: bool = False
    failed: bool = False
    current: str | None = None
    totals: dict[str, int] = field(default_factory=dict)  # Typ -> Gesamtzahl
    built: dict[str, int] = field(default_factory=dict)  # Typ -> gebaut
    indexed: dict[str, int] = field(default_factory=dict)  # Typ -> fertig im Index

    def type_done(self, rtype: str) -> int:
        """Fortschritt eines Typs: fertig indiziert = voll, sonst gebaut."""
        if rtype in self.indexed:
            return self.totals.get(rtype, self.indexed[rtype])
        return self.built.get(rtype, 0)

    def total_done(self) -> int:
        return sum(self.type_done(t) for t in self.totals)


def parse_progress(log_text: str, task_id: str, known_totals: dict[str, int] | None = None) -> Progress:
    """Liest Worker-Logzeilen ab dem `received` des Tasks `task_id`."""
    progress = Progress(totals=dict(known_totals or {}))
    in_task = False
    for line in log_text.splitlines():
        received = _RECEIVED.search(line)
        if received:
            in_task = received["id"] == task_id
            if in_task:
                progress = Progress(started=True, totals=dict(known_totals or {}))
            continue
        if not in_task:
            continue
        if (m := _BUILDING.search(line)):
            progress.current = m[2]
            progress.totals[m[2]] = int(m[1])
        elif (m := _BUILT.search(line)):
            progress.current = m[3]
            progress.built[m[3]] = int(m[1])
        elif (m := _INDEXED.search(line)):
            progress.indexed[m[2]] = int(m[1])
        elif (m := _FINISHED.search(line)) and m["id"] == task_id:
            progress.finished = True
            progress.failed = m["state"] != "succeeded"
    return progress


def _exec_python(instance_dir: Path, script: str) -> str:
    result = docker.compose(
        instance_dir, "exec", "-T", "api", "python", "-c", script, capture=True, check=False
    )
    if result.returncode != 0:
        raise ReindexError((result.stderr or result.stdout or "Aufruf im api-Container fehlgeschlagen").strip())
    return result.stdout


def enqueue(instance_dir: Path) -> str:
    out = _exec_python(instance_dir, ENQUEUE_SCRIPT)
    match = re.search(r"TASK_ID=([0-9a-f-]+)", out)
    if not match:
        raise ReindexError(f"Task-ID nicht erkannt: {out.strip()}")
    return match[1]


def fetch_totals(instance_dir: Path) -> dict[str, int] | None:
    """Gesamtzahlen pro Typ; None, wenn nicht ermittelbar (Fortschritt dann ohne Prozent)."""
    try:
        out = _exec_python(instance_dir, TOTALS_SCRIPT)
        match = re.search(r"TOTALS=(\{.*\})", out)
        return json.loads(match[1]) if match else None
    except (ReindexError, ValueError):
        return None


def worker_logs(instance_dir: Path, since: datetime) -> str:
    result = docker.compose(
        instance_dir,
        "logs",
        "--no-color",
        "--since",
        since.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "worker",
        capture=True,
        check=False,
    )
    return result.stdout or ""


def follow(
    instance_dir: Path,
    task_id: str,
    since: datetime,
    totals: dict[str, int] | None,
    on_update: Callable[[Progress], None],
    poll_seconds: float = 2.0,
    timeout_seconds: float = 6 * 3600,
) -> Progress:
    """Pollt die Worker-Logs, bis der Task endet. Wirft ReindexError bei Fehlschlag/Timeout."""
    deadline = time.monotonic() + timeout_seconds
    while True:
        progress = parse_progress(worker_logs(instance_dir, since), task_id, totals)
        on_update(progress)
        if progress.finished:
            if progress.failed:
                raise ReindexError(
                    "Reindex mit Fehlern beendet — Details: katalon logs worker"
                )
            return progress
        if time.monotonic() > deadline:
            raise ReindexError("Zeitüberschreitung beim Warten auf den Reindex.")
        time.sleep(poll_seconds)
