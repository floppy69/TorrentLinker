import json
import shutil
import zipfile
from types import SimpleNamespace

import pytest
from PIL import Image
from pydantic import ValidationError

from torrentlinker.studio import Keyframe, Project, Segment, Studio, Track, interpolate
from torrentlinker.studio_render import frame, render


@pytest.fixture
def studio(tmp_path):
    return Studio(SimpleNamespace(path=tmp_path / "settings.json"))


def test_curves_and_project_bounds():
    keys = [
        Keyframe(time=0, value=0, interpolation="bezier", curve=(0.42, 0, 0.58, 1)),
        Keyframe(time=2, value=1),
    ]
    assert interpolate(keys, 1, 8) == pytest.approx(0.5, abs=1e-5)
    assert 0 < interpolate(keys, 0.5, 8) < 0.25
    assert interpolate(keys, -1, 8) == 0
    assert interpolate(keys, 3, 8) == 1
    with pytest.raises(ValidationError):
        Project(duration=601)
    with pytest.raises(ValidationError):
        Segment(keyframes={"opacity": [Keyframe(time=0, value=2)]})
    with pytest.raises(ValidationError):
        Segment(crop=(1, 0, 0, 1))


def test_atomic_recovery_and_portable_placeholders(studio, tmp_path):
    picture = tmp_path / "poster.png"
    Image.new("RGB", (64, 64), "red").save(picture)
    asset = studio.add_asset(picture)
    project = Project(
        creator="Author", tracks=[Track(clips=[Segment(kind="image", asset=asset["id"])])]
    )
    studio.save(project.model_dump())
    project.name = "Changed"
    studio.save(project.model_dump())
    studio.path("projects", project.id, ".json").write_text("broken")
    assert studio.state()["projects"] == [{"id": project.id, "name": "Untitled"}]
    recovered = studio.load(project.id)
    assert recovered.name == "Untitled"
    studio.save(recovered.model_dump())
    bundle = studio.bundle(project.id, [])
    imported = studio.import_bundle(bundle)
    assert imported["id"] != project.id and imported["creator"] == "Author"
    assert imported["source_project"] == project.id
    missing = imported["tracks"][0]["clips"][0]["asset"]
    assert missing != asset["id"] and not studio.path("assets", missing).exists()
    full = studio.import_bundle(studio.bundle(project.id, [asset["id"]]))
    new = full["tracks"][0]["clips"][0]["asset"]
    assert new != asset["id"] and studio.asset(new)["sha256"] == asset["sha256"]


def test_bundle_rejects_traversal_and_hash_mismatch(studio, tmp_path):
    path = tmp_path / "bad.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "project.json", json.dumps({"project": Project().model_dump(), "assets": []})
        )
        archive.writestr("../outside", "payload")
    with pytest.raises(ValueError, match="Unexpected"):
        studio.import_bundle(path)
    assert not (studio.root.parent / "outside").exists()


def test_layering_motion_and_opacity(studio):
    red = studio.root / "red.png"
    Image.new("RGB", (100, 100), "red").save(red)
    asset = studio.add_asset(red)
    clip = Segment(
        kind="image",
        asset=asset["id"],
        keyframes={"opacity": [Keyframe(time=0, value=0), Keyframe(time=2, value=1)]},
    )
    project = Project(background="#000000", tracks=[Track(clips=[clip])])
    assert frame(studio, project, 0, 640).getpixel((320, 180)) == (0, 0, 0)
    assert frame(studio, project, 2, 640).getpixel((320, 180)) == (255, 0, 0)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg required")
