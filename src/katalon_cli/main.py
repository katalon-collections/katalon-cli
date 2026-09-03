"""katalon — Installer & Updater CLI für Production-Instanzen."""

from __future__ import annotations

import platform
import secrets
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm, Prompt
from rich.table import Table

from .core import backup as backup_mod
from .core import checks, docker, release
from .core.compose_gen import write_compose
from .core.paths import default_instance_dir
from .core.state import InstallationState, instance_dir_or_raise

app = typer.Typer(add_completion=False, help="Installer & Updater für Katalon Collections.")
console = Console()

DEFAULT_DIR = default_instance_dir()

TLS_CHOICES = {
    "standalone": "Standalone — eigenes nginx mit selbstsigniertem Zertifikat (Ports 80+443)",
    "behind-proxy": "Hinter eigenem Reverse-Proxy — kein TLS hier",
    "none": "Kein TLS (lokal / IP)",
}


OPTIONAL_ENV_MARKER = "# --- optionale Config (auskommentiert, bei Bedarf aktivieren) ---"
OPTIONAL_ENV_BLOCK = f"""
{OPTIONAL_ENV_MARKER}
# GEONAMES_USERNAME=demo
# SMTP_ENABLED=false
# SMTP_HOST=
# SMTP_PORT=587
# SMTP_USERNAME=
# SMTP_PASSWORD=
# SMTP_FROM=
# CORS_ORIGINS=["http://localhost"]
# MAX_UPLOAD_SIZE_MB=200
"""


def _ensure_env_vars(dir: Path, base_url: str, media_root: str | None = None) -> None:
    """Schreibt fehlende Pflicht-Env-Vars nach — idempotent, überschreibt nichts Vorhandenes."""
    env_path = dir / ".env"
    raw = env_path.read_text() if env_path.exists() else ""
    existing: dict[str, str] = {}
    for line in raw.splitlines():
        if "=" in line and not line.startswith("#"):
            key, _, value = line.partition("=")
            existing[key] = value

    postgres_password = existing.get("POSTGRES_PASSWORD", secrets.token_urlsafe(24))
    defaults = {
        "KATALON_BASE_URL": base_url,
        "POSTGRES_PASSWORD": postgres_password,
        "SECRET_KEY": secrets.token_urlsafe(32),
        "KATALON_SECRETS_KEY": secrets.token_urlsafe(32),
        "CANTALOUPE_PUBLIC_URL": base_url,
        "DEFAULT_ADMIN_EMAIL": "admin@example.org",
        "DEFAULT_ADMIN_PASSWORD": secrets.token_urlsafe(16),
    }
    if media_root is not None:
        defaults["MEDIA_ROOT"] = media_root
    for key, value in defaults.items():
        existing.setdefault(key, value)

    # Alte Installs hatten DATABASE_URL statisch in .env — jetzt aus POSTGRES_PASSWORD
    # in compose.yaml abgeleitet (einzige Quelle der Wahrheit), Altlast entfernen.
    existing.pop("DATABASE_URL", None)

    content = "".join(f"{key}={value}\n" for key, value in existing.items())
    if OPTIONAL_ENV_MARKER not in raw:
        content += OPTIONAL_ENV_BLOCK
    env_path.write_text(content)


OVERRIDE_EXAMPLE = """\
# compose.override.yaml
# Instanzspezifische Anpassungen hier eintragen, dann in "compose.override.yaml"
# umbenennen — docker compose bindet sie automatisch neben compose.yaml ein und
# katalon-cli überschreibt sie bei Updates nicht.
services:
  api:
    environment:
      - EXTRA_VAR=value

  db:
    volumes:
      - /mnt/external-disk/katalon-db:/var/lib/postgresql/data
"""


def _write_override_example(dir: Path) -> None:
    path = dir / "compose.override.yaml.example"
    if not path.exists():
        path.write_text(OVERRIDE_EXAMPLE)


def _run_checks(dir: Path, ports: list[int] | None = None, need_openssl: bool = False) -> bool:
    ok = True
    for result in checks.run_all(dir, ports=ports, need_openssl=need_openssl):
        icon, style = ("✔", "green") if result.ok else ("✖", "red")
        console.print(f"[{style}]{icon}[/] {result.name}: {result.detail}")
        ok = ok and result.ok
    return ok


