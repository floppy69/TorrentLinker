"""Real TLS sockets and temporary keys with a fake account-proof authority."""

import copy
import secrets

import pytest

from tests.test_achievement_sync import linked
from torrentlinker.achievement_peers import PeerExchange


def peer(tmp_path, name, authority):
    sync, remote, _, _ = linked(tmp_path)
    remote["installationId"] = name
    sync.identity()
    sync.config["pairing"] = True

    def proof(fp):
        key = secrets.token_urlsafe(32)
        authority[key] = {
            "accountId": "account-a",
            "installationId": name,
            "certificateFingerprint": fp,
        }
        return {"proof": key}

    def verify(key, fp):
        data = authority.pop(key)
        if data["certificateFingerprint"] != fp or data["installationId"] == name:
            raise ValueError("Invalid peer")
        return data

    sync.proof, sync.verify = proof, verify
    return PeerExchange(sync)


def test_explicit_mutual_pairing_encrypted_merge_replay_and_removal(tmp_path):
    authority = {}
    a, b = peer(tmp_path / "a", "a", authority), peer(tmp_path / "b", "b", authority)
    try:
        ai = a.invitation("https://127.0.0.1:0")
        bi = b.invitation("https://127.0.0.1:0")
        a.add(bi)
        b.add(ai)
        a.start("127.0.0.1", 0)
        b.start("127.0.0.1", 0)
        a.sync.config["peers"][0]["endpoint"] = f"https://127.0.0.1:{b.server.server_port}"
        b.sync.config["peers"][0]["endpoint"] = f"https://127.0.0.1:{a.server.server_port}"
        a.sync.ledger.complete("owner", "playlist", "a")
        b.sync.ledger.complete("owner", "studio", "b")
        a.synchronize()
        assert {r["code"] for r in a.sync.state()["achievements"]} == {
            "playlist-first",
            "studio-first",
        }
        assert {r["code"] for r in b.sync.state()["achievements"]} == {
            "playlist-first",
            "studio-first",
        }
        a.synchronize()
        assert len(a.sync.state()["achievements"]) == 2
        assert a.sync.ledger.pending("owner") == []
        b.remove(a.fingerprint)
        a.sync.ledger.complete("owner", "rss", "c")
        a.synchronize()
        assert "rss-first" not in {r["code"] for r in b.sync.state()["achievements"]}
        assert a.state()[0]["status"] == "offline"
    finally:
        a.close()
        b.close()
        a.sync.close()
        b.sync.close()


def test_wrong_account_tampered_cert_and_unapproved_installation_rejected(tmp_path):
    authority = {}
    a, b = peer(tmp_path / "a", "a", authority), peer(tmp_path / "b", "b", authority)
    try:
        invitation = b.invitation("https://127.0.0.1:9876")
        invalid = copy.deepcopy(invitation)
        invalid["accountId"] = "someone-else"
        with pytest.raises(ValueError):
            a.add(invalid)
        invalid = copy.deepcopy(invitation)
        invalid["certificate"] = a.certificate
        with pytest.raises(ValueError):
            a.add(invalid)
        assert a.state() == []
    finally:
        a.close()
        b.close()
        a.sync.close()
        b.sync.close()


def test_session_proofs_are_single_use_and_old_sessions_fail_after_unpair(tmp_path):
    authority = {}
    a, b = peer(tmp_path / "a", "a", authority), peer(tmp_path / "b", "b", authority)
    try:
        ai = a.invitation("https://127.0.0.1:9875")
        bi = b.invitation("https://127.0.0.1:9876")
        a.add(bi)
        b.add(ai)
        proof = a.sync.proof(a.fingerprint)["proof"]
        session = b.handle(a.fingerprint, "/session", {"proof": proof})
        with pytest.raises((ValueError, KeyError)):
            b.handle(a.fingerprint, "/session", {"proof": proof})
        with pytest.raises(ValueError):
            b.handle("0" * 64, "/session", {"proof": proof})
        b.remove(a.fingerprint)
        with pytest.raises(ValueError):
            b.handle(
                a.fingerprint,
                "/events",
                {"session": session["session"], "page": a.sync.ledger.export("owner"), "after": ""},
            )
    finally:
        a.close()
        b.close()
        a.sync.close()
        b.sync.close()


def test_automatic_peer_attempts_back_off_without_losing_local_events(tmp_path):
    authority = {}
    a, b = peer(tmp_path / "a", "a", authority), peer(tmp_path / "b", "b", authority)
    try:
        a.add(b.invitation("https://127.0.0.1:9876"))
        a.sync.ledger.complete("owner", "playlist", "retained")
        attempts = []

        def offline(*args):
            attempts.append(True)
            raise OSError("Unavailable")

        a._request = offline
        a.synchronize(force=False)
        a.synchronize(force=False)
        assert len(attempts) == 1
        assert len(a.sync.state()["achievements"]) == 1
        a.synchronize(force=True)
        assert len(attempts) == 2
    finally:
        a.close()
        b.close()
        a.sync.close()
        b.sync.close()


def test_bounded_reconciliation_resumes_across_fresh_sessions(tmp_path, monkeypatch):
    import torrentlinker.achievement_peers as transport

    monkeypatch.setattr(transport, "MAX_PAGES", 1)
    authority = {}
    a, b = peer(tmp_path / "a", "a", authority), peer(tmp_path / "b", "b", authority)
    try:
        ai = a.invitation("https://127.0.0.1:0")
        bi = b.invitation("https://127.0.0.1:0")
        a.add(bi)
        b.add(ai)
        b.start("127.0.0.1", 0)
        a.sync.config["peers"][0]["endpoint"] = f"https://127.0.0.1:{b.server.server_port}"
        for i in range(550):
            a.sync.ledger.complete("owner", "playlist", str(i))
        a.synchronize()
        assert a.state()[0]["status"] == "continuing"
        assert a.sync.config["peers"][0]["afterLocal"]
        a.synchronize()
        a.synchronize()
        assert a.state()[0]["status"] == "synced"
        first = b.sync.ledger.export("owner")
        last = first["events"][-1]
        second = b.sync.ledger.export("owner", after=last["family"] + ":" + last["identity"])
        assert len(first["events"]) + len(second["events"]) == 550
    finally:
        a.close()
        b.close()
        a.sync.close()
        b.sync.close()
