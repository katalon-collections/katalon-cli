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


def test_render_compose_worker_and_beat_have_elasticsearch_url():
    # worker/beat run reindex_all_task against Elasticsearch; without this var
    # they fall back to the package default (localhost:9200) and every
    # reindex silently fails, leaving the search index empty.
    yaml = render_compose(version="1.2.3", base_url="http://localhost", tls_mode="none")
    worker_block = yaml.split("\n  worker:")[1].split("\n  beat:")[0]
    beat_block = yaml.split("\n  beat:")[1].split("\n  admin:")[0]
    assert "ELASTICSEARCH_URL: ${ELASTICSEARCH_URL:-http://elasticsearch:9200}" in worker_block
    assert "ELASTICSEARCH_URL: ${ELASTICSEARCH_URL:-http://elasticsearch:9200}" in beat_block


def test_render_compose_behind_proxy_binds_loopback():
    yaml = render_compose(version="1.2.3", base_url="https://x.example", tls_mode="behind-proxy")
    assert "127.0.0.1:8080:80" in yaml



def test_render_compose_custom_port_none():
    yaml = render_compose(version="1.2.3", base_url="http://localhost:8080", tls_mode="none")
    assert '"8080:80"' in yaml


def test_render_compose_custom_port_behind_proxy():
    yaml = render_compose(version="1.2.3", base_url="https://x.example:8443", tls_mode="behind-proxy")
    assert "127.0.0.1:8443:80" in yaml


def test_render_nginx_conf_has_absolute_redirect_off():
    from katalon_cli.core.compose_gen import render_nginx_conf

    conf = render_nginx_conf(tls_mode="none")
    assert "absolute_redirect off;" in conf

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


def test_docker_is_running(tmp_path: Path):
    from unittest.mock import MagicMock, patch
    from katalon_cli.core import docker

    with patch("katalon_cli.core.docker.compose") as mock_compose:
        mock_compose.return_value = MagicMock(returncode=0, stdout="c123456\n")
        assert docker.is_running(tmp_path, "db") is True
        mock_compose.assert_called_once_with(
            tmp_path, "ps", "--status", "running", "-q", "db", check=False, capture=True
        )

    with patch("katalon_cli.core.docker.compose") as mock_compose:
        mock_compose.return_value = MagicMock(returncode=0, stdout="  \n")
        assert docker.is_running(tmp_path, "db") is False

    with patch("katalon_cli.core.docker.compose") as mock_compose:
        mock_compose.return_value = MagicMock(returncode=1, stdout="c123456\n")
        assert docker.is_running(tmp_path, "db") is False


def test_docker_wait_for_db(tmp_path: Path):
    from unittest.mock import MagicMock, patch
    from katalon_cli.core import docker

    with patch("katalon_cli.core.docker.compose") as mock_compose:
        mock_compose.return_value = MagicMock(returncode=0)
        assert docker.wait_for_db(tmp_path, timeout=2) is True

    with patch("katalon_cli.core.docker.compose") as mock_compose, patch("time.sleep"):
        mock_compose.return_value = MagicMock(returncode=1)
        assert docker.wait_for_db(tmp_path, timeout=2) is False
        assert mock_compose.call_count == 2


def test_ensure_db_running_when_already_running(tmp_path: Path):
    from unittest.mock import patch
    from katalon_cli.main import _ensure_db_running

    with patch("katalon_cli.core.docker.is_running", return_value=True), \
         patch("katalon_cli.core.docker.compose") as mock_compose:
        _ensure_db_running(tmp_path)
        mock_compose.assert_not_called()


def test_ensure_db_running_prompt_declined(tmp_path: Path):
    from unittest.mock import patch
    import pytest
    import typer
    from katalon_cli.main import _ensure_db_running

    with patch("katalon_cli.core.docker.is_running", return_value=False), \
         patch("rich.prompt.Confirm.ask", return_value=False):
        with pytest.raises(typer.Exit) as exc_info:
            _ensure_db_running(tmp_path)
        assert exc_info.value.exit_code == 1


def test_ensure_db_running_prompt_accepted(tmp_path: Path):
    from unittest.mock import patch
    from katalon_cli.main import _ensure_db_running

    with patch("katalon_cli.core.docker.is_running", return_value=False), \
         patch("rich.prompt.Confirm.ask", return_value=True), \
         patch("katalon_cli.core.docker.compose") as mock_compose, \
         patch("katalon_cli.core.docker.wait_for_db", return_value=True):
        _ensure_db_running(tmp_path)
        mock_compose.assert_called_once_with(tmp_path, "up", "-d", "db")


def test_ensure_db_running_yes_flag(tmp_path: Path):
    from unittest.mock import patch
    from katalon_cli.main import _ensure_db_running

    with patch("katalon_cli.core.docker.is_running", return_value=False), \
         patch("rich.prompt.Confirm.ask") as mock_confirm, \
         patch("katalon_cli.core.docker.compose") as mock_compose, \
         patch("katalon_cli.core.docker.wait_for_db", return_value=True):
        _ensure_db_running(tmp_path, yes=True)
        mock_confirm.assert_not_called()
        mock_compose.assert_called_once_with(tmp_path, "up", "-d", "db")


def test_resolve_ports_and_base_url_standalone():
    from katalon_cli.main import _resolve_ports_and_base_url

    url, ports = _resolve_ports_and_base_url("https://example.org", "standalone", False)
    assert url == "https://example.org"
    assert ports == [80, 443]


def test_resolve_ports_and_base_url_localhost_port_443_busy():
    from unittest.mock import patch
    from katalon_cli.main import _resolve_ports_and_base_url

    def mock_in_use(port):
        return port == 443

    with patch("katalon_cli.core.checks.is_port_in_use", side_effect=mock_in_use), \
         patch("rich.prompt.Confirm.ask", return_value=True), \
         patch("rich.prompt.Prompt.ask", return_value="8080"):
        url, ports = _resolve_ports_and_base_url("http://localhost", "none", True)
        assert url == "http://localhost:8080"
        assert ports == [8080]


def test_resolve_ports_and_base_url_port_busy_declined():
    from unittest.mock import patch
    from katalon_cli.main import _resolve_ports_and_base_url

    with patch("katalon_cli.core.checks.is_port_in_use", return_value=True), \
         patch("rich.prompt.Confirm.ask", return_value=False):
        url, ports = _resolve_ports_and_base_url("http://localhost:8080", "none", True)
        assert url == "http://localhost:8080"
        assert ports == [8080]
