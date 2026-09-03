# katalon-cli

Installer & Updater für [Katalon Collections](https://github.com/katalon-collections/katalon) Production-Instanzen.
Verwaltet eine Instanz unter einem Zielverzeichnis (z.B. `/opt/katalon/`) — pullt gepinnte
Release-Images, generiert `compose.yaml`, macht Backups vor jedem Update, kann rollbacken.

## Installation

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install katalon-cli
```

## Nutzung

```bash
katalon install              # interaktiver Setup-Wizard (Rich-Prompts + Progress)
katalon start / stop / status
katalon update                # interaktives Update, Backup zuerst immer
katalon rollback               # letztes Backup einspielen
katalon doctor                 # Docker, Diskspace, Ports prüfen
katalon backup                 # manuelles Backup
katalon logs [service]
```

Alle Befehle: `--dir PATH` (default `/opt/katalon`). `install`/`update` fragen interaktiv
(Auswahl über `rich.prompt`), `update`/`rollback` haben `--yes` zum Überspringen der Rückfrage.

`/opt/katalon` gehört root — `katalon install` scheitert dort ohne Vorbereitung mit
"Permission denied". `sudo katalon install` funktioniert i.d.R. nicht (sudo hat eigenes
PATH, findet das per `uv tool` installierte `katalon` nicht). Zwei Optionen:

```bash
# a) anderes Zielverzeichnis, kein root nötig
katalon install --dir ~/katalon

# b) bei /opt/katalon bleiben: Verzeichnis vorab anlegen und dem User geben
sudo mkdir -p /opt/katalon
sudo chown $USER:$USER /opt/katalon
katalon install --dir /opt/katalon
```

## Entwicklung

```bash
uv sync
uv run katalon --help
uv run pytest
```

## Architektur

- `core/state.py` — `installation.json`, Single Source of Truth für laufende Version.
- `core/release.py` — GitHub-Release-Metadaten (`katalon-release.json` Asset), 1h Cache.
- `core/compose_gen.py` + `templates/compose.yaml.j2` + `templates/nginx.conf.j2` — rendert `compose.yaml`
  + `nginx.conf` aus Version + TLS-Modus; erzeugt bei `tls_mode=standalone` ein selbstsigniertes
  Zertifikat unter `<dir>/certs/` (eigenes Zertifikat dort ablegen, um es zu ersetzen).
  `install` fragt zusätzlich `MEDIA_ROOT` ab und legt `<dir>/compose.override.yaml.example` an
  (instanzspezifische Overrides — umbenennen zu `compose.override.yaml`, wird automatisch eingebunden
  und bei Updates nicht angefasst). Optionale Env-Vars (Admin-Login, SMTP, Geonames, …) landet
  auskommentiert in `.env`.
- `core/backup.py` — `pg_dump` vor jedem Update; Rollback restauriert Dump statt `alembic downgrade`.
- `core/docker.py` — dünner `docker compose`-Subprocess-Wrapper.
- `main.py` — Typer-Commands, interaktive Teile über `rich.prompt`/`rich.progress`.
