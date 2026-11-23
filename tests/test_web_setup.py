from pathlib import Path

from fastapi.testclient import TestClient

from torrentlinker.web.app import create_app


def test_settings_require_login_and_mutations_require_browser_header(tmp_path: Path):
    with TestClient(create_app(tmp_path, password="test-password-long")) as browser:
        assert browser.get("/api/setup").status_code == 401
        assert (
            browser.post("/api/login", json={"password": "test-password-long"}).status_code == 403
        )
        headers = {"X-TorrentLinker": "1"}
        assert (
            browser.post("/api/login", json={"password": "wrong"}, headers=headers).status_code
            == 401
        )
        assert (
            browser.post(
                "/api/login", json={"password": "test-password-long"}, headers=headers
            ).status_code
            == 200
        )
        setup = browser.get("/api/setup").json()
        assert setup["configured"] is False
        for flag in ("has_password", "has_api_key", "has_proxy_password", "has_announce_url"):
            assert setup[flag] is False
        assert setup["storage_roots"] == []
        assert "HttpOnly" in browser.cookies.get("tl_session", "") or browser.cookies.get(
            "tl_session"
        )


def test_setup_tests_connection_imports_folders_and_keeps_secrets_private(tmp_path: Path):
    from torrentlinker.client_folders import ClientFolder

    class Seedbox:
        def check(self):
            return "qBittorrent test"

        def folder_settings(self):
            return [ClientFolder("", "/downloads", "default")]

    seen = []

    def connect(kind, host, username, password, api_key=""):
        seen.append((host, password))
        return Seedbox()

    with TestClient(
        create_app(tmp_path, password="test-password-long", connector=connect)
    ) as browser:
        browser.headers["X-TorrentLinker"] = "1"
        browser.post("/api/login", json={"password": "test-password-long"})
        connection = {
            "client": "qbittorrent",
            "host": "https://box.example/qbit",
            "username": "owner",
            "password": "private-client-password",
            "api_key": "private-client-key",
        }
        result = browser.post("/api/setup/test-client", json=connection)
        assert result.status_code == 200, result.text
        assert result.json()["folders"][0]["path"] == "/downloads"
        assert browser.get("/api/setup").json()["configured"] is False
        saved = browser.post("/api/setup/client", json=connection)
        assert saved.status_code == 200, saved.text
        settings = browser.get("/api/setup")
        assert settings.json()["configured"] is True
        assert settings.json()["capabilities"]["manage"] is True
        assert settings.json()["capabilities"]["scan"] is False
        assert settings.json()["has_password"] is True
        assert settings.json()["has_api_key"] is True
        assert "private-client-key" not in settings.text
        assert "private-client-password" not in settings.text
        assert seen[-1] == ("https://box.example/qbit", "private-client-password")
    assert "private-client-password" not in (tmp_path / "settings.json").read_text()
    assert b"private-client-password" not in (tmp_path / "credentials.enc").read_bytes()
    with TestClient(
        create_app(tmp_path, password="test-password-long", connector=connect)
    ) as browser:
        browser.headers["X-TorrentLinker"] = "1"
        browser.post("/api/login", json={"password": "test-password-long"})
        assert browser.get("/api/setup").json()["configured"] is True
        connection.pop("password")
        assert browser.post("/api/setup/test-client", json=connection).status_code == 200
        assert seen[-1][1] == "private-client-password"


def test_folder_browser_cannot_escape_mounted_roots(tmp_path: Path):
    root = tmp_path / "media"
    root.mkdir()
    (root / "Books").mkdir()
    outside = tmp_path / "private"
    outside.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)
    with TestClient(
        create_app(tmp_path / "config", password="test-password-long", roots=(root,))
    ) as browser:
        browser.headers["X-TorrentLinker"] = "1"
        browser.post("/api/login", json={"password": "test-password-long"})
        folders = browser.get("/api/folders", params={"path": str(root)}).json()
        assert folders["folders"] == [str(root / "Books")]
        assert browser.get("/api/folders", params={"path": str(root / "escape")}).status_code == 400
        assert browser.get("/api/folders", params={"path": str(root / "..")}).status_code == 400