@app.command()
def install(
    dir: Path = typer.Option(
        None, "--dir", help=f"Zielverzeichnis der Instanz (Default für dieses OS: {DEFAULT_DIR})"
    ),
):
    """Interaktiver Setup-Wizard für eine neue Instanz."""
    console.rule("[bold]Katalon Setup[/]")

    if dir is None:
        console.print(f"Zielverzeichnis — Standard für {platform.system()}: [cyan]{DEFAULT_DIR}[/]")
        dir = Path(Prompt.ask("Zielverzeichnis", default=str(DEFAULT_DIR)))

    if (dir / "installation.json").exists():
        console.print(f"[red]✖[/] {dir} ist bereits eine Katalon-Instanz.")
        raise typer.Exit(1)

    console.print()
    console.print(
        "KATALON_BASE_URL — [cyan]http://localhost[/] zum lokalen Testen (kein TLS), "
        "sonst echte Domain (dann folgt TLS-Auswahl)."
    )
    base_url = Prompt.ask("KATALON_BASE_URL", default="http://localhost")

    console.print()
    console.print("MEDIA_ROOT — Verzeichnis auf dem Host, in dem Katalon Mediendateien ablegt.")
    media_root = Prompt.ask("MEDIA_ROOT", default=str(dir / "media"))

    is_localhost = urlparse(base_url).hostname in (None, "localhost", "127.0.0.1")
    console.print()
    for key, label in TLS_CHOICES.items():
        console.print(f"  [cyan]{key}[/] — {label}")
    tls_mode = Prompt.ask("TLS-Modus", choices=list(TLS_CHOICES), default="none" if is_localhost else "standalone")

    console.print()
    console.rule("Preflight-Checks")
    ports = [80, 443] if tls_mode == "standalone" else None
    if not _run_checks(dir, ports=ports, need_openssl=tls_mode == "standalone"):
        console.print("[red]Abgebrochen — Check fehlgeschlagen.[/]")
        raise typer.Exit(1)

    console.print()
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
        task = progress.add_task("Lade Release-Metadaten …", total=None)
        try:
            meta = release.get_latest_release()
        except Exception as exc:  # noqa: BLE001
            progress.stop()
            console.print(f"[red]✖ Release-Metadaten konnten nicht geladen werden: {exc}[/]")
            raise typer.Exit(1) from exc
        progress.update(task, description=f"Release {meta.version} gefunden")

        progress.add_task("Schreibe compose.yaml + .env …", total=None)
        dir.mkdir(parents=True, exist_ok=True)
        Path(media_root).mkdir(parents=True, exist_ok=True)
        write_compose(dir, version=meta.version, base_url=base_url, tls_mode=tls_mode)

        _ensure_env_vars(dir, base_url, media_root=media_root)
        _write_override_example(dir)

        state = InstallationState(
            version=meta.version,
            compose_revision=meta.compose_revision,
            base_url=base_url,
            tls_mode=tls_mode,
            installed_at=datetime.now(timezone.utc),
        )
        state.record(meta.version, meta.compose_revision, "install")
        state.save(dir)

    console.print(f"[green]✔[/] Instanz eingerichtet in [bold]{dir}[/]")
    console.print(
        f"Admin-Login (DEFAULT_ADMIN_EMAIL/DEFAULT_ADMIN_PASSWORD) wurde generiert in [bold]{dir / '.env'}[/]."
    )
    console.print(
        f"Weitere optionale Config-Variablen sind auskommentiert in [bold]{dir / '.env'}[/] angelegt "
        "(SMTP, Geonames, …) — bei Bedarf einkommentieren."
    )
    console.print(
        f"Instanzspezifische compose-Overrides: [bold]{dir / 'compose.override.yaml.example'}[/] "
        "nach compose.override.yaml umbenennen."
    )
    console.print("Starten mit: [bold]katalon start --dir " + str(dir) + "[/]")


def _env_value(dir: Path, key: str) -> str | None:
    env_path = dir / ".env"
    if not env_path.exists():
        return None
    for line in env_path.read_text().splitlines():
        if line.startswith(f"{key}="):
            return line.partition("=")[2]
    return None


