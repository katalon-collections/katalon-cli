import os
import subprocess
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from katalon_cli.core import permissions
from katalon_cli.core.permissions import ContainerUser, PermissionFixError


def _fake_compose(*, id_out="uid=1000(app) gid=1000(app) groups=1000(app)\n", chown_rc=0, writable=("api", "worker")):
    calls: list[tuple] = []

    def compose(instance_dir, *args, check=True, capture=False):
        calls.append(args)
        entrypoint = args[args.index("--entrypoint") + 1]
        service = args[args.index("--entrypoint") + 2]
        if entrypoint == "id":
            return CompletedProcess(args, 0, stdout=id_out, stderr="")
        if entrypoint == "find":
            return CompletedProcess(args, chown_rc, stdout="", stderr="chown: Operation not permitted")
        if entrypoint == "test":
            return CompletedProcess(args, 0 if service in writable else 1, stdout="", stderr="")
        raise AssertionError(args)

    return compose, calls


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("uid=1000(app) gid=1000(app) groups=1000(app)", ContainerUser(1000, 1000, "app")),
        ("uid=4711 gid=42 groups=42", ContainerUser(4711, 42, "")),
    ],
)
def test_parse_id_output(output, expected):
    assert permissions.parse_id_output(output) == expected


def test_parse_id_output_rejects_garbage():
    with pytest.raises(PermissionFixError):
        permissions.parse_id_output("sh: id: not found")


def test_fix_reads_uid_from_container_and_chowns_as_root(tmp_path):
    compose, calls = _fake_compose(id_out="uid=4711(svc) gid=42(svc)\n")
    with patch("katalon_cli.core.permissions.docker.compose", side_effect=compose):
        user = permissions.fix_media_permissions(tmp_path)

    assert user == ContainerUser(4711, 42, "svc")
    id_call, chown_call, *test_calls = calls
    assert "--user" not in id_call  # läuft als Image-User
    assert chown_call[chown_call.index("--user") + 1] == "0:0"
    find_args = chown_call[chown_call.index("--entrypoint") + 1:]
    assert find_args[0] == "find" and find_args[1] == "api"
    assert list(find_args[2:]) == permissions.chown_args(permissions.CONTAINER_MEDIA_ROOT, user)[1:]
    assert [c[c.index("--entrypoint") + 2] for c in test_calls] == ["api", "worker"]


def test_fix_raises_when_chown_fails(tmp_path):
    compose, _ = _fake_compose(chown_rc=1)
    with patch("katalon_cli.core.permissions.docker.compose", side_effect=compose), pytest.raises(PermissionFixError, match="1000:1000"):
        permissions.fix_media_permissions(tmp_path)


def test_fix_raises_when_still_not_writable(tmp_path):
    compose, _ = _fake_compose(writable=("api",))
    with patch("katalon_cli.core.permissions.docker.compose", side_effect=compose), pytest.raises(PermissionFixError, match="worker"):
        permissions.fix_media_permissions(tmp_path)


def _owners(root: Path) -> dict[str, tuple[int, int]]:
    return {
        str(path.relative_to(root)): (path.lstat().st_uid, path.lstat().st_gid)
        for path in [root, *root.rglob("*")]
    }


def _media_tree(root: Path) -> None:
    (root / "a" / "b").mkdir(parents=True)
    (root / "a" / "b" / "scan.tif").write_bytes(b"\x00image")
    (root / "top.jpg").write_bytes(b"jpg")


def test_chown_args_are_noop_when_owner_already_matches(tmp_path):
    """Läuft ohne root: Ist alles korrekt, findet `find` nichts und ruft chown nie auf."""
    _media_tree(tmp_path)
    user = ContainerUser(os.getuid(), os.getgid())
    args = permissions.chown_args(str(tmp_path), user)
    # chown durch Ausgabe ersetzen, um zu sehen, was angefasst würde
    probe = args[: args.index("-exec")] + ["-print"]
    assert subprocess.run(probe, capture_output=True, text=True, check=True).stdout == ""


@pytest.mark.skipif(os.geteuid() != 0, reason="chown auf fremde UID braucht root")
def test_chown_args_repair_wrong_owner_idempotently(tmp_path):
    media = tmp_path / "media"
    media.mkdir()
    _media_tree(media)
    os.chown(media / "a", 0, 0)
    target = ContainerUser(4711, 4712)
    before = (media / "a" / "b" / "scan.tif").read_bytes()
    mtime = (media / "a" / "b" / "scan.tif").stat().st_mtime_ns

    subprocess.run(permissions.chown_args(str(media), target), check=True)
    assert set(_owners(media).values()) == {(4711, 4712)}
    assert (media / "a" / "b" / "scan.tif").read_bytes() == before
    assert (media / "a" / "b" / "scan.tif").stat().st_mtime_ns == mtime

    probe = permissions.chown_args(str(media), target)
    probe = probe[: probe.index("-exec")] + ["-print"]
    assert subprocess.run(probe, capture_output=True, text=True, check=True).stdout == ""


def _instance(tmp_path: Path) -> Path:
    from datetime import UTC, datetime

    from katalon_cli.core.state import InstallationState

    InstallationState(
        version="1.0.0", compose_revision=1, base_url="http://localhost",
        tls_mode="none", installed_at=datetime.now(UTC),
    ).save(tmp_path)
    (tmp_path / ".env").write_text("MEDIA_ROOT=/srv/media\n")
    return tmp_path


def test_start_fixes_permissions_before_up(tmp_path):
    from katalon_cli.main import app

    dir = _instance(tmp_path)
    order: list[str] = []
    with patch("katalon_cli.main.permissions.fix_media_permissions",
               side_effect=lambda d: order.append("fix") or ContainerUser(1000, 1000, "app")), \
         patch("katalon_cli.main.docker.compose", side_effect=lambda d, *a, **k: order.append(a[0])):
        result = CliRunner().invoke(app, ["start", "--dir", str(dir)])
    assert result.exit_code == 0, result.output
    assert order[:3] == ["pull", "fix", "up"]
    assert "1000:1000 (app)" in result.output


def test_start_continues_with_clear_message_when_fix_fails(tmp_path):
    from katalon_cli.main import app

    dir = _instance(tmp_path)
    with patch("katalon_cli.main.permissions.fix_media_permissions",
               side_effect=PermissionFixError("nicht erlaubt")), \
         patch("katalon_cli.main.docker.compose") as compose:
        result = CliRunner(env={"COLUMNS": "300"}).invoke(app, ["start", "--dir", str(dir)])
    assert result.exit_code == 0, result.output
    assert [c.args[1] for c in compose.call_args_list[:2]] == ["pull", "up"]
    assert "/srv/media" in result.output and "chown -R" in result.output


def test_doctor_reports_unwritable_media_root(tmp_path):
    from katalon_cli.main import app

    dir = _instance(tmp_path)
    fake, _ = _fake_compose(writable=())

    def compose(instance_dir, *args, **kwargs):
        return fake(instance_dir, *args, **kwargs) if args[0] == "run" else CompletedProcess(args, 0)

    with patch("katalon_cli.main._run_checks", return_value=True), \
         patch("katalon_cli.core.docker.compose", side_effect=compose):
        result = CliRunner(env={"COLUMNS": "300"}).invoke(app, ["doctor", "--dir", str(dir)])
    assert "nicht beschreibbar" in result.output
    assert "api, worker" in result.output
    assert "chown -R 1000:1000 /srv/media" in result.output
