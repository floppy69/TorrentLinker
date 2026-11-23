"""Empty Plans explain the actual gate, rather than listing unrelated remedies."""

from dataclasses import replace
from pathlib import Path

import pytest

from tests.test_plan_interfaces import plan_messages
from torrentlinker.downloads import DownloadFolders, IndexerCategory
from torrentlinker.gui.zen_view import PlanView
from torrentlinker.plan import (
    DiskSpace,
    PlanCandidate,
    PlanGoal,
    PlanOptions,
    catalogue_candidates,
    explain_inputs,
    make_plan,
)
from torrentlinker.store import CatalogueRow
from torrentlinker.zen import GB, ZenClass, ZenProfile


def test_empty_plan_reports_total_torrent_cap(qtbot):
    view = PlanView()
    qtbot.addWidget(view)
    candidate = PlanCandidate("a", "Film", GB, 10, 2030, Path("/films"), "disk")
    plan = make_plan(ZenProfile(ZenClass.SWARM_KEEPER), [candidate], {"disk": 100 * GB}, slots=0)

    view.show_plan(plan)

    assert "torrent cap" in plan_messages(view).lower()
    assert "fetch the Catalogue" not in plan_messages(view)
    assert "free some space" not in plan_messages(view)


def test_default_download_folder_refreshes_all_known_categories():
    from torrentlinker.catalogue import plan_categories
    from torrentlinker.downloads import DownloadFolders

    categories = {2000: IndexerCategory("Video"), 2030: IndexerCategory("Film", 2000)}
    assert plan_categories(None, DownloadFolders(default="/downloads"), categories) == [2000, 2030]


def test_refresh_failure_still_plans_from_usable_cached_rows(qtbot, tmp_path, monkeypatch):
    from tests.fake_qbit import FakeQbit
    from torrentlinker.config import Settings
    from torrentlinker.downloads import DownloadFolders
    from torrentlinker.gui.main_window import MainWindow
    from torrentlinker.store import CatalogueRow, CrawlState, Store

    settings = Settings()
    settings.indexer_categories = {2030: IndexerCategory("Film")}
    settings.download_folders = DownloadFolders({2030: str(tmp_path)})
    settings.plan_categories = [2030]
    store = Store(tmp_path / "state.db")
    store.save_catalogue([CatalogueRow("a" * 40, "Film", GB, 10, 2030, "", "", 1)])
    store.save_crawl_state(CrawlState(2030, limited=True))
    window = MainWindow(settings, tmp_path / "settings.json", store)
    qtbot.addWidget(window)
    monkeypatch.setattr(window, "qbit", lambda: FakeQbit())
    monkeypatch.setattr("torrentlinker.gui.main_window.get_secret", lambda *args: "test")

    def failed_refresh(work):
        window._catalogue_error = ValueError("Metadata service unavailable")
        window._after_catalogue_always()

    monkeypatch.setattr(window, "_run_catalogue", failed_refresh)
    window.make_plan()
    qtbot.waitUntil(lambda: not window.zen_tab.plan_view._busy, timeout=5000)
    view = window.zen_tab.plan_view
    assert view.plan is not None and len(view.plan.items) == 1
    assert "cached" in view.notice.lower()
    assert "refresh failed" in view.notice.lower()
    assert "Catalogue" not in plan_messages(view)


@pytest.mark.parametrize(
    "options,profile,budget,code",
    [
        (PlanOptions(max_torrents=0), ZenProfile(), 100 * GB, "plan_cap"),
        (PlanOptions(min_size=2 * GB), ZenProfile(), 100 * GB, "filters"),
        (PlanOptions(max_seeders=1), ZenProfile(), 100 * GB, "filters"),
        (PlanOptions(), ZenProfile(ZenClass.REUPLOADER), 100 * GB, "zen_class"),
        (PlanOptions(PlanGoal.ZEN), ZenProfile(seed_hours=0), 100 * GB, "seed_hours"),
        (PlanOptions(), ZenProfile(), GB - 1, "disk_space"),
        (PlanOptions(max_download_bytes=GB - 1), ZenProfile(), 100 * GB, "download_limit"),
    ],
)
def test_optimizer_reports_only_measured_blockers(options, profile, budget, code):
    candidate = PlanCandidate("a", "Film", GB, 10, 2030, Path("/films"), "disk")
    plan = make_plan(profile, [candidate], {"disk": budget}, options=options)
    assert not plan.items
    assert [issue.code for issue in plan.issues] == [code]