def _print_next_steps(dir: Path, base_url: str) -> None:
    base_url = base_url.rstrip("/")
    console.print()
    console.print(f"Portal:      [bold]{base_url}/[/]")
    console.print(f"Admin:       [bold]{base_url}/admin/[/]")
    admin_email = _env_value(dir, "DEFAULT_ADMIN_EMAIL")
    admin_password = _env_value(dir, "DEFAULT_ADMIN_PASSWORD")
    if admin_email and admin_password:
        console.print(f"Admin-Login: [bold]{admin_email}[/] / [bold]{admin_password}[/] (siehe auch {dir / '.env'})")
    console.print("Docs:        [bold]https://katalon-collections.github.io/katalon-docs/[/]")


@app.command()
def start(dir: Path = typer.Option(DEFAULT_DIR, "--dir")):
    """Stack starten."""
    instance_dir_or_raise(dir)
    docker.compose(dir, "up", "-d")
    console.print("[green]✔[/] Stack gestartet.")
    state = InstallationState.load(dir)
    _print_next_steps(dir, state.base_url)


@app.command()
def stop(dir: Path = typer.Option(DEFAULT_DIR, "--dir")):
    """Stack stoppen."""
    instance_dir_or_raise(dir)
    docker.compose(dir, "stop")
    console.print("[green]✔[/] Stack gestoppt.")


@app.command()
def restart(dir: Path = typer.Option(DEFAULT_DIR, "--dir")):
    """Stack neu starten."""
    instance_dir_or_raise(dir)
    docker.compose(dir, "restart")
    console.print("[green]✔[/] Stack neu gestartet.")


@app.command()
def status(dir: Path = typer.Option(DEFAULT_DIR, "--dir")):
    """Versionen, Container-Health, Diskspace."""
    instance_dir_or_raise(dir)
    state = InstallationState.load(dir)

    table = Table(show_header=False)
    table.add_row("Version", state.version)
    table.add_row("Compose-Revision", str(state.compose_revision))
    table.add_row("Base URL", state.base_url)
    table.add_row("TLS-Modus", state.tls_mode)
    table.add_row("Installiert", str(state.installed_at))
    console.print(table)

    docker.compose(dir, "ps")


@app.command()
def logs(
    service: str = typer.Argument(None, help="Service-Name, leer = alle"),
    dir: Path = typer.Option(DEFAULT_DIR, "--dir"),
    follow: bool = typer.Option(True, "--follow/--no-follow"),
):
    """Wrapper um docker compose logs."""
    instance_dir_or_raise(dir)
    args = ["logs"]
    if follow:
        args.append("-f")
    if service:
        args.append(service)
    docker.compose(dir, *args)


@app.command()
def doctor(dir: Path = typer.Option(DEFAULT_DIR, "--dir")):
    """Diagnose: Docker, Diskspace, Compose-Status."""
    _run_checks(dir)
    try:
        instance_dir_or_raise(dir)
    except FileNotFoundError:
        return
    docker.compose(dir, "ps")


@app.command()
def backup(dir: Path = typer.Option(DEFAULT_DIR, "--dir")):
    """Manuelles Backup (Postgres-Dump + .env + installation.json)."""
    instance_dir_or_raise(dir)
    path = backup_mod.create_backup(dir)
    console.print(f"[green]✔[/] Backup erstellt: {path}")


