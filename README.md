# katalon-cli

Installer & Updater für [Katalon Collections](https://github.com/katalon-collections/katalon) Production-Instanzen.
Verwaltet eine Instanz unter einem frei gewählten Zielverzeichnis — pullt gepinnte
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
katalon check-updates         # prüft nur, ob ein neues Release verfügbar ist
katalon update                # interaktives Update, Backup zuerst immer
katalon rollback               # letztes Backup einspielen
katalon doctor                 # Docker, Diskspace, Ports prüfen
katalon backup                 # manuelles Backup
katalon logs [service]
katalon manage <args>          # katalon-manage im api-Container (z.B. reset-admin, create-user)
katalon restore DUMP           # DB durch pg_dump ersetzen (-Fc oder SQL), danach Reindex
katalon reindex                # Suchindex neu aufbauen, mit Fortschrittsanzeige
```

Ein DB-Dump enthält nicht den Suchindex (Elasticsearch). `restore` baut ihn deshalb nach dem
Einspielen neu auf (`--no-reindex` zum Überspringen, später `katalon reindex`). Bei großen
Beständen dauert das lange (ca. 45 Min. für 80k Datensätze). Außerdem prüft `katalon` einmal
täglich auf neue Versionen (abschalten: `KATALON_NO_UPDATE_CHECK=1`).

`install` ohne `--dir` fragt das Zielverzeichnis interaktiv ab. Nach erfolgreicher Einrichtung
wird der absolute Pfad benutzerweit in `~/.config/katalon/instance` gespeichert.
Bei gesetztem, absolutem `XDG_CONFIG_HOME` liegt die Datei stattdessen unter
`$XDG_CONFIG_HOME/katalon/instance`. Das Konfigurationsverzeichnis wird bei Bedarf angelegt.
Alle weiteren Befehle verwenden den gespeicherten Pfad, unabhängig vom Arbeitsverzeichnis.
Ohne gespeicherten Pfad ist der Default auf allen Plattformen `~/katalon`.

Alle Befehle unterstützen `--dir PATH`: überschreibt den Pfad nur für diesen Aufruf.
Eine erfolgreiche neue Installation speichert ihr Zielverzeichnis als neuen Default.
Bestehende Instanzen lassen sich weiterhin mit `--dir` verwenden; alternativ ihren absoluten
Pfad als einzige Zeile in die Konfigurationsdatei eintragen.
`install`/`update` fragen interaktiv (Auswahl über `rich.prompt`),
`update`/`rollback` haben `--yes` zum Überspringen der Rückfrage.

```bash
katalon install --dir ~/meine-katalon-instanz
katalon start
katalon status
```

## Entwicklung

```bash
uv sync
uv run katalon --help
uv run pytest
```

## Architektur

- `core/state.py` — `installation.json`, Single Source of Truth für laufende Version.
- `core/release.py` — GitHub-Release-Metadaten (`katalon-release.json` Asset). Enthält
  optional `env_vars`/`deprecated_env_vars`: `install`/`update` ergänzen neue Pflichtvariablen
  automatisch (Secret generieren oder Default übernehmen), fragen bei fehlendem Default interaktiv
  nach (`--yes` bricht dann ab), tragen neue optionale Variablen auskommentiert in `.env` ein und
  warnen vor veralteten Variablen, die noch in der `.env` stehen.
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
