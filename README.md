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
katalon doctor                 # Docker, Diskspace, Ports, Schreibrechte von MEDIA_ROOT prüfen
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

## API-Adresse

Die REST-API liegt direkt unter der Base-URL, ohne `/api`-Präfix: `<KATALON_BASE_URL>/v1/...`
(z. B. Login unter `http://127.0.0.1:8080/v1/...` bei `behind-proxy`). Unter `/api/` liegen nur
die OpenAPI-Dokumentation (`/api/docs`, `/api/openapi.json`) und interne Endpunkte;
`/api/v1/...` liefert für normale API-Aufrufe 404.

## Medienverzeichnis und Rechte

API und Worker laufen im Container als unprivilegierter User (`USER` im Image). `MEDIA_ROOT`
ist ein Bind-Mount vom Host und muss für diesen User beschreibbar sein. `katalon start`
(auch beim Install), `update` und `rollback` lesen UID/GID per `id` aus dem api-Container und
setzen in einem kurzlebigen root-Container desselben Images den Eigentümer aller Einträge
unter `MEDIA_ROOT`, die noch einem anderen Eigentümer gehören. Dateiinhalte werden nicht
verändert; ein erneuter Lauf ändert nichts. `katalon doctor` meldet ein nicht beschreibbares
`MEDIA_ROOT`, bevor Uploads mit HTTP 500 scheitern.

## Bild-Cache (Cantaloupe)

Vorschaubilder und Viewer-Kacheln rechnet Cantaloupe aus den Originalen und legt sie im
Instanzverzeichnis unter `cantaloupe-cache/` ab (abweichend: `CANTALOUPE_CACHE_DIR` in `.env`).
Der Cache übersteht Neustarts und Updates; ein kurzlebiger Init-Container übergibt das
Verzeichnis vor jedem Start dem Cantaloupe-User. Abgelaufene Derivate
(`CANTALOUPE_CACHE_SERVER_DERIVATIVE_TTL_SECONDS`, Standard 30 Tage) löscht Cantaloupe selbst.

Eine Größenbegrenzung kennt Cantaloupe nicht. Als Richtwert ~25 KB pro Vorschaubild plus
Kacheln der aufgerufenen Detailansichten einplanen; wer den Platz hart begrenzen muss, legt
`CANTALOUPE_CACHE_DIR` auf ein eigenes Dateisystem bzw. Quota-Verzeichnis. Hosts ohne
Plattenplatz nutzen mit `CANTALOUPE_FILESYSTEMCACHE_PATHNAME=/tmpfs/cache` einen RAM-Cache
(`CANTALOUPE_CACHE_TMPFS_SIZE`, Standard `512m`), der nach jedem Neustart leer ist.

Vorschaubilder lassen sich vorab berechnen, damit schon der erste Aufruf der Trefferliste
schnell ist: `katalon media warm-thumbnails` (Hauptbilder zuerst, dann die übrigen; mit
`--primary-only` nur Hauptbilder, `--status` zeigt den Fortschritt). Der Lauf arbeitet im
Worker in kleinen Paketen, belegt höchstens `THUMBNAIL_WARM_CONCURRENCY` (Standard 3)
Cantaloupe-Kerne und setzt nach einer Unterbrechung beim letzten Stand fort. Neu hochgeladene
Bilder werden automatisch vorberechnet.

Bestehende Instanzen stellt `katalon update` automatisch um (neue `compose.yaml`); der bisherige
RAM-Cache entfällt dabei. Releases, die eine neuere CLI voraussetzen, bricht `katalon update`
mit einem Hinweis auf `uv tool upgrade katalon-cli` ab.

## Domain und HTTPS

Für eine lokale Installation bleibt `http://localhost` mit TLS-Modus `none` der Standard.
Bei einer öffentlichen Domain schlägt der Setup-Wizard `caddy` vor. Du kannst auch nur
`sammlung.example.org` eingeben; mit Caddy wird daraus `https://sammlung.example.org`.

Vor der Installation müssen die DNS-Einträge wirksam sein: Der A-Record zeigt auf die öffentliche
IPv4-Adresse des Servers. Ein vorhandener AAAA-Record muss auf dessen erreichbare IPv6-Adresse
zeigen. TCP-Ports 80 und 443 müssen frei und öffentlich erreichbar sein, auch durch Server- und
Provider-Firewalls sowie gegebenenfalls Portweiterleitungen. Docker und Docker Compose müssen
installiert sein. Die CLI prüft freie Ports lokal, aber keine öffentliche DNS-Auflösung oder
Erreichbarkeit von außen.

Die TLS-Modi:

- `caddy`: Caddy läuft als Docker-Container vor dem internen nginx, belegt Ports 80 und 443,
  beantragt öffentlich vertrauenswürdige Zertifikate und erneuert sie automatisch.
  HTTP wird auf HTTPS umgeleitet. Zertifikate und Zustand liegen dauerhaft in den Docker-Volumes
  `caddy_data` und `caddy_config`, die bei Neustarts, Updates und Rollbacks erhalten bleiben.
  Dafür muss Caddy weiterlaufen, DNS muss stimmen und der Server erreichbar bleiben.
- `standalone`: nginx verwendet ein selbstsigniertes Zertifikat. Browser zeigen eine Warnung;
  es gibt keine automatische Erneuerung. Eigene Zertifikate können unter `<dir>/certs/`
  als `fullchain.pem` und `privkey.pem` abgelegt werden. Ihre Erneuerung und das anschließende
  Neuladen von nginx musst du selbst einrichten.
- `behind-proxy`: Ein eigener Reverse-Proxy übernimmt HTTPS und Zertifikate.
  Katalon ist standardmäßig nur auf `127.0.0.1:8080` erreichbar.
- `none`: HTTP ohne TLS, für lokale Tests oder IP-Adressen.

Die erste Zertifikatsausstellung kann nach dem Start kurz dauern. Bei HTTPS-Problemen:
`katalon logs caddy`. Caddy-Konfiguration und Zertifikatsverwaltung sind in der
[Caddy-Dokumentation](https://caddyserver.com/docs/automatic-https) beschrieben.
Die CLI erzeugt `<dir>/Caddyfile` bei Installation, Update und Rollback neu;
instanzspezifische Compose-Anpassungen gehören in `compose.override.yaml`.

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
  + `nginx.conf` und bei `tls_mode=caddy` das `Caddyfile` aus Version + TLS-Modus;
  erzeugt bei `tls_mode=standalone` ein selbstsigniertes
  Zertifikat unter `<dir>/certs/` (eigenes Zertifikat dort ablegen, um es zu ersetzen).
  `install` fragt zusätzlich `MEDIA_ROOT` ab und legt `<dir>/compose.override.yaml.example` an
  (instanzspezifische Overrides — umbenennen zu `compose.override.yaml`, wird automatisch eingebunden
  und bei Updates nicht angefasst). Optionale Env-Vars (Admin-Login, SMTP, Geonames, …) landet
  auskommentiert in `.env`.
- `core/backup.py` — `pg_dump` vor jedem Update; Rollback restauriert Dump statt `alembic downgrade`.
- `core/docker.py` — dünner `docker compose`-Subprocess-Wrapper.
- `main.py` — Typer-Commands, interaktive Teile über `rich.prompt`/`rich.progress`.
