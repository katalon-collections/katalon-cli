from datetime import UTC, datetime
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
        installed_at=datetime.now(UTC),
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


def test_release_metadata_env_vars_default_empty():
    from katalon_cli.core.release import ReleaseMetadata

    meta = ReleaseMetadata.model_validate({
        "version": "1.0.0",
        "minimum_installer_version": "0.1.0",
        "migration_required": False,
        "breaking": False,
        "compose_revision": 1,
    })
    assert meta.env_vars == []
    assert meta.deprecated_env_vars == []


def test_release_metadata_parses_env_vars():
    from katalon_cli.core.release import ReleaseMetadata

    meta = ReleaseMetadata.model_validate({
        "version": "1.0.0",
        "minimum_installer_version": "0.1.0",
        "migration_required": False,
        "breaking": False,
        "compose_revision": 1,
        "env_vars": [
            {"key": "OIDC_CLIENT_ID", "description": "SSO Client-ID", "required": True, "secret": False, "default": None},
        ],
        "deprecated_env_vars": [
            {"key": "OLD_AUTH_TOKEN", "note": "Ersetzt durch OIDC_CLIENT_ID"},
        ],
    })
    assert meta.env_vars[0].key == "OIDC_CLIENT_ID"
    assert meta.env_vars[0].required is True
    assert meta.deprecated_env_vars[0].note == "Ersetzt durch OIDC_CLIENT_ID"

def test_get_releases_between_includes_skipped_env_metadata(monkeypatch):
    from katalon_cli.core import release

    def payload(version: str, env_var: str) -> dict:
        return {
            "version": version,
            "minimum_installer_version": "0.1.0",
            "migration_required": False,
            "breaking": False,
            "compose_revision": 1,
            "env_vars": [{"key": env_var, "description": env_var}],
        }

    metadata = {
        "1.1.0": payload("1.1.0", "FIRST_RELEASE_VAR"),
        "1.2.0": payload("1.2.0", "SKIPPED_RELEASE_VAR"),
        "1.3.0": payload("1.3.0", "TARGET_RELEASE_VAR"),
    }
    monkeypatch.setattr(
        release,
        "_fetch_releases",
        lambda: [{"tag_name": f"v{version}"} for version in reversed(metadata)],
    )
    monkeypatch.setattr(
        release,
        "_fetch_release_asset",
        lambda tag: metadata[tag.lstrip("v")],
    )

    releases = release.get_releases_between("1.1.0", "1.3.0")

    assert [item.version for item in releases] == ["1.2.0", "1.3.0"]
    assert [item.env_vars[0].key for item in releases] == [
        "SKIPPED_RELEASE_VAR",
        "TARGET_RELEASE_VAR",
    ]


def test_ensure_env_vars_release_secret_and_default(tmp_path: Path):
    from katalon_cli.core.release import ReleaseEnvVar
    from katalon_cli.main import _ensure_env_vars, _parse_env_file

    env_vars = [
        ReleaseEnvVar(key="NEW_SECRET", required=True, secret=True),
        ReleaseEnvVar(key="NEW_WITH_DEFAULT", required=True, default="fallback"),
    ]
    _ensure_env_vars(tmp_path, "http://localhost", release_env_vars=env_vars)
    written = _parse_env_file((tmp_path / ".env").read_text())
    assert written["NEW_SECRET"]
    assert written["NEW_WITH_DEFAULT"] == "fallback"


def test_ensure_env_vars_release_optional_appended_as_comment(tmp_path: Path):
    from katalon_cli.core.release import ReleaseEnvVar
    from katalon_cli.main import _ensure_env_vars, _parse_env_file

    env_vars = [ReleaseEnvVar(key="OIDC_CLIENT_ID", description="SSO Client-ID", required=False)]
    _ensure_env_vars(tmp_path, "http://localhost", release_env_vars=env_vars)
    raw = (tmp_path / ".env").read_text()
    assert "OIDC_CLIENT_ID" not in _parse_env_file(raw)
    assert "# OIDC_CLIENT_ID=" in raw
    assert "SSO Client-ID" in raw


def test_ensure_env_vars_release_optional_not_duplicated_on_rerun(tmp_path: Path):
    from katalon_cli.core.release import ReleaseEnvVar
    from katalon_cli.main import _ensure_env_vars

    env_vars = [ReleaseEnvVar(key="OIDC_CLIENT_ID", description="SSO Client-ID", required=False)]
    _ensure_env_vars(tmp_path, "http://localhost", release_env_vars=env_vars)
    _ensure_env_vars(tmp_path, "http://localhost", release_env_vars=env_vars)
    raw = (tmp_path / ".env").read_text()
    assert raw.count("OIDC_CLIENT_ID") == 1


