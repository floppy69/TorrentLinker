"""Cross-seed: sources, paced searches, automatic adds and the review (ADR-0024).

Every client and Indexer is a fake: nothing here reaches a real one.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import httpx
import torf
from fastapi.testclient import TestClient

from tests.fake_qbit import FakeQbit
from tests.test_web_jobs import login
from tests.torznab_fixtures import CAPS_XML
from torrentlinker.config import IndexerSettings
from torrentlinker.crossseed import CrossSeed
from torrentlinker.domain import Torrent
from torrentlinker.reseed import VERIFYING, check_verifications
from torrentlinker.torznab import TorznabIndexer
from torrentlinker.web.app import create_app
from torrentlinker.web.library import Library
from torrentlinker.web.security import ServerSecrets
from torrentlinker.web.setup import Setup


class Client(FakeQbit):
    management_controls = ("category",)

    def manage_control(self, hash: str, action: str, values: dict) -> None:
        self._set(hash, category=values["category"])


def torrent_of(root: Path, files: dict[str, bytes], source: str) -> bytes:
    """A .torrent of `root`; another `source` makes another infohash of the same data."""
    made = torf.Torrent(path=root, trackers=["https://t.example/a"], private=True, source=source)
    made.generate()
    return bytes(made.dump())


@dataclass
class Fake:
    """An Indexer with one torrent to offer (or none), counting what was asked."""

    data: bytes = b""
    searches: list[dict[str, str]] = field(default_factory=list)
    downloads: int = 0
    refuse: int = 0  # answer 429 this many times first

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/dl"):
            self.downloads += 1
            return httpx.Response(200, content=self.data)
        params = dict(request.url.params)
        if params.get("t") == "caps":
            return httpx.Response(200, text=CAPS_XML)
        self.searches.append(params)
        if self.refuse:
            self.refuse -= 1
            return httpx.Response(429, headers={"Retry-After": "900"})
        if not self.data:
            return httpx.Response(200, text="<rss><channel></channel></rss>")
        from torrentlinker.torrent_meta import read_torrent

        meta = read_torrent(self.data)
        item = (
            f"<item><title>{escape(meta.name)}</title><size>{sum(meta.files.values())}</size>"
            f'<enclosure url="https://o.example/dl"/>'
            f'<torznab:attr name="infohash" value="{meta.infohash}"/></item>'
        )
        return httpx.Response(
            200,
            text='<rss xmlns:torznab="http://torznab.com/schemas/2015/feed">'
            f"<channel>{item}</channel></rss>",
        )


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class Fixture:
    def __init__(self, tmp_path: Path, monkeypatch: Any, files: dict[str, bytes], keep=None):
        self.tmp = tmp_path
        data = tmp_path / "data"
        folder = data / "Show"
        folder.mkdir(parents=True)
        for name, content in files.items():
            (folder / name).write_bytes(content)
        self.folder = folder
        self.qbit = Client()
        self.original = torrent_of(folder, files, "ORIG")
        from torrentlinker.torrent_meta import read_torrent

        meta = read_torrent(self.original)
        self.qbit.by_hash[meta.infohash] = Torrent(
            meta.infohash,
            meta.name,
            data,
            dict(meta.files),
            frozenset(),
            1.0,
            "uploading",
            category="Series",
        )
        config = tmp_path / "config"
        config.mkdir()
        self.setup = Setup(config, (data,), ServerSecrets(config), lambda *args: self.qbit)
        self.setup.configured = True
        self.setup.settings.indexers.append(
            IndexerSettings("https://o.example/api", "other", "Other, one", True)
        )
        self.setup.secrets.update({"indexer-key-other": "KEY"})
        self.fake = Fake()
        self.clock = Clock()
        self.indexer = TorznabIndexer(
            "https://o.example/api",
            "KEY",
            "Other, one",
            http=httpx.Client(transport=httpx.MockTransport(self.fake.handler)),
            clock=self.clock.time,
            sleep=self.clock.sleep,
        )
        self.setup._torznab["other"] = (("https://o.example/api", "KEY"), self.indexer)
        # c411 has no key here, so only "Other" is searched.
        self.engine = CrossSeed(self.setup, Library(self.setup))
        self.stop = threading.Event()

    def offer(self, source: str = "CAND") -> str:
        self.fake.data = torrent_of(self.folder, {}, source)
        from torrentlinker.torrent_meta import read_torrent

        return read_torrent(self.fake.data).infohash

    def run(self) -> None:
        self.engine.enqueue()
        while self.engine.search_next("other", self.stop):
            pass

    def rows(self, state: str) -> list[dict]:
        return self.setup.store.crossseed_rows(state)

    def verified(self, hash: str) -> None:
        self.qbit.finish_check(hash, 1.0)
        check_verifications(self.engine.library.client(), self.setup.store)
        self.engine.settle()


EPISODES = {f"e{i}.mkv": bytes([i]) * (40_000 + i * 1000) for i in range(1, 11)}


def test_a_full_match_is_added_stopped_verified_started_and_tagged(tmp_path, monkeypatch):
    f = Fixture(tmp_path, monkeypatch, EPISODES)
    new = f.offer()

    f.run()

    added = f.qbit.by_hash[new]
    assert added.save_path == f.qbit.by_hash[next(iter(f.qbit.by_hash))].save_path
    assert {"cross-seed", "Other one", VERIFYING} <= added.tags
    assert added.category == "Series"
    assert added.state != "uploading"  # stopped until Verification
    assert [r["state"] for r in f.rows("verifying")] == ["verifying"]
    assert f.fake.searches and f.fake.searches[0]["apikey"] == "KEY"

    f.verified(new)

    assert f.qbit.started == [new] and VERIFYING not in f.qbit.by_hash[new].tags
    assert [r["state"] for r in f.rows("added")] == ["added"]
    assert f.rows("verifying") == []
    # Searched once per source and Indexer; the Cross-seed itself is no source.
    f.run()
    assert len(f.fake.searches) == 1


def test_a_partial_match_over_the_threshold_skips_its_missing_files(tmp_path, monkeypatch):
    f = Fixture(tmp_path, monkeypatch, EPISODES)
    new = f.offer()
    (f.folder / "e10.mkv").unlink()  # the original torrent still has it; we have 9 of 10 files
    f.qbit.by_hash[next(iter(f.qbit.by_hash))] = replace(
        next(iter(f.qbit.by_hash.values())),
        files={
            n: s
            for n, s in next(iter(f.qbit.by_hash.values())).files.items()
            if n != "Show/e10.mkv"
        },
    )
    f.engine.rules.threshold = 0.85

    f.run()

    assert f.rows("verifying")[0]["missing"] == ["Show/e10.mkv"]
    from torrentlinker.torrent_meta import read_torrent

    index = list(read_torrent(f.fake.data).files).index("Show/e10.mkv")
    assert f.qbit.priorities[new][index] == 0  # the missing file is never downloaded
    pieces = f.qbit.by_hash[new]
    assert pieces.state != "downloading"


def test_a_partial_match_under_the_threshold_waits_for_review_then_is_accepted(
    tmp_path, monkeypatch
):
    f = Fixture(tmp_path, monkeypatch, EPISODES)
    new = f.offer()
    (f.folder / "e10.mkv").unlink()
    first = next(iter(f.qbit.by_hash))
    f.qbit.by_hash[first] = replace(
        f.qbit.by_hash[first],
        files={n: s for n, s in f.qbit.by_hash[first].files.items() if not n.endswith("e10.mkv")},
    )
    f.engine.rules.threshold = 0.85  # the size window holds it; the rule then judges it
    from torrentlinker.indexer import Candidate
    from torrentlinker.review import compare_candidate
    from torrentlinker.torrent_meta import read_torrent

    source = f.engine.source("torrent:" + first)
    checked = compare_candidate(
        source.item, Candidate("x", 1, ""), read_torrent(f.fake.data), f.engine.search_rules()
    )
    f.engine.rules.auto_add = False
    f.run()
    f.engine.rules.threshold = 0.95
    assert "under the 95% threshold" in f.engine.review_reason(checked, f.engine.library.client())

    (row,) = f.rows("review")
    assert row["coverage"] < 0.95 and new not in f.qbit.by_hash
    review = next(r for r in f.engine.activity()["rows"] if r["state"] == "review")
    assert review["missing"] == ["Show/e10.mkv"] and "data" not in review

    f.engine.accept(review["id"])

    assert new in f.qbit.by_hash and f.rows("verifying")


def test_nothing_is_added_when_auto_add_is_off_or_cross_seed_paused(tmp_path, monkeypatch):
    f = Fixture(tmp_path, monkeypatch, EPISODES)
    f.offer()
    f.engine.rules.auto_add = False
    f.run()
    assert len(f.rows("review")) == 1 and "Automatic" in f.rows("review")[0]["reason"]

    paused = Fixture(tmp_path / "p", monkeypatch, EPISODES)
    (tmp_path / "p").mkdir(exist_ok=True)
    paused.offer()
    paused.engine.rules.paused = True
    paused.run()
    assert paused.fake.searches == [] and len(paused.qbit.by_hash) == 1


def test_a_torrent_the_client_already_has_is_never_added_or_downloaded(tmp_path, monkeypatch):
    f = Fixture(tmp_path, monkeypatch, EPISODES)
    existing = f.offer()
    from torrentlinker.torrent_meta import read_torrent

    meta = read_torrent(f.fake.data)
    f.qbit.by_hash[existing] = Torrent(
        existing,
        meta.name,
        f.folder.parent,
        dict(meta.files),
        frozenset({"cross-seed"}),
        1.0,
        "uploading",
    )

    f.run()

    assert f.fake.downloads == 0 and f.rows("verifying") == [] and f.rows("review") == []
    assert [r["state"] for r in f.setup.store.crossseed_rows()] == ["searched"]


def test_a_failed_verification_is_a_rejection_never_proposed_again_unless_retried(
    tmp_path, monkeypatch
):
    f = Fixture(tmp_path, monkeypatch, EPISODES)
    new = f.offer()
    f.run()

    f.qbit.finish_check(new, 0.4)
    f.engine.library.client()  # the check settles after the grace period
    check_verifications(
        f.engine.library.client(), f.setup.store, now=lambda: __import__("time").time() + 60
    )
    f.engine.settle()

    (failed,) = f.rows("failed")
    assert "Verification failed" in failed["reason"]
    assert new not in f.qbit.by_hash and f.qbit.removed == [(new, False)]
    assert (f.folder / "e1.mkv").exists()  # never data
    # A new search does not propose it again.
    for source in ("torrent:" + h for h in list(f.qbit.by_hash)):
        f.setup.store.delete_crossseed(source, "other", "")
    f.run()
    assert new not in f.qbit.by_hash

    shown = next(r for r in f.engine.activity()["rows"] if r["state"] == "failed" and r["title"])
    f.engine.retry(shown["id"])
    assert new in f.qbit.by_hash and f.rows("verifying")


def test_rejecting_a_review_remembers_it(tmp_path, monkeypatch):
    f = Fixture(tmp_path, monkeypatch, EPISODES)
    f.offer()
    f.engine.rules.auto_add = False
    f.run()
    (row,) = f.rows("review")

    f.engine.reject(next(r["id"] for r in f.engine.activity()["rows"] if r["state"] == "review"))

    assert f.rows("review") == []
    assert row["candidate_key"] in f.setup.store.rejections(f.folder)


def test_a_rate_limited_indexer_keeps_its_queue_and_rests(tmp_path, monkeypatch):
    f = Fixture(tmp_path, monkeypatch, EPISODES)
    f.offer()
    f.fake.refuse = 99

    f.run()

    assert len(f.rows("queued")) == 1
    status = f.engine.indexer_status()[0]
    assert status["queued"] == 1 and status["blocked_until"] is not None
    asked = len(f.fake.searches)  # the pacer's own retries, then it rests
    f.run()
    assert len(f.fake.searches) == asked


def test_a_removed_cross_seed_leaves_its_original_alone(tmp_path, monkeypatch):
    f = Fixture(tmp_path, monkeypatch, EPISODES)
    new = f.offer()
    f.run()
    f.verified(new)
    del f.qbit.by_hash[new]  # the Owner removes it

    f.engine.settle()

    assert f.rows("added") == [] and len(f.qbit.by_hash) == 1


def test_data_that_disappears_flags_an_orphan(tmp_path, monkeypatch):
    f = Fixture(tmp_path, monkeypatch, EPISODES)
    new = f.offer()
    f.run()
    f.verified(new)
    f.qbit._set(new, state="missingFiles")

    f.engine.settle()

    assert [r["state"] for r in f.rows("orphan")] == ["orphan"]
    f.qbit._set(new, state="uploading")
    f.engine.settle()
    assert [r["state"] for r in f.rows("added")] == ["added"]


def test_owner_routes_expose_activity_review_and_rules(tmp_path, monkeypatch):
    f = Fixture(tmp_path, monkeypatch, EPISODES)
    f.offer()
    f.engine.rules.auto_add = False
    f.run()
    f.setup.save()
    with TestClient(
        create_app(
            tmp_path / "config",
            password="test-password-long",
            service_override=f.setup,
            monitor_verifications=False,
        )
    ) as web:
        assert web.get("/api/cross-seed").status_code == 401
        login(web)
        activity = web.get("/api/cross-seed").json()
        assert activity["counts"]["review"] == 1 and activity["settings"]["threshold"] == 0.95
        assert {s["name"] for s in activity["rows"][0]["steps"]} >= {"found", "verified"}
        assert "KEY" not in str(activity)
        assert web.post("/api/cross-seed/pause").json()["paused"] is True
        assert web.post("/api/cross-seed/resume").json()["paused"] is False
        saved = web.post("/api/cross-seed/settings", json={"threshold": 0.9, "auto_add": True})
        assert saved.json()["threshold"] == 0.9
        assert web.post("/api/cross-seed/settings", json={"threshold": 0.1}).status_code == 422
        row = next(r for r in activity["rows"] if r["state"] == "review")
        assert web.post(f"/api/cross-seed/{row['id']}/reject").status_code == 200
        assert web.get("/api/cross-seed?state=review").json()["rows"] == []
        assert web.get("/api/cross-seed?state=bogus").status_code == 400


def test_a_library_item_is_a_source_and_a_seeded_one_is_not(tmp_path, monkeypatch):
    from torrentlinker.domain import ContentKind, ItemState, LibraryFolder
    from torrentlinker.library import LibraryEntry
    from torrentlinker.scan import scan_item

    f = Fixture(tmp_path, monkeypatch, EPISODES)
    (client_hash,) = f.qbit.by_hash
    del f.qbit.by_hash[client_hash]  # the Library Item has no torrent: an Orphan
    folder = LibraryFolder(f.folder.parent, 1, ContentKind.SERIES)
    item = scan_item(f.folder)
    f.engine.library.entries = [
        LibraryEntry(folder, item, ItemState.ORPHAN),
        LibraryEntry(folder, scan_item(f.folder), ItemState.SEEDED),
    ]
    new = f.offer()

    assert f.engine.enqueue() == 1  # the seeded one is covered by its torrent
    f.run()

    assert new in f.qbit.by_hash and f.rows("verifying")[0]["origin"] == "item"
    assert f.fake.searches[0]["t"] == "tvsearch"


def test_the_size_window_reaches_down_to_the_review_floor(tmp_path, monkeypatch):
    f = Fixture(tmp_path, monkeypatch, EPISODES)
    f.engine.rules.threshold = 0.95
    floor = f.engine.root.settings.matching.rules().min_partial_coverage

    # A torrent big enough to cover only the floor is fetched (it then waits for review).
    assert f.engine.search_rules().size_tolerance >= 1 / floor - 1


def test_a_review_row_tells_if_its_match_is_an_archive_and_for_which_item(tmp_path, monkeypatch):
    f = Fixture(tmp_path, monkeypatch, EPISODES)
    f.offer()
    f.engine.rules.auto_add = False
    f.run()

    (row,) = f.engine.activity("review")["rows"]

    assert row["archive"] is False and row["item_path"] == str(f.folder)


def test_an_orphan_is_removed_from_the_client_keeping_its_data(tmp_path, monkeypatch):
    f = Fixture(tmp_path, monkeypatch, EPISODES)
    new = f.offer()
    f.run()
    f.verified(new)
    f.qbit._set(new, state="missingFiles")
    f.engine.settle()
    (orphan,) = f.engine.activity("orphan")["rows"]

    f.engine.remove(orphan["id"])

    assert (new, False) in f.qbit.removed and f.rows("orphan") == []
    try:
        f.engine.remove(orphan["id"])
    except ValueError:
        pass
    else:
        raise AssertionError("an unknown Cross-seed cannot be removed")


def notices_of(f: Fixture) -> list[tuple[str, str, str]]:
    sent: list[tuple[str, str, str]] = []
    f.engine.notify = lambda event, title, state, note, dedup: sent.append((event, state, note))
    return sent


def test_the_owner_hears_of_an_added_cross_seed_and_a_failed_verification(tmp_path, monkeypatch):
    f = Fixture(tmp_path, monkeypatch, EPISODES)
    sent = notices_of(f)
    new = f.offer()
    f.run()
    f.verified(new)
    f.engine.settle()  # not told twice
    assert [e for e, *_ in sent] == ["cross-added"]


def test_the_owner_hears_of_a_failed_verification(tmp_path, monkeypatch):
    f = Fixture(tmp_path, monkeypatch, EPISODES)
    sent = notices_of(f)
    bad = f.offer()
    f.run()
    f.qbit.finish_check(bad, 0.4)
    check_verifications(
        f.engine.library.client(), f.setup.store, now=lambda: __import__("time").time() + 60
    )
    f.engine.settle()
    assert [e for e, *_ in sent] == ["cross-failed"]
    assert "Verification failed" in sent[0][2]


def test_one_notice_tells_of_the_matches_waiting_for_review(tmp_path, monkeypatch):
    f = Fixture(tmp_path, monkeypatch, EPISODES)
    sent = notices_of(f)
    f.offer()
    f.engine.rules.auto_add = False
    f.run()
    assert [(e, s) for e, s, _ in sent] == [("cross-review", "1 waiting for review")]


def test_data_that_disappears_is_an_orphan_with_its_reason_and_a_notice(tmp_path, monkeypatch):
    f = Fixture(tmp_path, monkeypatch, EPISODES)
    sent = notices_of(f)
    new = f.offer()
    f.run()
    f.verified(new)
    f.qbit._set(new, state="error")
    f.engine.settle()
    f.engine.settle()
    (row,) = f.rows("orphan")
    assert "error" in row["reason"]
    assert [e for e, *_ in sent] == ["cross-added", "cross-orphan"]

    f.qbit._set(new, state="uploading")
    f.engine.settle()
    moved = f.folder.rename(f.folder.with_name("moved"))  # the files vanish; nothing is deleted
    f.engine.settle()
    (row,) = f.rows("orphan")
    assert "files are missing" in row["reason"] and (moved / "e1.mkv").exists()
    assert [e for e, *_ in sent].count("cross-orphan") == 2
