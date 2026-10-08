"""Rendert compose.yaml + nginx.conf aus Template + Release-Version + TLS-Modus."""

from __future__ import annotations

import re
import subprocess
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlparse

from jinja2 import Environment, PackageLoader, select_autoescape

_env = Environment(
    loader=PackageLoader("katalon_cli", "templates"),
    autoescape=select_autoescape(disabled_extensions=(".yaml", ".j2", ".conf")),
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_compose(
    *,
    version: str,
    base_url: str,
    tls_mode: str,
    registry: str = "ghcr.io/katalon-collections/katalon",
) -> str:
    if tls_mode == "caddy":
        caddy_host(base_url)
    parsed_port = urlparse(base_url).port
    template = _env.get_template("compose.yaml.j2")
    return template.render(
        version=version,
        base_url=base_url,
        tls_mode=tls_mode,
        registry=registry,
        port=parsed_port,
    )

def render_nginx_conf(*, tls_mode: str) -> str:
    template = _env.get_template("nginx.conf.j2")
    return template.render(tls_mode=tls_mode)


def write_compose(instance_dir: Path, **kwargs) -> Path:
    content = render_compose(**kwargs)
    path = instance_dir / "compose.yaml"
    path.write_text(content)

    nginx_path = instance_dir / "nginx.conf"
    nginx_path.write_text(render_nginx_conf(tls_mode=kwargs["tls_mode"]))

    if kwargs["tls_mode"] == "caddy":
        template = _env.get_template("Caddyfile.j2")
        (instance_dir / "Caddyfile").write_text(template.render(host=caddy_host(kwargs["base_url"])))

    if kwargs["tls_mode"] == "standalone":
        ensure_self_signed_cert(instance_dir, host=_host_of(kwargs["base_url"]))

    return path


def ensure_self_signed_cert(instance_dir: Path, *, host: str) -> None:
    """Legt ein selbstsigniertes Zertifikat an, falls keins vorhanden ist.

    Für echtes TLS eigenes Zertifikat (z.B. Let's Encrypt) unter
    <instance_dir>/certs/fullchain.pem + privkey.pem ablegen — wird nicht überschrieben.
    """
    certs_dir = instance_dir / "certs"
    fullchain = certs_dir / "fullchain.pem"
    privkey = certs_dir / "privkey.pem"
    if fullchain.exists() and privkey.exists():
        return

    certs_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "openssl", "req", "-x509", "-nodes", "-newkey", "rsa:2048",
            "-days", "825",
            "-keyout", str(privkey),
            "-out", str(fullchain),
            "-subj", f"/CN={host}",
        ],
        check=True,
        capture_output=True,
    )


def caddy_host(base_url: str) -> str:
    """Validiert die öffentliche HTTPS-Adresse vor dem Rendern der Caddy-Konfiguration."""
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").encode("idna").decode("ascii")
    try:
        ip_address(host)
        is_ip = True
    except ValueError:
        is_ip = False
    label = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    if (
        parsed.scheme != "https" or parsed.port not in (None, 443)
        or parsed.username is not None or parsed.password is not None
        or parsed.path not in ("", "/") or parsed.query or parsed.fragment
        or is_ip or len(host) > 253
        or not re.fullmatch(rf"{label}(?:\.{label})+", host)
        or host.endswith((".localhost", ".local"))
    ):
        raise ValueError("Caddy benötigt eine öffentliche Domain als https://domain.tld ohne Pfad (Port 443).")
    return host


def _host_of(base_url: str) -> str:
    return urlparse(base_url).hostname or "localhost"
