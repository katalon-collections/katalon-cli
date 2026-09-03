from datetime import datetime, timezone
from pathlib import Path

from katalon_cli.core.compose_gen import render_compose
from katalon_cli.core.state import InstallationState


def test_render_compose_standalone_exposes_tls_ports():
    yaml = render_compose(version="1.2.3", base_url="https://x.example", tls_mode="standalone")
    assert "ghcr.io/katalon-collections/katalon-api:1.2.3" in yaml
    assert "ghcr.io/katalon-collections/katalon-worker:1.2.3" in yaml
    assert "ghcr.io/katalon-collections/katalon-admin:1.2.3" in yaml
    assert "ghcr.io/katalon-collections/katalon-portal:1.2.3" in yaml
    assert "islandora/cantaloupe:main" in yaml
    assert '"443:443"' in yaml
    assert "./certs:/etc/nginx/certs:ro" in yaml


def test_render_compose_none_has_no_tls_ports():
    yaml = render_compose(version="1.2.3", base_url="http://localhost", tls_mode="none")
    assert '"443:443"' not in yaml
    assert "./certs:/etc/nginx/certs:ro" not in yaml
    assert '"80:80"' in yaml


def test_render_compose_behind_proxy_binds_loopback():
    yaml = render_compose(version="1.2.3", base_url="https://x.example", tls_mode="behind-proxy")
    assert "127.0.0.1:8080:80" in yaml


def test_state_roundtrip_and_history(tmp_path: Path):
    state = InstallationState(
        version="1.0.0",
        compose_revision=1,
        base_url="https://x.example",
        tls_mode="standalone",
        installed_at=datetime.now(timezone.utc),
    )
    state.record("1.0.0", 1, "install")
    state.save(tmp_path)

    loaded = InstallationState.load(tmp_path)
    assert loaded.version == "1.0.0"
    assert loaded.previous() is None

    loaded.record("1.1.0", 2, "update")
    assert loaded.version == "1.1.0"
    assert loaded.previous().version == "1.0.0"