def test_changing_seedbox_invalidates_paths_and_pending_jobs_block_connection_changes(
    tmp_path: Path,
):
    from torrentlinker.client_folders import ClientFolder
    from torrentlinker.domain import Torrent

    root = tmp_path / "media"
    root.mkdir()
    (root / "book.epub").write_bytes(b"book")

    class Client:
        def check(self):
            return "test"

        def folder_settings(self):
            return [ClientFolder("", "/downloads", "default")]

        def torrents(self, **kwargs):
            return [Torrent("a" * 40, "book", Path("/downloads"))]

        def files(self, hash):
            return {"book.epub": 4}

    with TestClient(
        create_app(
            tmp_path / "config",
            password="test-password-long",
            roots=(root,),
            connector=lambda *args: Client(),
        )
    ) as browser:
        browser.headers["X-TorrentLinker"] = "1"
        browser.post("/api/login", json={"password": "test-password-long"})
        connection = {"client": "qbittorrent", "host": "https://one.example"}
        browser.post("/api/setup/client", json=connection)
        response = browser.post(
            "/api/setup/folder",
            json={"local": str(root), "client_path": "/downloads", "purpose": "download"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["sample"]["client"] == "/downloads/book.epub"
        # A local-looking save path must not validate an unrelated remote prefix.
        Client.torrents = lambda self, **kwargs: [Torrent("a" * 40, "book", root)]
        bad = browser.post(
            "/api/setup/folder",
            json={
                "local": str(root),
                "client_path": "/wrong-unmounted-location",
                "purpose": "download",
            },
        )
        assert bad.status_code == 400, bad.text
        connection["host"] = "https://two.example"
        browser.post("/api/setup/client", json=connection)
        assert browser.get("/api/setup").json()["download_folder"] == ""


def test_web_shell_has_guided_setup_and_no_external_asset_dependencies(tmp_path: Path):
    with TestClient(create_app(tmp_path, password="test-password-long")) as browser:
        response = browser.get("/")
        assert response.status_code == 200
        assert "app.js" in response.text
        assert "setup" in response.text
        assert "frame-ancestors" in response.headers["content-security-policy"]
        assert browser.get("/static/app.js").status_code == 200
        player = browser.get("/static/player/view.html")
        assert player.status_code == 200
        assert "frame-ancestors 'self'" in player.headers["content-security-policy"]
        assert "default-src 'none'" in player.headers["content-security-policy"]


def test_user_can_remove_a_library_folder_even_after_its_mount_disappears(tmp_path):
    from tests.test_web_jobs import Client, login

    class EmptyClient(Client):
        def files(self, hash):
            return {}

    root = tmp_path / "media"
    root.mkdir()
    with TestClient(
        create_app(
            tmp_path / "config",
            password="test-password-long",
            roots=(root,),
            connector=lambda *args: EmptyClient(),
        )
    ) as browser:
        login(browser)
        browser.post("/api/setup/client", json={"client": "deluge", "host": "https://box.example"})
        assert (
            browser.post(
                "/api/setup/folder", json={"local": str(root), "client_path": "/remote"}
            ).status_code
            == 200
        )
        root.rmdir()
        removed = browser.post(
            "/api/setup/remove-folder", json={"local": str(root), "purpose": "library"}
        )
        assert removed.status_code == 200, removed.text
        assert browser.get("/api/setup").json()["folders"] == []


def test_reverse_proxy_prefix_cannot_bypass_authentication(tmp_path: Path):
    with TestClient(
        create_app(tmp_path, password="test-password-long"), root_path="/tl"
    ) as browser:
        assert browser.get("/tl/api/setup").status_code == 401
        browser.headers["X-TorrentLinker"] = "1"
        assert (
            browser.post("/tl/api/login", json={"password": "test-password-long"}).status_code
            == 200
        )
        assert browser.get("/tl/api/setup").status_code == 200
        assert browser.get("/tl/static/app.js").status_code == 200


def test_proxy_setup_keeps_password_out_of_settings_and_can_be_disabled(tmp_path: Path):
    with TestClient(create_app(tmp_path, password="test-password-long")) as browser:
        browser.headers["X-TorrentLinker"] = "1"
        browser.post("/api/login", json={"password": "test-password-long"})
        response = browser.post(
            "/api/setup/proxy",
            json={
                "address": "socks5://proxy.example:1080",
                "username": "owner",
                "password": "proxy-private",
                "torrent_client": False,
            },
        )
        assert response.status_code == 200, response.text
        setup = browser.get("/api/setup")
        assert setup.json()["proxy"]["address"] == "socks5://proxy.example:1080"
        assert setup.json()["has_proxy_password"] is True
        assert "proxy-private" not in setup.text
        assert browser.post("/api/setup/proxy", json={"address": ""}).status_code == 200
        assert browser.get("/api/setup").json()["proxy"]["address"] == ""


def test_suggested_mapping_uses_only_allowed_storage_roots(tmp_path: Path):
    from torrentlinker.domain import Torrent

    root = tmp_path / "media"
    root.mkdir()
    (root / "book.epub").write_bytes(b"book")

    class Client:
        def check(self):
            return "test"

        def folder_settings(self):
            return []

        def torrents(self, **kwargs):
            return [Torrent("a" * 40, "book", Path("/downloads"))]

        def files(self, hash):
            return {"book.epub": 4}

    with TestClient(
        create_app(
            tmp_path / "config",
            password="test-password-long",
            roots=(root,),
            connector=lambda *args: Client(),
        )
    ) as browser:
        browser.headers["X-TorrentLinker"] = "1"
        browser.post("/api/login", json={"password": "test-password-long"})
        browser.post("/api/setup/client", json={"client": "deluge", "host": "https://box.example"})
        response = browser.post("/api/setup/suggest-mappings", json={})
        assert response.status_code == 200
        assert response.json()["suggestions"][0]["mapping"] == {
            "local": str(root),
            "qbit": "/downloads",
        }


def test_bittorrent_classic_connection_uses_webui_and_persists_its_own_profile(
    tmp_path, monkeypatch
):
    import httpx

    from tests.test_utorrent_unit import WebUI
    from torrentlinker import net

    remote = WebUI()
    monkeypatch.setattr(
        net, "client", lambda **kwargs: httpx.Client(transport=httpx.MockTransport(remote.handle))
    )
    directory = tmp_path / "config"
    connection = {
        "client": "bittorrent",
        "name": "My BitTorrent box",
        "host": "http://classic.example:8081/gui/",
        "username": "owner",
        "password": "private-classic-password",
    }
    with TestClient(create_app(directory, password="test-password-long")) as browser:
        browser.headers["X-TorrentLinker"] = "1"
        browser.post("/api/login", json={"password": "test-password-long"})
        result = browser.post("/api/setup/test-client", json=connection)
        assert result.status_code == 200, result.text
        assert result.json()["folders"][0]["path"] == r"C:\Downloads"
        saved = browser.post("/api/setup/client", json=connection)
        assert saved.status_code == 200, saved.text
        snapshot = browser.get("/api/setup")
        assert snapshot.json()["client"] == "bittorrent"
        assert "private-classic-password" not in snapshot.text
    with TestClient(create_app(directory, password="test-password-long")) as browser:
        browser.headers["X-TorrentLinker"] = "1"
        browser.post("/api/login", json={"password": "test-password-long"})
        connection.pop("password")
        assert browser.post("/api/setup/test-client", json=connection).status_code == 200
        remote.bad_password = True
        denied = browser.post("/api/setup/test-client", json=connection)
        assert denied.status_code == 400
        assert "private-classic-password" not in denied.text


def test_library_folders_can_be_registered_without_a_client_or_mapping(tmp_path):
    root = tmp_path / "media"
    root.mkdir()
    for name in ("Films", "Books"):
        (root / name).mkdir()
    with TestClient(
        create_app(tmp_path / "config", password="test-password-long", roots=(root,))
    ) as browser:
        browser.headers["X-TorrentLinker"] = "1"
        browser.post("/api/login", json={"password": "test-password-long"})
        for name in ("Films", "Books"):
            result = browser.post("/api/setup/folder", json={"local": str(root / name)})
            assert result.status_code == 200, result.text
            assert result.json()["readable"]
        settings = browser.get("/api/setup").json()
        assert [f["local"] for f in settings["folders"]] == [
            str(root / "Films"),
            str(root / "Books"),
        ]
        assert settings["mappings"] == []
        assert settings["download_folder"] == ""
        denied = browser.post("/api/setup/folder", json={"local": str(tmp_path)})
        assert denied.status_code == 400


def test_scan_without_a_client_shows_unknown_seeding_status(tmp_path):
    from tests.test_web_jobs import finished, login

    root = tmp_path / "media"
    root.mkdir()
    (root / "book.epub").write_bytes(b"book")
    with TestClient(
        create_app(tmp_path / "config", password="test-password-long", roots=(root,))
    ) as browser:
        login(browser)
        assert browser.post("/api/setup/folder", json={"local": str(root)}).status_code == 200
        created = browser.post("/api/jobs", json={"kind": "scan"})
        result = finished(browser, created.json()["id"])
        assert result["status"] in {"completed", "partial"}, result
        rows = browser.get("/api/library").json()["rows"]
        assert [(r["name"], r["state"]) for r in rows] == [("book.epub", "unknown")]


def test_reseed_folder_is_persistent_scoped_and_confined_to_storage(tmp_path):
    from torrentlinker.config import Settings

    config = tmp_path / "config"
    config.mkdir()
    links = tmp_path / "links"
    links.mkdir()
    settings = Settings()
    other = settings.add_client("Other client")
    settings.save(config / "settings.json")
    with TestClient(create_app(config, password="test-password-long", roots=(links,))) as browser:
        assert (
            browser.post("/api/setup/reseed-folder", json={"path": str(links)}).status_code == 403
        )
        browser.headers["X-TorrentLinker"] = "1"
        browser.post("/api/login", json={"password": "test-password-long"})
        assert (
            browser.post(
                "/api/setup/reseed-folder", json={"client_id": other.id, "path": str(tmp_path)}
            ).status_code
            == 400
        )
        assert (
            browser.post(
                "/api/setup/reseed-folder", json={"client_id": other.id, "path": str(links)}
            ).status_code
            == 200
        )
        assert (
            browser.get("/api/setup", params={"client_id": "default"}).json()["reseed_link_root"]
            == ""
        )
        assert browser.get("/api/reseed-workspace", params={"client_id": other.id}).json()[
            "link_root"
        ] == str(links)
        loaded = Settings.load(config / "settings.json")
        assert loaded.for_client(other.id).profile().reseed_link_root == str(links)
        assert loaded.for_client("default").profile().reseed_link_root == ""
        assert (
            browser.post(
                "/api/setup/reseed-folder", json={"client_id": other.id, "path": ""}
            ).status_code
            == 200
        )
        assert (
            Settings.load(config / "settings.json").for_client(other.id).profile().reseed_link_root
            == ""
        )


def test_announce_saved_status_exposes_no_private_url(tmp_path):
    with TestClient(create_app(tmp_path, password="test-password-long")) as browser:
        browser.headers["X-TorrentLinker"] = "1"
        browser.post("/api/login", json={"password": "test-password-long"})
        secret = "https://tracker.example/announce/private-passkey"
        assert browser.post("/api/setup/announce", json={"value": secret}).status_code == 200
        response = browser.get("/api/setup")
        assert response.json()["has_announce_url"] is True
        assert secret not in response.text
        assert "private-passkey" not in response.text
        # An empty submission is refused without removing the saved URL.
        assert browser.post("/api/setup/announce", json={"value": ""}).status_code == 400
        assert browser.get("/api/setup").json()["has_announce_url"] is True


def test_folder_preview_is_read_only_and_respects_storage_roots(tmp_path):
    root = tmp_path / "library"
    root.mkdir()
    (root / "Book.epub").write_bytes(b"book")
    (root / "Atlas.pdf").write_bytes(b"atlas")
    with TestClient(
        create_app(tmp_path / "config", password="test-password-long", roots=(root,))
    ) as browser:
        browser.headers["X-TorrentLinker"] = "1"
        browser.post("/api/login", json={"password": "test-password-long"})
        result = browser.post(
            "/api/setup/preview-folder", json={"local": str(root), "kind": "ebook", "depth": None}
        )
        assert result.status_code == 200, result.text
        assert result.json()["count"] == 2
        assert {r["name"] for r in result.json()["items"]} == {"Book.epub", "Atlas.pdf"}
        assert browser.get("/api/setup").json()["folders"] == []
        result = browser.post(
            "/api/setup/preview-folder", json={"local": str(root), "kind": "ebook", "depth": 0}
        )
        assert result.json()["count"] == 1
        assert result.json()["items"][0]["name"] == "library"
        assert (
            browser.post(
                "/api/setup/preview-folder", json={"local": str(tmp_path), "kind": "ebook"}
            ).status_code
            == 400
        )


def test_edit_folder_path_keeps_registration_during_pending_verification(tmp_path):
    from torrentlinker.domain import LibraryFolder
    from torrentlinker.web.security import ServerSecrets
    from torrentlinker.web.setup import Setup

    root = tmp_path / "storage"
    old, new = root / "old", root / "new"
    old.mkdir(parents=True)
    new.mkdir()
    config = tmp_path / "config"
    config.mkdir()
    setup = Setup(config, (root,), ServerSecrets(config))
    setup.settings.library_folders = [LibraryFolder(old)]
    setup.store.start_verification("a" * 40, old / "file.mkv", "candidate")
    with TestClient(
        create_app(config, password="test-password-long", service_override=setup)
    ) as browser:
        browser.headers["X-TorrentLinker"] = "1"
        browser.post("/api/login", json={"password": "test-password-long"})
        body = {
            "local": str(new / ".." / "new"),
            "original_local": str(old),
            "kind": "movie",
            "depth": None,
        }
        response = browser.post("/api/setup/folder", json=body)
        assert response.status_code == 400
        assert browser.get("/api/setup").json()["folders"][0]["local"] == str(old)
        setup.store.end_verification("a" * 40)
        response = browser.post("/api/setup/folder", json=body)
        assert response.status_code == 200, response.text
        assert response.json()["local"] == str(new)
        assert [f["local"] for f in browser.get("/api/setup").json()["folders"]] == [str(new)]
        assert old.is_dir()
