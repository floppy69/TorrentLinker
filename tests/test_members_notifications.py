"""Private notices are durable; optional delivery contains no private note or credentials."""

from types import SimpleNamespace

import pytest

from tests.test_members_requests import server as requests_server
from tests.test_members_signin import PASSWORD, member
from tests.test_web_jobs import login
from torrentlinker.accounts import OWNER, Accounts, Permission
from torrentlinker.member_notifications import Channels, NoticeSettings, Notifications, Preferences
from torrentlinker.member_requests import Release, Requests

RELEASE = Release("a" * 40, "Film.2025", 100, "Film", "2025")


@pytest.fixture
def store(tmp_path):
    accounts = Accounts(tmp_path)
    requests = Requests(accounts)
    vault = {}
    secrets = SimpleNamespace(get=lambda key: vault.get(key, ""), update=vault.update)
    approval = SimpleNamespace(
        refresh=lambda requests: None, margin=lambda pending: {"capacity": 0, "downloading": 0}
    )
    notices = Notifications(accounts, secrets, requests, approval)
    yield accounts, requests, notices, vault
    accounts.close()


@pytest.fixture
def server(tmp_path):
    yield from requests_server.__wrapped__(tmp_path)


def configure(notices):
    notices.save_settings(
        NoticeSettings(
            email_enabled=True,
            host="smtp.example.test",
            sender="noreply@example.test",
            app_url="https://app.example.test",
            browser_enabled=True,
        ),
        "private-password",
    )


def test_request_events_reach_only_their_recipients_and_are_not_replayed(store):
    accounts, requests, notices, _vault = store
    lea = accounts.create("Lea", "lea", {Permission.REQUEST})
    other = accounts.create("Other", "other", {Permission.REQUEST})
    approver = accounts.create("Approver", "approver", {Permission.APPROVE})
    row = requests.ask(lea, RELEASE)
    notices.collect()
    assert notices.listing(OWNER)["unread"] == notices.listing(approver)["unread"] == 1
    assert notices.listing(lea)["unread"] == notices.listing(other)["unread"] == 0
    requests.answer(row["id"], approver, refuse=True, note="Private refusal note")
    notices.collect()
    own = notices.listing(lea)["notices"]
    assert len(own) == 1 and own[0]["note"] == "Private refusal note"
    assert notices.listing(other)["notices"] == []
    notices.collect()
    assert len(notices.listing(lea)["notices"]) == 1
    notices.seen(lea)
    assert notices.listing(lea)["unread"] == 0
    accounts.grant(approver, set())
    assert notices.listing(approver)["notices"] == []


def test_wish_resolution_and_margin_crossing(store):
    accounts, requests, notices, _vault = store
    lea = accounts.create("Lea", "lea", {Permission.WISH})
    row = requests.wish(lea, "Something")
    requests.answer(row["id"], OWNER, release=RELEASE)
    notices.collect()
    assert notices.listing(lea)["notices"][0]["event"] == "wish-resolved"
    notices.save_settings(NoticeSettings(margin_gb=10))
    notices.tick()
    notices.margin_at = 0
    notices.tick()
    assert sum(n["event"] == "margin" for n in notices.listing(OWNER)["notices"]) == 1


