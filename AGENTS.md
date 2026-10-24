# katalon-cli

## Versionierung

- Neue Features erhöhen die Minor-Version, z. B. `0.1.20` → `0.2.0`.
- Fehlerkorrekturen ohne neue Features erhöhen die Patch-Version, z. B. `0.2.0` → `0.2.1`.
- Projektversion in `pyproject.toml` und `uv.lock` synchron halten.
- Bereits veröffentlichte Releases und Tags bleiben unverändert. Historische Feature-Releases unter `0.1.x` werden nicht nachträglich umnummeriert.

## Images der Fremdservices

- Welche Images Postgres, Redis, Elasticsearch, Cantaloupe, nginx und Caddy nutzen, bestimmt das Katalon-Release (`images` in `katalon-release.json`, gepflegt in `release-meta.toml` von Katalon). Die CLI führt nur aus: keine Infrastruktur-Versionen ins Template schreiben, neue Versionen kommen über das Release.
- Die Defaults in `ReleaseImages` (`core/release.py`) sind der eingefrorene Stand für Releases ohne `images` (bis Katalon 1.46.0) und werden nicht angehoben.
- `requires` wird nur für Releases mit `images` geprüft; ältere Releases nannten dort ungeprüfte, teils falsche Werte.
- Ein Major-Wechsel von Postgres oder Elasticsearch bricht `update` ab. Ein geführter Upgrade-Weg (Dump/Restore, neues ES-Datenverzeichnis plus Reindex) ist erst zu bauen, wenn ein Release ihn braucht.
- Neuer Service, Ports oder Volumes ändern weiterhin das Template; dazu in Katalon `compose_revision` und `minimum_installer_version` hochziehen.
