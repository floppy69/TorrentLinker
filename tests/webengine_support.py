"""Isolated rendering checks for bundled Qt WebEngine views."""


def isolated_webengine_render(request):
    """Keep the 3D viewer's global OpenGL backend out of headless HTML checks."""
    import os
    import subprocess
    import sys

    if os.environ.get("QT_QPA_PLATFORM") != "offscreen" or os.getenv("TL_WEBENGINE_RENDER_CHILD"):
        return False
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", request.node.nodeid],
        env={
            **os.environ,
            "TL_WEBENGINE_RENDER_CHILD": "1",
            "QTWEBENGINE_CHROMIUM_FLAGS": "--disable-gpu",
            "QT_QUICK_BACKEND": "software",
        },
        capture_output=True,
        text=True,
        timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return True