def test_delivery_is_opt_in_minimal_and_rechecked_before_retry(store, monkeypatch):
    accounts, requests, notices, vault = store
    lea = accounts.create("Lea", "lea", {Permission.REQUEST})
    configure(notices)
    assert vault["notifications:smtp"] == "private-password"
    notices.save_preferences(
        lea,
        Preferences(
            email="lea@example.test", events={"accepted": Channels(email=True, browser=True)}
        ),
    )
    subscription = {
        "endpoint": "https://fcm.googleapis.com/push/test",
        "keys": {"p256dh": "A" * 88, "auth": "B" * 24},
    }
    notices.subscribe(lea, subscription)
    row = requests.ask(lea, RELEASE)
    requests.answer(row["id"], OWNER, note="Private path /secret/file and note")
    notices.collect()
    emails, pushes = [], []
    monkeypatch.setattr(notices, "send_email", lambda *args: emails.append(args))
    monkeypatch.setattr(notices, "push", lambda sub, payload: pushes.append(payload))
    notices.deliver()
    assert emails == [
        ("lea@example.test", "Film", "accepted", "https://app.example.test/#/media/video")
    ]
    assert len(pushes) == 1 and set(pushes[0]) == {"id", "title", "state", "url"}
    assert "secret" not in str(emails + pushes)
    notices.emit(lea, "accepted", "Second", "accepted")

    def failure(*args):
        raise RuntimeError("private-password")

    monkeypatch.setattr(notices, "send_email", failure)
    notices.deliver()
    assert (
        notices.db.execute("SELECT attempts FROM notice_outbox WHERE channel='email'").fetchone()[0]
        == 1
    )
    notices.save_preferences(lea, Preferences())
    notices.db.execute("UPDATE notice_outbox SET next_at=0")
    notices.deliver()
    assert notices.db.execute("SELECT COUNT(*) FROM notice_outbox").fetchone()[0] == 0


def test_push_keys_and_account_removal(store):
    from py_vapid import Vapid

    accounts, _requests, notices, vault = store
    lea = accounts.create("Lea", "lea", password=PASSWORD)
    configure(notices)
    public = notices.public_key()
    assert len(public) == 87 and notices.public_key() == public
    assert Vapid.from_string(vault["notifications:vapid"]).public_key
    with pytest.raises(ValueError, match="endpoint"):
        notices.subscribe(lea, {"endpoint": "https://127.0.0.1/private", "keys": {}})
    notices.subscribe(
        lea,
        {
            "endpoint": "https://fcm.googleapis.com/push/test",
            "keys": {"p256dh": "A" * 88, "auth": "B" * 24},
        },
    )
    accounts.set_password(lea, "new-password-long")
    assert notices.db.execute("SELECT COUNT(*) FROM notice_subscriptions").fetchone()[0] == 0
    notices.emit(lea, "accepted", "Film", "accepted")
    accounts.disable(lea)
    accounts.delete(lea)
    assert (
        notices.db.execute("SELECT COUNT(*) FROM notices WHERE account=?", (lea,)).fetchone()[0]
        == 0
    )


def test_settings_and_notices_are_account_scoped(server, monkeypatch):
    app, browser = server
    lea = member(app, "lea", Permission.REQUEST)
    member(app, "other", Permission.REQUEST)
    login(browser)
    config = NoticeSettings(
        email_enabled=True,
        host="smtp.example.test",
        username="private-login",
        sender="noreply@example.test",
        app_url="https://app.example.test",
    )
    assert (
        browser.post(
            "/api/notifications/settings",
            json={**config.model_dump(), "password": "secret-password"},
        ).status_code
        == 200
    )
    delivered = []
    monkeypatch.setattr(app.state.notifications, "send_email", lambda *args: delivered.append(args))
    assert (
        browser.post(
            "/api/notifications/test-email", json={"email": "owner@example.test"}
        ).status_code
        == 200
    )
    assert len(delivered) == 1
    browser.cookies.clear()
    browser.post("/api/login", json={"login": "lea", "password": PASSWORD})
    result = browser.get("/api/notifications/preferences")
    assert "private-login" not in result.text and "secret-password" not in result.text
    assert browser.post("/api/notifications/settings", json={}).status_code == 403
    assert (
        browser.post(
            "/api/notifications/test-email", json={"email": "other@example.test"}
        ).status_code
        == 403
    )
    assert (
        browser.post(
            "/api/notifications/preferences", json={"events": {"locked": {"email": True}}}
        ).status_code
        == 400
    )
    app.state.notifications.emit(lea, "accepted", "Private film", "accepted")
    assert browser.get("/api/notifications").json()["unread"] == 1
    browser.cookies.clear()
    browser.post("/api/login", json={"login": "other", "password": PASSWORD})
    assert browser.get("/api/notifications").json()["notices"] == []


