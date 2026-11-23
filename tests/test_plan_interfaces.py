"""Shared Plan selection, review and editing through the desktop interface."""

from pathlib import Path

from tests.test_community_interfaces import js, wait_js
from torrentlinker.gui.plan_view import PlanView
from torrentlinker.plan import Plan, PlanCandidate, PlanItem


def configure_plan(view, **changes):
    """Change planner inputs through the same public request as either renderer."""
    value = view.options
    options = {
        "plan_goal": value.goal.value,
        "maximum_bytes": value.max_download_bytes,
        "limit_torrents": value.max_torrents is not None,
        "maximum_torrents": value.max_torrents or 100,
        "minimum_torrents": value.min_torrents,
        "min_seeders": value.min_seeders,
        "max_seeders": value.max_seeders,
        "min_size": value.min_size,
        "max_size": value.max_size,
        "categories": sorted(view.chosen_categories or ()),
    }
    view.request("configure", {"options": {**options, **changes}})


def choose_plan_category(view, category):
    configure_plan(view, categories=sorted(set(view.chosen_categories or ()) | {category}))


def plan_messages(view):
    return "\n".join(issue["message"] for issue in view.state()["result"]["issues"])


def test_desktop_plan_selection_is_reviewed_before_sending(qtbot):
    view = PlanView()
    view.language = "en"
    qtbot.addWidget(view)
    view.resize(1280, 850)
    rows = [
        PlanItem(PlanCandidate("a" * 40, "Zulu", 1000, 2, 7000, Path("/books"), "disk"), 1),
        PlanItem(PlanCandidate("b" * 40, "Alpha", 2000, 3, 7000, Path("/books"), "disk"), 2),
    ]
    view.show_plan(Plan(rows, 3))
    view.show()
    wait_js(qtbot, view, "document.querySelectorAll('#plan-result tbody tr').length===2")
    js(qtbot, view, "document.querySelector('#plan-select-none').click()")
    assert js(qtbot, view, "document.querySelector('#plan-send').disabled")
    js(
        qtbot,
        view,
        "document.querySelector('[data-sort=title]').click()",
    )
    assert js(
        qtbot, view, "document.querySelector('#plan-result tbody tr').textContent.includes('Alpha')"
    )
    js(
        qtbot,
        view,
        "document.querySelector('#plan-result tbody input').click();"
        "document.querySelector('#plan-send').click()",
    )
    wait_js(qtbot, view, "document.querySelector('#dialog').open")
    assert js(
        qtbot, view, "document.querySelector('#dialog-content').textContent.includes('1 download')"
    )
    with qtbot.waitSignal(view.send_requested) as selected:
        js(qtbot, view, "document.querySelector('#dialog-content button.primary').click()")
    assert [i.candidate.infohash for i in selected.args[0].items] == ["b" * 40]


def test_plan_input_keeps_focus_and_selection_across_environment_refresh(qtbot):
    # Other GUI tests select a process-wide Qt Quick renderer. Isolate Chromium's
    # resize check so its compositor can initialize normally.
    import os
    import subprocess
    import sys

    if not os.getenv("TL_PLAN_CATALOGUE_RESIZE_CHILD"):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                f"{__file__}::test_plan_input_keeps_focus_and_selection_across_environment_refresh",
            ],
            env={**os.environ, "TL_PLAN_CATALOGUE_RESIZE_CHILD": "1"},
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return
    view = PlanView()
    qtbot.addWidget(view)
    view.language = "en"
    view.options_changed.connect(lambda _: view.invalidate())
    view.resize(620, 600)
    view.show()
    wait_js(qtbot, view, "typeof initialized!=='undefined' && initialized")
    for control in (
        "plan-category",
        "plan-goal",
        "plan-budget",
        "plan-count",
        "plan-seeders",
        "plan-min-size",
        "plan-max-size",
        "plan-cached",
    ):
        assert js(qtbot, view, f"document.getElementById('{control}').checkVisibility()")
    js(
        qtbot,
        view,
        "document.querySelector('#plan-min-size').focus();"
        "document.querySelector('#plan-min-size').value='4';"
        "document.querySelector('#plan-min-size').dispatchEvent(new Event('input',{bubbles:true}))",
    )
    view.refresh()
    wait_js(qtbot, view, "document.activeElement?.id==='plan-min-size'")
    assert js(qtbot, view, "document.querySelector('#plan-min-size').value==='4'")
    view.resize(390, 700)
    wait_js(qtbot, view, "innerWidth<=390 && document.documentElement.scrollWidth<=innerWidth")


