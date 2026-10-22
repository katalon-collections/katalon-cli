# Changelog

Format nach [Keep a Changelog](https://keepachangelog.com/de/1.1.0/). Nachträglich aus der Git-Historie erstellt; Versionen ohne eigenen Tag (0.1.1–0.1.3, 0.2.0) fehlen oder sind in der nächsten Version enthalten.

## [0.3.5] – 2026-10-22

### Geändert
- Cantaloupe ist fest auf `islandora/cantaloupe:7.0.22` gepinnt statt des beweglichen `:main`; ein `katalon update` konnte bisher unbemerkt eine andere Cantaloupe-Version ziehen. 7.0.22 enthält dieselbe Cantaloupe-Version (5.0.7) wie der zuletzt verteilte `main`-Stand.
- Cantaloupe-Heap 256 MB bis 1 GB (`CANTALOUPE_HEAP_MIN`/`CANTALOUPE_HEAP_MAX` in `.env`). Bisher galt das Image-Default von 3 GB Minimum und 5 GB Maximum; die JVM belegte unter Last fast 3 GB RAM, obwohl rund 0,6 GB genutzt werden.
- Cantaloupe loggt auf `info` statt des Image-Defaults `debug` (mehrere Zeilen pro Bildanfrage und Healthcheck, rund 30 MB am Tag auch ohne Last). Zur Fehlersuche `CANTALOUPE_LOG_LEVEL=debug` in `.env`. Das eigene Access-Log von Cantaloupe ist aus, Bildzugriffe stehen im nginx-Log.

## [0.3.4] – 2026-10-21

### Behoben
- `katalon update` und `katalon rollback` laden nginx nach `up -d` neu (`nginx -t`, `nginx -s reload`). Zuvor blieb der Container bei geänderter `nginx.conf` unverändert und lief mit der alten Konfiguration weiter, etwa ohne die Header aus 0.3.3.
- `katalon update` und `katalon reindex` prüfen vorab alle Dateisysteme des Servers und brechen ab, wenn eines zu 90 % oder mehr belegt ist. Elasticsearch verweigert ab dieser Schwelle die Shard-Allokation; der Reindex scheiterte zuvor mit einem Timeout beim Anlegen des Index, ohne die Platte als Ursache zu nennen.

## [0.3.3] – 2026-10-21

### Behoben
- nginx-Template: `server_tokens off`, außerdem `Strict-Transport-Security`, `Cross-Origin-Opener-Policy` und `Cross-Origin-Resource-Policy`, wie in `docker/nginx.conf` von Katalon. Zuvor nannte nginx seine Version, und HSTS fehlte (ZAP-Scan, karkraeg/Katalon#433). `/iiif/` sendet `Cross-Origin-Resource-Policy: cross-origin`, damit andere Seiten die Bilder einbinden können. Wirkt nach `katalon update`, das `nginx.conf` neu rendert.

## [0.3.2] – 2026-10-19

### Behoben
- `katalon reindex`: Fortschritt und Ergebnis werden auch mit dem Logformat ab Katalon 1.42 erkannt. Zuvor meldete der Befehl „0 Datensätze“, obwohl der Index vollständig neu aufgebaut war. Er zeigt jetzt die Zahl je Typ und warnt, wenn nichts indiziert wurde.

### Hinzugefügt
- `katalon update` liest `reindex_required` aus `katalon-release.json` und bietet danach den Neuaufbau des Suchindex an; `--reindex` startet ihn ohne Nachfrage.

## [0.3.1] – 2026-10-15

### Behoben
- `katalon install`/`start`: Images werden vor der Rechte-Korrektur mit sichtbarem Fortschritt geladen. Zuvor zog `docker compose run` das api-Image still im Hintergrund und der Start wirkte minutenlang hängend.
- Preflight: fehlendes Docker meldet "Docker fehlt" statt `[Errno 2] No such file or directory: 'docker'`.

## [0.3.0] – 2026-10-14

### Hinzugefügt
- `katalon media warm-thumbnails`: Vorschaubilder vorberechnen.
- IIIF: `Cache-Control` richtet sich nach Sichtbarkeit statt pauschal `public`.
- Test: kein nginx-Block verliert geerbte Sicherheits-Header.

### Geändert
- Cantaloupe-Cache liegt auf Platte statt im tmpfs.
- `katalon update` prüft die Mindestversion der CLI, die das Release verlangt.

## [0.2.1] – 2026-10-12

### Behoben
- `MEDIA_ROOT` wird für den Container-User von api/worker beschreibbar gemacht (Uploads schlugen sonst mit HTTP 500 fehl).

## [0.2.0] – 2026-10-08 (kein Tag, in 0.2.1 enthalten)

### Hinzugefügt
- Automatisches HTTPS mit Caddy; TLS-Modi `caddy`, `standalone`, `behind-proxy`, `none`.

## [0.1.20] – 2026-10-04

### Hinzugefügt
- `katalon restore` und `katalon reindex` mit Fortschrittsanzeige.

### Behoben
- Fallback-Hinweis, wenn die First-Run-Credentials-Datei bereits gelöscht ist.

## [0.1.19] – 2026-10-04

### Hinzugefügt
- `katalon manage` und Update-Check.

### Geändert
- Admin-Passwort wird bei `start` nicht mehr ausgegeben.

## [0.1.18] – 2026-10-02

### Behoben
- Instanzverzeichnis wird pro Nutzer gemerkt.

## [0.1.17] – 2026-10-01

### Behoben
- Cantaloupe-Healthcheck: `start_period` 300 s, 20 Retries.

## [0.1.16] – 2026-09-29

### Geändert
- `DEFAULT_ADMIN_PASSWORD` entfällt aus der `.env`; Warnung, das Admin-Passwort zu speichern.

## [0.1.15] – 2026-09-28

### Behoben
- `DEFAULT_ADMIN_PASSWORD` wiederhergestellt, API-Healthcheck verlängert.

## [0.1.14] – 2026-09-28

### Behoben
- Ausgabezeile für den Admin-Login vereinfacht.

## [0.1.13] – 2026-09-28

### Behoben
- Install zeigt die echten, von der API generierten Admin-Credentials statt falscher `.env`-Werte.

## [0.1.12] – 2026-09-28

### Behoben
- PostGIS-Image auf Plattform `linux/amd64` festgelegt.

## [0.1.11] – 2026-09-28

### Hinzugefügt
- Install zeigt das aufgelöste absolute Zielverzeichnis vor dem Schreiben.

## [0.1.10] – 2026-09-28

### Behoben
- `--dir` wird überall zu einem absoluten Pfad aufgelöst.

## [0.1.9] – 2026-09-20

### Geändert
- README: veralteten Cache-Hinweis entfernt.

## [0.1.8] – 2026-09-20

### Hinzugefügt
- `katalon update` zeigt das Changelog des Releases an.
- Befehl zur Update-Prüfung.

### Entfernt
- Veralteter Release-Cache.

## [0.1.7] – 2026-09-14

### Behoben
- `update`: übersprungene Releases werden in die Metadaten einbezogen.

## [0.1.6] – 2026-09-11

### Hinzugefügt
- Auswertung der Release-Metadaten `env_vars` und `deprecated_env_vars`.

## [0.1.5] – 2026-09-03

### Hinzugefügt
- Flag `--version`.

### Entfernt
- Doppelt vorhandener, toter `doctor`-Befehl.

## [0.1.4] – 2026-09-03

### Hinzugefügt
- Prüfung des DB-Zustands, Auflösung von Port-Konflikten, Rückfrage zum Starten.
