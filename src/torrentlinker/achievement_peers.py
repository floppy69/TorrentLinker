"""Explicit same-account pairing over pinned, mutually authenticated TLS.

Only the peer endpoints carry private ledger pages. The Community Site verifies
short-lived certificate-bound account proofs, never ledger evidence or addresses.
"""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import secrets
import socket
import ssl
import tempfile
import threading
import time
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.x509.oid import NameOID

HOSTNAME = "torrentlinker-peer.invalid"
MAX_BODY = 500_000
MAX_PAGES = 128


def certificate_fingerprint(pem):
    if not isinstance(pem, str) or len(pem) > 8192:
        raise ValueError("Invalid peer certificate.")
    try:
        cert = x509.load_pem_x509_certificate(pem.encode())
        return cert.fingerprint(hashes.SHA256()).hex()
    except (ValueError, TypeError):
        raise ValueError("Invalid peer certificate.") from None


def endpoint(value):
    if not isinstance(value, str) or len(value) > 300:
        raise ValueError("Use an explicit HTTPS address for this installation.")
    parsed = urlsplit(value)
    try:
        host = ipaddress.ip_address(parsed.hostname or "")
        port = parsed.port
    except ValueError:
        raise ValueError("Use a local or VPN IP address and port.") from None
    if (
        parsed.scheme != "https"
        or not host.is_private
        or host.is_unspecified
        or host.is_multicast
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in ("", "/")
        or port is None
    ):
        raise ValueError("Use a private HTTPS IP address and port without a path.")
    return str(host), port


class PinnedConnection(http.client.HTTPSConnection):
    def __init__(self, host, port, *, timeout, context):
        self.peer_context = context
        super().__init__(host, port, timeout=timeout, context=context)

    def connect(self):
        http.client.HTTPConnection.connect(self)
        self.sock = self.peer_context.wrap_socket(self.sock, server_hostname=HOSTNAME)


