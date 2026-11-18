"""Give Windows a stable taskbar identity before Qt creates any windows."""

import sys

APP_ID = "Vietnoirien.TorrentLinker"


def set_app_id() -> None:
    if sys.platform != "win32":
        return
    import ctypes

    set_id = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID
    set_id.argtypes = [ctypes.c_wchar_p]
    set_id.restype = ctypes.c_long
    result = set_id(APP_ID)
    if result < 0:
        import logging

        logging.getLogger(__name__).warning("Windows taskbar identity could not be set: %s", result)