def test_plan_progress_keeps_selection_and_stop_is_available(qtbot):
    from torrentlinker.send import SendProgress

    view = PlanView()
    qtbot.addWidget(view)
    view.language = "en"
    view.show_plan(
        Plan(
            [PlanItem(PlanCandidate("a" * 40, "Alpha", 1000, 2, 7000, Path("/books"), "disk"), 1)],
            1,
        )
    )
    view.show()
    wait_js(qtbot, view, "document.querySelectorAll('#plan-result tbody tr').length===1")
    view.sending(
        SendProgress(done=1, total=2, title="Alpha", added=1, refused=0, failed=0, zen_added=1)
    )
    wait_js(qtbot, view, "!document.querySelector('#plan-stop').hidden")
    assert js(qtbot, view, "document.querySelector('#plan-progress').textContent.includes('1/2')")
    assert js(qtbot, view, "document.querySelector('#plan-result tbody input').checked")
    assert js(qtbot, view, "document.querySelector('#plan-result tbody input').disabled")
    with qtbot.waitSignal(view.stop_send_requested):
        js(qtbot, view, "document.querySelector('#plan-stop').click()")
    view.sending(None)
    from torrentlinker.send import SendReport

    view.show_report(
        SendReport(
            added=["Alpha"],
            refused=[("Beta", "Existing files")],
            failed=[("Gamma", "Client refused")],
            stopped=True,
        )
    )
    wait_js(
        qtbot, view, "document.querySelector('#plan-outcome').textContent.includes('1 refused')"
    )
    assert js(
        qtbot,
        view,
        "document.querySelector('#plan-outcome').textContent.includes('Beta: Existing files')",
    )
    assert js(
        qtbot,
        view,
        "document.querySelector('#plan-outcome').textContent.includes('Gamma: Client refused')",
    )
    view.set_speed(12500000, "2026-11-19")
    view.configuration = lambda: {
        "client_id": "default",
        "preferences": {"download_speed": 12500000},
    }
    view.refresh()
    wait_js(qtbot, view, "document.querySelector('#plan-speed').value==='100'")


def test_plan_review_rejects_changed_client_and_queue_errors(qtbot):
    import pytest

    view = PlanView()
    qtbot.addWidget(view)
    view.show_plan(
        Plan([PlanItem(PlanCandidate("a" * 40, "Alpha", 1, 2, 7000, Path("/books"), "disk"), 1)], 1)
    )
    body = {"plan_id": view.plan_id, "hashes": ["a" * 40]}
    review = view.request("review", body.copy())
    view.configuration = lambda: {"client_id": "second"}
    with pytest.raises(ValueError, match="Review this selection"):
        view.request("send", {**body, "confirmation": review["token"]})

    def fail(action, body):
        raise OSError("Queue storage is unavailable")

    view.action = fail
    import json

    response = json.loads(view.bridge.request("queue", json.dumps(body)))
    assert "Queue storage is unavailable" in response["error"]


def test_desktop_queue_preserves_each_selected_download_destination(qtbot, tmp_path):
    from types import SimpleNamespace

    from tests.test_web_plan_execution import prepared, second_client
    from torrentlinker.download_queue import entries
    from torrentlinker.gui.plan_host import PlanHost

    _, setup, client, rows = prepared(tmp_path)
    profile, _ = second_client(tmp_path, setup, client)
    view = PlanView()
    qtbot.addWidget(view)
    owner = SimpleNamespace(
        settings=setup.settings,
        store=setup.store,
        zen_tab=SimpleNamespace(plan_view=view),
        _plan_destinations={"default": 0},
        indexer=setup.indexer,
    )
    PlanHost(owner)
    items = [
        PlanItem(
            PlanCandidate(
                row.infohash,
                row.title,
                row.size,
                row.seeders,
                row.category,
                Path(profile.download_folders.default),
                "disk",
                source=row,
                client_id=profile.id,
            ),
            1,
        )
        for row in rows
    ]
    view.show_plan(Plan(items, 3))
    result = view.request("queue", {"plan_id": view.plan_id, "hashes": [rows[1].infohash]})
    assert result == {"queued": 1}
    assert not entries(setup.store)
    queued = entries(setup.store.for_client(profile.id))
    assert len(queued) == 1
    assert queued[0].candidate.infohash == rows[1].infohash
    assert str(queued[0].folder) == profile.download_folders.default
    assert client.downloads == []


def test_plan_minimum_controls_and_size_units_survive_collapse(qtbot):
    view = PlanView()
    qtbot.addWidget(view)
    view.language = "en"
    view.resize(1280, 1000)
    view.show()
    wait_js(qtbot, view, "typeof initialized!=='undefined' && initialized")
    js(
        qtbot,
        view,
        """
      document.querySelector('#plan-min-count').value = '20';
      document.querySelector('#plan-min-seeders').value = '3';
      document.querySelector('#plan-min-size').value = '1';
      document.querySelector('[data-size-unit=min]').click();
      document.querySelector('#plan-min-count').dispatchEvent(new Event('input', {bubbles:true}));
      document.querySelector('#plan-options > summary').click();
    """,
    )
    qtbot.waitUntil(lambda: view.options.min_torrents == 20)
    assert view.options.min_seeders == 3
    assert view.options.min_size == 1024**3
    assert js(qtbot, view, "document.querySelector('#plan-min-size').value") == "1024"
    view.refresh()
    assert not js(qtbot, view, "document.querySelector('#plan-options').open")
    js(qtbot, view, "document.querySelector('#plan-options > summary').click()")
    assert js(qtbot, view, "document.querySelector('#plan-min-count').value") == "20"
    assert (
        js(qtbot, view, "document.querySelector('[data-size-unit=max]').textContent.trim()")
        == "GiB"
    )