@pytest.mark.parametrize("security", ["ssl", "starttls"])
def test_smtp_uses_tls_and_minimal_message(store, monkeypatch, security):
    import smtplib

    _accounts, _requests, notices, _vault = store
    notices.save_settings(
        NoticeSettings(
            email_enabled=True,
            host="mail.example.test",
            sender="noreply@example.test",
            username="noreply@example.test",
            app_url="https://app.example.test",
            security=security,
        ),
        "secret",
    )
    calls = []

    class SMTP:
        def __init__(self, host, port, **kwargs):
            calls.append(("connect", host, port, "context" in kwargs))

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def starttls(self, **kwargs):
            calls.append(("tls",))

        def login(self, user, password):
            calls.append(("login", user, password))

        def send_message(self, message):
            calls.append(("message", message))

    monkeypatch.setattr(smtplib, "SMTP_SSL", SMTP)
    monkeypatch.setattr(smtplib, "SMTP", SMTP)
    notices.send_email("lea@example.test", "Film", "available", "https://app.example.test/")
    assert calls[0][-1] is (security == "ssl")
    assert (("tls",) in calls) is (security == "starttls")
    message = calls[-1][1]
    assert message.get_content() == "Film\navailable\n\nhttps://app.example.test/\n"
    assert "secret" not in message.as_string()


def test_invitation_email_and_acceptance_and_shared_screen_notices(server, monkeypatch):
    app, browser = server
    login(browser)
    configure(app.state.notifications)
    sent = []
    monkeypatch.setattr(app.state.notifications, "send_email", lambda *args: sent.append(args))
    invite = browser.post(
        "/api/members/invite",
        json={
            "name": "New Member",
            "base": "https://app.example.test",
            "days": 3,
            "permissions": ["films"],
        },
    )
    assert invite.status_code == 200, invite.text
    invitation = invite.json()
    account = invitation["member"]["id"]
    assert (
        browser.post(
            f"/api/members/{account}/email-link", json={"email": "new@example.test"}
        ).status_code
        == 200
    )
    assert sent[0][3] == invitation["link"]["url"]
    token = invitation["link"]["url"].split("#")[1]
    redeemed = browser.post(
        "/api/links/redeem",
        json={"token": token, "password": PASSWORD, "name": "New Member", "login": "new"},
    )
    assert redeemed.status_code == 200
    browser.cookies.clear()
    assert (
        browser.post(
            "/api/login", json={"login": "new", "password": PASSWORD, "screen": "Living room"}
        ).status_code
        == 200
    )
    owner = app.state.notifications.listing(OWNER)["notices"]
    assert {row["event"] for row in owner} >= {"invitation", "screen"}
    app.state.accounts.revoke_member_access()
    assert app.state.accounts.screen(browser.cookies["tl_session"]) is None


def test_browser_subscriptions_are_bounded_and_existing_browser_can_refresh(store):
    accounts, _requests, notices, _vault = store
    lea = accounts.create("Lea", "lea", {Permission.REQUEST})
    configure(notices)
    subscription = {
        "endpoint": "https://fcm.googleapis.com/push/0",
        "keys": {"p256dh": "A" * 88, "auth": "B" * 24},
    }
    for index in range(8):
        notices.subscribe(
            lea, {**subscription, "endpoint": f"https://fcm.googleapis.com/push/{index}"}
        )
    notices.subscribe(lea, subscription)
    with pytest.raises(ValueError, match="eight browsers"):
        notices.subscribe(
            lea, {**subscription, "endpoint": "https://fcm.googleapis.com/push/extra"}
        )
    notices.unsubscribe(lea, subscription["endpoint"])
    notices.subscribe(lea, {**subscription, "endpoint": "https://fcm.googleapis.com/push/extra"})


def test_cross_seed_events_are_the_owners_alone(store):
    accounts, _requests, notices, _vault = store
    lea = accounts.create("Lea", "lea", {Permission.REQUEST})
    for event in ("cross-added", "cross-failed", "cross-review", "cross-orphan"):
        notices.emit(OWNER, event, "Show S01", "x", dedup=event)
        notices.emit(lea, event, "Show S01", "x", dedup=event)
    assert len(notices.listing(OWNER)["notices"]) == 4
    assert notices.listing(lea)["notices"] == []