@app.command()
def update(
    dir: Path = typer.Option(DEFAULT_DIR, "--dir"),
    target: str = typer.Option(None, "--target", help="Zielversion, default = latest"),
    yes: bool = typer.Option(False, "--yes", help="Ohne Rückfrage"),
):
    """Update auf neue Version — Backup zuerst, immer."""
    instance_dir_or_raise(dir)
    state = InstallationState.load(dir)
    try:
        meta = release.get_release(target) if target else release.get_latest_release()
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]✖ Release-Metadaten konnten nicht geladen werden: {exc}[/]")
        raise typer.Exit(1) from exc

    if meta.version == state.version:
        console.print(f"[green]✔[/] Bereits auf aktueller Version {meta.version}.")
        return

    console.rule("Update")
    console.print(f"Aktuell: [bold]{state.version}[/]  →  Ziel: [bold]{meta.version}[/]")
    if meta.breaking:
        console.print("[red]⚠ Breaking Change in diesem Release.[/]")
    if meta.migration_required:
        console.print("[yellow]⚠ DB-Migration erforderlich.[/]")
    if meta.compose_revision != state.compose_revision:
        console.print(
            f"[yellow]⚠ compose.yaml wird neu generiert "
            f"(Revision {state.compose_revision} → {meta.compose_revision})[/]"
        )

    if not yes and not Confirm.ask("Update durchführen?"):
        raise typer.Exit(0)

    steps = [
        ("Backup erstellen", lambda: backup_mod.create_backup(dir)),
        ("Env-Vars ergänzen", lambda: _ensure_env_vars(dir, state.base_url)),
        (
            "compose.yaml rendern",
            lambda: write_compose(dir, version=meta.version, base_url=state.base_url, tls_mode=state.tls_mode),
        ),
        ("Images pullen", lambda: docker.compose(dir, "pull")),
        # DB-Migration läuft automatisch im api-Container-Entrypoint beim Start.
        ("Container neu starten", lambda: docker.compose(dir, "up", "-d")),
    ]

    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"), console=console) as progress:
        for description, action in steps:
            task = progress.add_task(description, total=None)
            action()
            progress.update(task, description=f"[green]✔[/] {description}")

        task = progress.add_task("Warte auf Healthcheck …", total=None)
        healthy = False
        import time

        for _ in range(30):
            if docker.is_healthy(dir):
                healthy = True
                break
            time.sleep(2)
        progress.update(
            task,
            description="[green]✔ Healthcheck OK[/]" if healthy else "[red]✖ Healthcheck fehlgeschlagen[/]",
        )

    if not healthy:
        console.print("[red]✖ Healthcheck fehlgeschlagen — `katalon rollback` erwägen.[/]")
        raise typer.Exit(1)

    state.record(meta.version, meta.compose_revision, "update")
    state.save(dir)
    console.print(f"[green]✔[/] Update auf {meta.version} abgeschlossen.")
    _print_next_steps(dir, state.base_url)


@app.command()
def rollback(
    dir: Path = typer.Option(DEFAULT_DIR, "--dir"),
    yes: bool = typer.Option(False, "--yes"),
):
    """Letztes Backup einspielen (kein Alembic-Downgrade)."""
    instance_dir_or_raise(dir)
    backup_dir = backup_mod.latest_backup(dir)
    if backup_dir is None:
        console.print("[red]✖[/] Kein Backup vorhanden.")
        raise typer.Exit(1)

    console.print(f"[yellow]⚠[/] Rollback auf Backup {backup_dir.name} — Daten seit diesem Backup gehen verloren.")
    if not yes and not Confirm.ask("Fortfahren?"):
        raise typer.Exit(0)

    state = InstallationState.load(dir)
    previous = state.previous()

    docker.compose(dir, "stop", "api", "worker", "beat")
    backup_mod.restore_backup(dir, backup_dir)

    restored_env = (dir / ".env").read_text() if (dir / ".env").exists() else ""
    missing_secrets = [
        key for key in ("SECRET_KEY", "KATALON_SECRETS_KEY")
        if not any(line.startswith(f"{key}=") for line in restored_env.splitlines())
    ]
    _ensure_env_vars(dir, state.base_url)
    if missing_secrets:
        console.print(
            f"[yellow]⚠ {', '.join(missing_secrets)} fehlte(n) im Backup und wurde(n) neu generiert — "
            "damit verschlüsselte Felder in der wiederhergestellten DB sind ggf. nicht mehr lesbar.[/]"
        )

    if previous:
        write_compose(dir, version=previous.version, base_url=state.base_url, tls_mode=state.tls_mode)
        docker.compose(dir, "pull")

    docker.compose(dir, "up", "-d")
    console.print("[green]✔[/] Rollback abgeschlossen.")


def main() -> None:
    try:
        app()
    except (FileNotFoundError, docker.DockerError, backup_mod.BackupError, subprocess.CalledProcessError) as exc:
        console.print(f"[red]✖[/] {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
