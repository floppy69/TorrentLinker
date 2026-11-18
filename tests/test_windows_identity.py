import sys

import pytest

from torrentlinker.gui.windows_identity import APP_ID, set_app_id


@pytest.mark.skipif(sys.platform != "win32", reason="Uses the Windows shell API")
def test_windows_process_has_explicit_taskbar_identity():
    import ctypes

    set_app_id()
    value = ctypes.c_wchar_p()
    get_id = ctypes.windll.shell32.GetCurrentProcessExplicitAppUserModelID
    get_id.argtypes = [ctypes.POINTER(ctypes.c_wchar_p)]
    get_id.restype = ctypes.c_long
    assert get_id(ctypes.byref(value)) == 0
    try:
        assert value.value == APP_ID
    finally:
        free = ctypes.windll.ole32.CoTaskMemFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = None
        free(ctypes.cast(value, ctypes.c_void_p))
