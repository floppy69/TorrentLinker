"""Run one headless server process with an exclusive configuration directory."""

from __future__ import annotations

import argparse
import ipaddress
import logging
import os
import sys
from collections.abc import Mapping
from pathlib import Path


def resolve_password(password_file: Path | None, environ: Mapping[str, str]) -> str | None:
    """Return the Web UI password, preferring the file over TL_WEB_PASSWORD."""
    if password_file is not None:
        return password_file.read_text().strip()
    value = environ.get("TL_WEB_PASSWORD", "").strip()
    return value or None


def trusted_networks(
    values: list[str], environ: Mapping[str, str]
) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    """Return the reverse proxies' networks, preferring --trusted-proxy over TL_TRUSTED_PROXIES."""
    if not values:
        values = [v for v in environ.get("TL_TRUSTED_PROXIES", "").split(",") if v.strip()]
    return tuple(ipaddress.ip_network(value.strip(), strict=False) for value in values)


def argument_parser() -> argparse.ArgumentParser:
    """Share configuration parsing with the container bootstrap."""
    parser = argparse.ArgumentParser(description="TorrentLinker Web UI")
    parser.add_argument("--host", default=os.getenv("TL_WEB_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("TL_WEB_PORT", "8787")))
    parser.add_argument(
        "--config", type=Path, default=Path(os.getenv("TL_CONFIG_DIR", "./torrentlinker-data"))
    )
    parser.add_argument("--password-file", type=Path, default=os.getenv("TL_WEB_PASSWORD_FILE"))
    parser.add_argument(
        "--web-auth",
        choices=("password", "proxy"),
        default=os.getenv("TL_WEB_AUTH", "password"),
    )
    parser.add_argument(
        "--members", choices=("on", "off"), default=os.getenv("TL_WEB_MEMBERS", "off")
    )
    parser.add_argument("--trusted-proxy", action="append", default=[])
    parser.add_argument("--root", action="append", type=Path, default=[])
    parser.add_argument(
        "--secure-cookie", action="store_true", default=os.getenv("TL_SECURE_COOKIE", "0") == "1"
    )
    parser.add_argument("--root-path", default=os.getenv("TL_ROOT_PATH", ""))
    return parser


def main() -> int:
    parser = argument_parser()
    args = parser.parse_args()
    # argparse checks choices only on the command line, not on a default from TL_WEB_AUTH.
    if args.web_auth not in ("password", "proxy"):
        parser.error(f"TL_WEB_AUTH must be password or proxy, not {args.web_auth!r}.")
    password = None
    proxies: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = ()
    if args.web_auth == "proxy":
        try:
            proxies = trusted_networks(args.trusted_proxy, os.environ)
        except ValueError as error:
            parser.error(f"Invalid trusted proxy: {error}")
        if not proxies:
            parser.error(
                "TL_WEB_AUTH=proxy needs --trusted-proxy or TL_TRUSTED_PROXIES, "
                "the networks of the reverse proxy that signs users in."
            )
        # Anyone who reaches the port from these networks is the owner.
        print(
            "TorrentLinker: the reverse proxy signs users in; only "
            + ", ".join(map(str, proxies))
            + " may use the Web UI.",
            file=sys.stderr,
            flush=True,
        )
    else:
        try:
            password = resolve_password(args.password_file, os.environ)
        except OSError as error:
            parser.error(f"Cannot read the password file: {error}")
        if password is None:
            parser.error(
                "Provide --password-file, TL_WEB_PASSWORD_FILE or TL_WEB_PASSWORD, "
                "with a password of at least 12 characters."
            )
    roots = tuple(
        args.root or [Path(p) for p in os.getenv("TL_STORAGE_ROOTS", "").split(os.pathsep) if p]
    )
    directory = args.config.resolve()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Only one process may recover jobs or use a connection's rate limits at a time.
    import fcntl

    import uvicorn

    from torrentlinker.web.app import create_app

    with (directory / "server.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error("Another TorrentLinker server already uses this configuration directory.")
        secret_files = {
            name: Path(value)
            for name in (
                "qbit-password",
                "qbit-api-key",
                "deluge-password",
                "transmission-password",
                "utorrent-password",
                "rtorrent-password",
                "indexer-api-key",
                "announce-url",
                "proxy-password",
            )
            if (value := os.getenv("TL_" + name.upper().replace("-", "_") + "_FILE"))
        }
        try:
            app = create_app(
                directory,
                password=password,
                trusted_proxies=proxies,
                roots=roots,
                secret_files=secret_files,
                secure_cookie=args.secure_cookie,
                members_enabled=args.members == "on",
            )
        except (ValueError, OSError) as error:
            parser.error(f"Cannot initialize server: {error}")
        # httpx logs each request URL at INFO, and Torznab URLs carry the API key.
        logging.getLogger("httpx").setLevel(logging.WARNING)
        uvicorn.run(
            app,
            host=args.host,
            port=args.port,
            workers=1,
            proxy_headers=False,
            root_path=args.root_path,
            access_log=False,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