def test_ensure_env_vars_release_never_overwrites_existing(tmp_path: Path):
    from katalon_cli.core.release import ReleaseEnvVar
    from katalon_cli.main import _ensure_env_vars, _parse_env_file

    (tmp_path / ".env").write_text("NEW_SECRET=user-set-value\n")
    env_vars = [ReleaseEnvVar(key="NEW_SECRET", required=True, secret=True)]
    _ensure_env_vars(tmp_path, "http://localhost", release_env_vars=env_vars)
    written = _parse_env_file((tmp_path / ".env").read_text())
    assert written["NEW_SECRET"] == "user-set-value"


def test_collect_required_env_vars_yes_flag_aborts():
    import pytest
    import typer

    from katalon_cli.core.release import ReleaseEnvVar
    from katalon_cli.main import _collect_required_env_vars

    env_vars = [ReleaseEnvVar(key="NEW_REQUIRED", required=True)]
    with pytest.raises(typer.Exit) as exc_info:
        _collect_required_env_vars({}, env_vars, yes=True)
    assert exc_info.value.exit_code == 1


def test_collect_required_env_vars_prompts_interactively():
    from unittest.mock import patch

    from katalon_cli.core.release import ReleaseEnvVar
    from katalon_cli.main import _collect_required_env_vars

    env_vars = [ReleaseEnvVar(key="NEW_REQUIRED", description="Wichtig", required=True)]
    with patch("rich.prompt.Prompt.ask", return_value="user-value"):
        provided = _collect_required_env_vars({}, env_vars, yes=False)
    assert provided == {"NEW_REQUIRED": "user-value"}


def test_collect_required_env_vars_skips_secret_default_and_existing():
    from katalon_cli.core.release import ReleaseEnvVar
    from katalon_cli.main import _collect_required_env_vars

    env_vars = [
        ReleaseEnvVar(key="HAS_SECRET", required=True, secret=True),
        ReleaseEnvVar(key="HAS_DEFAULT", required=True, default="x"),
        ReleaseEnvVar(key="ALREADY_SET", required=True),
    ]
    provided = _collect_required_env_vars({"ALREADY_SET": "v"}, env_vars, yes=True)
    assert provided == {}


def test_print_deprecated_env_vars_only_warns_when_present(capsys):
    from katalon_cli.core.release import DeprecatedEnvVar
    from katalon_cli.main import _print_deprecated_env_vars

    deprecated = [DeprecatedEnvVar(key="OLD_VAR", note="Ersetzt durch NEW_VAR")]
    _print_deprecated_env_vars({}, deprecated)
    assert "OLD_VAR" not in capsys.readouterr().out
    _print_deprecated_env_vars({"OLD_VAR": "x"}, deprecated)
    out = capsys.readouterr().out
    assert "OLD_VAR" in out
    assert "Ersetzt durch NEW_VAR" in out


def test_ensure_env_vars_removes_legacy_database_url(tmp_path: Path):
    from katalon_cli.main import _ensure_env_vars, _parse_env_file

    (tmp_path / ".env").write_text("DATABASE_URL=postgresql://old\nPOSTGRES_PASSWORD=keep-me\n")
    _ensure_env_vars(tmp_path, "http://localhost")
    raw = (tmp_path / ".env").read_text()
    assert "DATABASE_URL" not in raw
    assert _parse_env_file(raw)["POSTGRES_PASSWORD"] == "keep-me"


def test_ensure_env_vars_preserves_comments_across_repeated_calls(tmp_path: Path):
    from katalon_cli.main import OPTIONAL_ENV_MARKER, _ensure_env_vars

    _ensure_env_vars(tmp_path, "http://localhost")
    _ensure_env_vars(tmp_path, "http://localhost")
    raw = (tmp_path / ".env").read_text()
    assert OPTIONAL_ENV_MARKER in raw
    assert "GEONAMES_USERNAME" in raw
    assert "SMTP_HOST" in raw


def test_check_updates_reports_available_and_current_release(tmp_path: Path):
    from unittest.mock import patch

    from typer.testing import CliRunner

    from katalon_cli.core.release import ReleaseMetadata
    from katalon_cli.main import app

    InstallationState(
        version="1.0.0",
        compose_revision=1,
        base_url="http://localhost",
        tls_mode="none",
        installed_at=datetime.now(UTC),
    ).save(tmp_path)
    runner = CliRunner()
    with patch(
        "katalon_cli.main.release.get_latest_release",
        side_effect=[
            ReleaseMetadata(
                version="1.1.0",
                minimum_installer_version="0.1.0",
                migration_required=False,
                breaking=False,
                compose_revision=1,
            ),
            ReleaseMetadata(
                version="1.0.0",
                minimum_installer_version="0.1.0",
                migration_required=False,
                breaking=False,
                compose_revision=1,
            ),
        ],
    ):
        available = runner.invoke(app, ["check-updates", "--dir", str(tmp_path)])
        current = runner.invoke(app, ["check-updates", "--dir", str(tmp_path)])

    assert available.exit_code == 0
    assert "1.0.0" in available.output
    assert "1.1.0" in available.output
    assert current.exit_code == 0
    assert "Bereits auf aktueller Version 1.0.0" in current.output
