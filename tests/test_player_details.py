"""The playing video's details under the picture, in the desktop Media tab."""

import os
import shutil
import subprocess
import sys
import threading

import pytest


def test_desktop_video_shows_its_details_under_the_picture(qtbot, tmp_path, request):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        pytest.skip("ffmpeg is required for a real playable video fixture")
    # WebEngine needs its own Qt application and profile, as in the other panel tests.
    if not os.getenv("TL_PLAYER_DETAILS_CHILD"):
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", request.node.nodeid],
            env={
                **os.environ,
                "TL_PLAYER_DETAILS_CHILD": "1",
                "XDG_CONFIG_HOME": str(tmp_path / "qt"),
            },
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return
    from PIL import Image

    from tests.test_community_interfaces import js, wait_js
    from tests.test_media_api import media_app
    from torrentlinker.gui.media import MediaTab

    app, root = media_app(tmp_path)
    subprocess.run(
        [
            ffmpeg,
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=160x120:r=10",
            "-t",
            "20",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(root / "Validation.Film.2026.MULTi.1080p.WEB.AAC.2.0.mp4"),
        ],
        check=True,
    )
    Image.new("RGB", (200, 300), "#cc5533").save(root / "poster.png")
    synopsis = "A full synopsis remains visible. " * 40 + "The final sentence is shown."
    (root / "movie.nfo").write_text(
        f"<movie><title>Validation Film</title><plot>{synopsis}</plot>"
        "<genre>Adventure</genre></movie>"
    )
    library = app.state.agent_service.media
    library.scan("default", threading.Event(), lambda _: None)
    item = library.listing("default", kind="video")["rows"][0]
    tab = MediaTab(lambda: app.state.assistant, lambda: "default", lambda: None)
    qtbot.addWidget(tab)
    tab.resize(1280, 900)
    tab.show()
    tab.activate()
    tab.command("play", media_ids=[item["id"]], index=0)
    details = tab.browser
    wait_js(
        qtbot,
        details,
        "document.querySelector('#media-feature h2')?.textContent==='Validation Film'",
    )
    wait_js(qtbot, details, "document.querySelector('#view-media').dataset.watch==='true'")
    assert js(qtbot, details, "document.querySelectorAll('.media-description-toggle').length") == 0
    flags = js(qtbot, details, "document.querySelector('#media-feature-details').innerText")
    assert "1080p" in flags and "AAC 2.0" in flags and "MULTI" in flags
    wait_js(
        qtbot,
        details,
        "document.querySelector('.media-feature-poster img')?.naturalWidth===200",
    )
    assert (
        js(qtbot, details, "document.querySelector('.media-feature-description').textContent")
        == synopsis
    )
    assert js(
        qtbot,
        details,
        "(() => { const p=document.querySelector('.media-feature-description'); "
        "return p.scrollHeight > p.clientHeight; })()",
    )
    assert js(qtbot, details, "document.querySelectorAll('.media-feature-tag').length") == 4
    assert js(
        qtbot,
        details,
        "document.querySelector('.media-feature-poster').getBoundingClientRect().width === 192",
    )
    assert js(
        qtbot,
        details,
        "(() => { const p=document.querySelector('.media-feature-poster').getBoundingClientRect(); "
        "const a=document.querySelector('.media-feature-actions').getBoundingClientRect(); "
        "return Math.abs(p.bottom - a.bottom) < 2; })()",
    )
    assert not tab.now_playing.isVisible()
    # The full-width theatre scrolls away; the library banner and menu stay at y=0.
    wait_js(qtbot, details, "document.querySelector('#media-screen').offsetHeight > 500")
    js(qtbot, details, "document.querySelector('.media-scroll').scrollTop = 800")
    wait_js(
        qtbot, details, "document.querySelector('#media-feature').getBoundingClientRect().top===0"
    )
    assert (
        js(qtbot, details, "document.querySelector('.media-topbar').getBoundingClientRect().top")
        == 0
    )
    if screenshot := os.getenv("TL_PLAYER_DETAILS_SCREENSHOT"):
        qtbot.wait(300)
        tab.grab().save(screenshot)
    source = tab.player.source()
    for layout in ("horizon", "cinematic"):
        tab.set_media_layout(layout)
        wait_js(
            qtbot, details, f"document.querySelector('#view-media').dataset.layout==='{layout}'"
        )
        assert tab.player.source() == source
        assert not tab.video_controls.isVisible()
    tab.stop()