def test_real_host_render_has_h264_aac_and_cancel(studio):
    from torrentlinker.prerolls import probe

    project = Project(
        duration=0.2,
        width=1280,
        height=720,
        tracks=[Track(clips=[Segment(text="Hello", duration=0.2)])],
    )
    render(studio, project)
    assert studio.job["status"] == "complete", studio.job
    path = studio.root / "exports" / studio.job["file"]
    assert probe(path)["height"] == 720
    from torrentlinker.achievements import Ledger

    ledger = Ledger(studio.root.parent / "achievements.sqlite")
    assert [a["code"] for a in ledger.state("owner")["achievements"]] == ["studio-first"]
    ledger.close()
    studio.cancel.set()
    render(studio, project)
    assert studio.job["status"] == "cancelled"
    assert not list((studio.root / "exports").glob("*.wav"))


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg required")
def test_render_video_and_audio_tracks(studio, tmp_path):
    import subprocess

    import numpy as np

    fixture = tmp_path / "sample.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=red:s=160x90:r=25:d=0.4",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=0.4",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(fixture),
        ],
        check=True,
        capture_output=True,
    )
    asset = studio.add_asset(fixture)
    project = Project(
        duration=0.4,
        width=1280,
        height=720,
        tracks=[Track(clips=[Segment(kind="video", asset=asset["id"], duration=0.4)])],
    )
    render(studio, project)
    assert studio.job["status"] == "complete", studio.job
    exported = studio.root / "exports" / studio.job["file"]
    audio = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(exported), "-vn", "-f", "f32le", "pipe:1"],
        check=True,
        capture_output=True,
    ).stdout
    assert np.abs(np.frombuffer(audio, dtype="<f4")).max() > 0.01


def test_split_keeps_keyframe_timebase(studio):
    from torrentlinker.studio import value

    original = Segment(
        duration=4,
        keyframes={
            "x": [Keyframe(time=0, value=0, interpolation="bezier"), Keyframe(time=4, value=1)]
        },
    )
    right = original.model_copy(update={"duration": 2, "start": 2, "animation_offset": 2})
    for when in (0, 0.5, 1.5):
        assert value(right, "x", when) == value(original, "x", when + 2)


def test_native_preroll_skip_and_cleanup(qtbot, studio):
    from torrentlinker.gui.prerolls import PrerollPlayer

    dialog = PrerollPlayer(
        studio,
        {
            "steps": [
                {"kind": "pause", "seconds": 60, "title": "Pause"},
                {"kind": "pause", "seconds": 60, "title": "Second"},
            ]
        },
    )
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitUntil(lambda: dialog.index == 0)
    dialog.advance()
    assert dialog.index == 1 and dialog.timer.isActive()
    dialog.accept()
    assert not dialog.timer.isActive()


def test_native_studio_loads_and_saves(qtbot, tmp_path, request):
    from tests.test_community_interfaces import js, wait_js
    from tests.test_web_plan_execution import prepared
    from tests.webengine_support import isolated_webengine_render

    if isolated_webengine_render(request):
        return
    from torrentlinker.gui.media_browser import MediaBrowserPanel
    from torrentlinker.web.app import create_app

    config, setup, _, _ = prepared(tmp_path)
    app = create_app(
        config, password="test-password-long", service_override=setup, monitor_verifications=False
    )
    view = MediaBrowserPanel(
        lambda: app.state.agent_service, lambda: setup.settings.active_client_id
    )
    qtbot.addWidget(view)
    view.resize(1400, 1000)
    view.show()
    view.activate()
    wait_js(
        qtbot,
        view,
        # The panel reaches the app only once connected; opening Pré-rolls earlier has no API.
        "typeof prerollStudio==='function' && typeof communityBrowseDialog==='function'"
        " && typeof panelRequest==='function'",
    )
    js(qtbot, view, "void preOpen()")
    wait_js(qtbot, view, "!!document.querySelector('#preroll-body')")
    js(qtbot, view, "preUI.tab='studio'; preRender()")
    wait_js(
        qtbot,
        view,
        "Array.from(document.querySelectorAll('button')).some(b=>b.textContent==='New project')",
    )
    js(
        qtbot,
        view,
        "[...document.querySelectorAll('button')].find(b=>b.textContent==='New project').click()",
    )
    wait_js(qtbot, view, "document.querySelector('#studio-preview')?.naturalWidth===640")
    view.close()