class PeerExchange:
    def __init__(self, sync):
        self.sync = sync
        self.lock = threading.RLock()
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.sessions: dict[str, tuple[str, str, float]] = {}
        self.statuses: dict[str, str] = {}
        self.retries: dict[str, tuple[float, int]] = {}
        self.ensure_key()
        sync.peer = self

    def ensure_key(self):
        with self.sync.lock:
            if not self.sync.config.get("certificate"):
                key = Ed25519PrivateKey.generate()
                name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, HOSTNAME)])
                now = datetime.now(UTC)
                cert = (
                    x509.CertificateBuilder()
                    .subject_name(name)
                    .issuer_name(name)
                    .public_key(key.public_key())
                    .serial_number(x509.random_serial_number())
                    .not_valid_before(now - timedelta(minutes=5))
                    .not_valid_after(now + timedelta(days=3650))
                    .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                    .add_extension(
                        x509.SubjectAlternativeName([x509.DNSName(HOSTNAME)]), critical=False
                    )
                    .sign(key, None)
                )
                self.sync.config.update(
                    certificate=cert.public_bytes(serialization.Encoding.PEM).decode(),
                    privateKey=key.private_bytes(
                        serialization.Encoding.PEM,
                        serialization.PrivateFormat.PKCS8,
                        serialization.NoEncryption(),
                    ).decode(),
                )
                self.sync._save()
            self.certificate = self.sync.config["certificate"]
            self.fingerprint = certificate_fingerprint(self.certificate)

    def state(self):
        return [
            {
                "installationId": p["installationId"],
                "fingerprint": p["fingerprint"],
                "endpoint": p["endpoint"],
                "status": self.statuses.get(p["fingerprint"], "waiting"),
            }
            for p in self.sync.config.get("peers", [])
        ]

    def invitation(self, address):
        endpoint(address)
        self.sync.identity()
        self.ensure_key()
        proof = self.sync.proof(self.fingerprint)
        return {
            "schemaVersion": 1,
            "endpoint": address,
            "certificate": self.certificate,
            "accountId": self.sync.config["accountId"],
            "installationId": self.sync.config["installationId"],
            "proof": proof["proof"],
        }

    def inspect(self, invitation):
        if (
            not isinstance(invitation, dict)
            or set(invitation)
            != {"schemaVersion", "endpoint", "certificate", "accountId", "installationId", "proof"}
            or type(invitation["schemaVersion"]) is not int
            or invitation["schemaVersion"] != 1
        ):
            raise ValueError("Unsupported pairing invitation.")
        endpoint(invitation["endpoint"])
        fp = certificate_fingerprint(invitation["certificate"])
        if (
            invitation["accountId"] != self.sync.config.get("accountId")
            or not isinstance(invitation["installationId"], str)
            or not 0 < len(invitation["installationId"]) <= 160
            or invitation["installationId"] == self.sync.config.get("installationId")
            or fp == self.fingerprint
            or not isinstance(invitation["proof"], str)
            or not 0 < len(invitation["proof"]) <= 256
        ):
            raise ValueError("Pair only a different installation of this Site Account.")
        return fp

    def add(self, invitation):
        with self.sync.lock:
            self.sync.identity()
            fp = self.inspect(invitation)
            peers = self.sync.config.get("peers", [])
            if len(peers) >= 4 or any(
                p["fingerprint"] == fp or p["installationId"] == invitation["installationId"]
                for p in peers
            ):
                raise ValueError(
                    "Remove an existing pairing first. At most four peers are supported."
                )
            verified = self.sync.verify(invitation["proof"], fp)
            if verified["installationId"] != invitation["installationId"]:
                raise ValueError("The invitation does not match its account proof.")
            self.sync.config["peers"] = [
                *peers,
                {
                    "fingerprint": fp,
                    "certificate": invitation["certificate"],
                    "installationId": verified["installationId"],
                    "endpoint": invitation["endpoint"],
                },
            ]
            self.sync._save()
        self._restart()
        return self.state()

    def remove(self, fingerprint):
        with self.sync.lock:
            self.sync.config["peers"] = [
                p for p in self.sync.config.get("peers", []) if p["fingerprint"] != fingerprint
            ]
            self.sync._save()
        with self.lock:
            self.sessions.clear()
        self._restart()
        return self.state()

    def invalidate(self):
        # Called under the sync lock. Existing sessions fail the pairing/account
        # checks even if a socket was accepted before revocation.
        with self.lock:
            self.sessions.clear()

    def context(self, *, server=False, peer=None):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER if server else ssl.PROTOCOL_TLS_CLIENT)
        context.minimum_version = ssl.TLSVersion.TLSv1_3
        context.verify_mode = ssl.CERT_REQUIRED
        trusted = self.sync.config.get("peers", []) if server else [peer]
        if trusted:
            context.load_verify_locations(cadata="\n".join(p["certificate"] for p in trusted))
        # SSL accepts file paths for the key, so use a private temporary directory;
        # the only persistent copy is in the application's encrypted secret store.
        with tempfile.TemporaryDirectory(prefix="tl-peer-key-") as directory:
            cert_path, key_path = Path(directory) / "cert.pem", Path(directory) / "key.pem"
            cert_path.write_text(self.certificate)
            key_path.write_text(self.sync.config["privateKey"])
            key_path.chmod(0o600)
            context.load_cert_chain(cert_path, key_path)
        return context

    def start(self, host, port):
        if self.server:
            return
        ip = ipaddress.ip_address(host)
        if not (ip.is_private and not ip.is_multicast and not ip.is_unspecified):
            raise ValueError("Bind pairing to a specific local or VPN interface.")
        exchange = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def do_POST(self):
                self.connection.settimeout(15)
                try:
                    fp = hashlib.sha256(self.connection.getpeercert(binary_form=True)).hexdigest()
                    length = int(self.headers.get("Content-Length", "-1"))
                    if not 0 <= length <= MAX_BODY or self.headers.get("Transfer-Encoding"):
                        raise ValueError("Invalid request size.")
                    body = json.loads(self.rfile.read(length))
                    result = exchange.handle(fp, self.path, body)
                    payload = json.dumps(result, separators=(",", ":")).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except Exception:
                    self.send_error(403, "Peer synchronization unavailable")

        class Server(ThreadingHTTPServer):
            daemon_threads = True
            # Bound active sockets; TLS handshakes time out before dispatch.
            request_queue_size = 4

            def get_request(self):
                sock, address = self.socket.accept()
                sock.settimeout(10)
                try:
                    return exchange.context(server=True).wrap_socket(
                        sock, server_side=True
                    ), address
                except Exception:
                    sock.close()
                    raise

        if ip.version == 6:
            Server.address_family = socket.AF_INET6
        self.server = Server((host, port), Handler)
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True, name="ledger-peer"
        )
        self.thread.start()

    def _restart(self):
        if self.server:
            address = self.server.server_address
            self.close()
            self.start(address[0], address[1])

    def close(self):
        server, self.server = self.server, None
        if server:
            server.shutdown()
            server.server_close()
        if self.thread:
            self.thread.join(timeout=2)
        self.invalidate()

    def handle(self, fingerprint, path, body):
        if not isinstance(body, dict):
            raise ValueError("Invalid request.")
        with self.sync.lock:
            self.sync._check_link()
            peer = next(
                (p for p in self.sync.config.get("peers", []) if p["fingerprint"] == fingerprint),
                None,
            )
            if not self.sync.config.get("pairing") or peer is None:
                raise ValueError("Unpaired installation.")
            account = self.sync.config["accountId"]
            if path == "/session" and set(body) == {"proof"}:
                verified = self.sync.verify(body["proof"], fingerprint)
                if verified["installationId"] != peer["installationId"]:
                    raise ValueError("The paired identity changed.")
                proof = self.sync.proof(self.fingerprint)
                with self.lock:
                    self.sessions = {
                        k: v for k, v in self.sessions.items() if v[2] > time.monotonic()
                    }
                    if len(self.sessions) >= 16:
                        raise ValueError("Too many peer sessions.")
                    token = secrets.token_urlsafe(32)
                    self.sessions[token] = (fingerprint, account, time.monotonic() + 120)
                return {"session": token, "proof": proof["proof"]}
            if path != "/events" or set(body) != {"session", "page", "after"}:
                raise ValueError("Invalid operation.")
            with self.lock:
                session = self.sessions.get(body["session"])
            if (
                not session
                or session[:2] != (fingerprint, account)
                or session[2] <= time.monotonic()
                or not isinstance(body["after"], str)
                or len(body["after"]) > 100
            ):
                raise ValueError("Expired peer session.")
            self.sync.ledger.merge("owner", account, body["page"])
            page = self.sync.ledger.export("owner", after=body["after"])
            self.statuses[fingerprint] = (
                "synced" if not body["page"]["events"] and not page["events"] else "continuing"
            )
            return page

    def _request(self, peer, path, body):
        host, port = endpoint(peer["endpoint"])
        connection = PinnedConnection(host, port, timeout=15, context=self.context(peer=peer))
        try:
            connection.connect()
            if (
                hashlib.sha256(connection.sock.getpeercert(binary_form=True) or b"").hexdigest()
                != peer["fingerprint"]
            ):
                raise ValueError("Peer certificate changed. Pair again.")
            payload = json.dumps(body, separators=(",", ":")).encode()
            if len(payload) > MAX_BODY:
                raise ValueError("Ledger page too large.")
            connection.request(
                "POST", path, body=payload, headers={"Content-Type": "application/json"}
            )
            response = connection.getresponse()
            data = response.read(MAX_BODY + 1)
            if response.status != 200 or len(data) > MAX_BODY:
                raise ValueError("Peer synchronization unavailable.")
            value = json.loads(data)
            if not isinstance(value, dict):
                raise ValueError("Invalid peer response.")
            return value
        finally:
            connection.close()

    def synchronize(self, *, force=True):
        with self.sync.lock:
            self.sync._check_link()
            if not self.sync.config.get("pairing"):
                return
            peers = list(self.sync.config.get("peers", []))
        for peer in peers:
            fp = peer["fingerprint"]
            due, failures = self.retries.get(fp, (0.0, 0))
            # One initiator suffices because every exchange carries both ledgers.
            # This avoids doubling the Site proof budget for a mesh of peers.
            if not force and (
                time.monotonic() < due
                or self.sync.config.get("installationId", "") > peer["installationId"]
            ):
                continue
            after_local = peer.get("afterLocal", "")
            after_remote = peer.get("afterRemote", "")
            finished = False
            try:
                proof = self.sync.proof(self.fingerprint)
                response = self._request(peer, "/session", {"proof": proof["proof"]})
                verified = self.sync.verify(response["proof"], fp)
                if verified["installationId"] != peer["installationId"]:
                    raise ValueError("Peer identity changed.")
                for _ in range(MAX_PAGES):
                    with self.sync.lock:
                        if peer not in self.sync.config.get(
                            "peers", []
                        ) or not self.sync.config.get("pairing"):
                            raise ValueError("Pairing removed.")
                        page = self.sync.ledger.export("owner", after=after_local)
                    remote = self._request(
                        peer,
                        "/events",
                        {"session": response["session"], "page": page, "after": after_remote},
                    )
                    with self.sync.lock:
                        if peer not in self.sync.config.get("peers", []):
                            raise ValueError("Pairing removed.")
                        self.sync.ledger.merge("owner", verified["accountId"], remote)
                    for records, side in ((page["events"], "local"), (remote["events"], "remote")):
                        if records:
                            cursor = records[-1]["family"] + ":" + records[-1]["identity"]
                            if side == "local":
                                after_local = cursor
                            else:
                                after_remote = cursor
                    if not page["events"] and not remote["events"]:
                        finished = True
                        break
                self.statuses[fp] = "synced" if finished else "continuing"
                self.retries[fp] = (time.monotonic() + 300, 0)
            except Exception:
                self.statuses[fp] = "offline"
                failures = min(failures + 1, 5)
                self.retries[fp] = (
                    time.monotonic() + min(3600, 300 * 2 ** (failures - 1)),
                    failures,
                )

            finally:
                with self.sync.lock:
                    if peer in self.sync.config.get("peers", []):
                        peer["afterLocal"] = "" if finished else after_local
                        peer["afterRemote"] = "" if finished else after_remote
                        self.sync._save()