def test_disk_reserve_and_download_limit_are_both_reported_when_both_block():
    candidate = PlanCandidate("a", "Film", GB, 10, 2030, Path("/films"), "disk")
    space = DiskSpace("disk", Path("/films"), 2 * GB, 2 * GB)
    plan = make_plan(
        ZenProfile(),
        [candidate],
        {"disk": space.available},
        options=PlanOptions(max_download_bytes=1),
        disk_spaces=[space],
    )
    assert {issue.code for issue in plan.issues} == {"disk_space", "download_limit"}
    assert plan.disk_spaces == (space,)


@pytest.mark.parametrize(
    "change,folders,in_client,only,exclusions,code",
    [
        ({"category": None}, DownloadFolders(default="/dl"), set(), None, [], "unknown_category"),
        ({}, DownloadFolders(), set(), None, [], "no_folder"),
        ({}, DownloadFolders(default="/dl"), {"a"}, None, [], "in_client"),
        ({"seeders": 0}, DownloadFolders(default="/dl"), set(), None, [], "no_seeders"),
        ({}, DownloadFolders(default="/dl"), set(), {7000}, [], "category"),
        ({}, DownloadFolders(default="/dl"), set(), None, ["film"], "excluded_title"),
    ],
)
def test_catalogue_filter_reports_its_actual_exclusion(
    change, folders, in_client, only, exclusions, code
):
    row = replace(CatalogueRow("a", "Film", GB, 10, 2030, "", "", 1), **change)
    issues = []
    candidates = catalogue_candidates(
        [row], folders, {}, in_client, lambda p: "disk", only, exclusions, issues=issues
    )
    plan = explain_inputs(make_plan(ZenProfile(), candidates, {"disk": 100 * GB}), issues, [])
    assert [issue.code for issue in plan.issues] == [code]
    assert plan.issues[0].count == 1


def test_unrelated_categories_do_not_hide_why_selected_category_is_blocked():
    rows = [CatalogueRow(str(i), "Book", GB, 10, 7000, "", "", 1) for i in range(10)]
    rows.append(CatalogueRow("film", "Film", GB, 0, 2030, "", "", 1))
    issues = []
    catalogue_candidates(
        rows, DownloadFolders(default="/dl"), {}, set(), lambda p: 1, {2030}, issues=issues
    )
    assert [(issue.code, issue.count) for issue in issues] == [("no_seeders", 1)]


def test_successful_plan_clears_previous_diagnostics_and_coverage(qtbot):
    view = PlanView()
    qtbot.addWidget(view)
    candidate = PlanCandidate("a", "Film", GB, 10, 2030, Path("/films"), "disk")
    view.show_plan(make_plan(ZenProfile(), [candidate], {"disk": 0}))
    view.set_notice("old coverage warning")
    view.show_plan(make_plan(ZenProfile(), [candidate], {"disk": GB}))
    assert "disk space" not in plan_messages(view)
    assert not view.plan.issues
    assert view.notice == ""


def test_french_plan_diagnostic_is_available(qtbot, qapp):
    from PySide6.QtCore import QCoreApplication, QTranslator

    from torrentlinker.i18n import HERE
    from torrentlinker.plan_diagnostics import PlanIssue, issue_text

    translator = QTranslator()
    assert translator.load(str(HERE / "torrentlinker_fr.qm"))
    qapp.installTranslator(translator)
    try:
        text = issue_text(
            PlanIssue("torrent_cap"),
            lambda text: QCoreApplication.translate("PlanDiagnostics", text),
        )
        assert "plafond total de torrents est atteint" in text
    finally:
        qapp.removeTranslator(translator)


@pytest.mark.parametrize("blocker", ["no_folder", "filters", "client_budget"])
def test_distributed_plan_preserves_empty_reasons(tmp_path, blocker):
    from tests.fake_qbit import FakeQbit
    from torrentlinker.config import Settings
    from torrentlinker.multi_plan import distributed_plan
    from torrentlinker.store import Store

    settings = Settings()
    settings.indexer_categories = {2030: IndexerCategory("Film")}
    if blocker != "no_folder":
        settings.download_folders = DownloadFolders({2030: str(tmp_path)})
    if blocker == "filters":
        settings.plan_options = PlanOptions(min_size=2 * GB)
    store = Store(tmp_path / "state.db")
    store.save_catalogue([CatalogueRow("a", "Film", GB, 10, 2030, "", "", 1)])
    budget = 1 if blocker == "client_budget" else 0
    result = distributed_plan(
        settings,
        store,
        {settings.active_client_id: FakeQbit()},
        {settings.active_client_id: budget},
    )
    assert not result.items
    assert [issue.code for issue in result.issues] == [blocker]
