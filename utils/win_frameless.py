"""
חלון ללא מסגרת ל-Windows *ששומר על ההתנהגות המקורית* — הצמדה (Aero Snap),
שינוי-גודל מהקצוות, צל, ואנימציות מזעור/הגדלה. במקום להשתמש ב-
FramelessWindowHint של Qt (שמאבד את כל אלה), אנחנו מיירטים את הודעות ה-Win32:

  • WM_NCCALCSIZE  — מבטל את ציור מסגרת-הכותרת של המערכת, כך שאזור-הלקוח ממלא את
                     כל החלון והכותרת המעוצבת שלנו יושבת במקומה.
  • WM_NCHITTEST   — מגדיר רצועות שינוי-גודל בקצוות (Windows מציג סמן וגורר במקור).
  • DwmExtendFrameIntoClientArea — משאיר את צל-המערכת סביב החלון.

הכול מוגן ל-win32 בלבד; בפלטפורמות אחרות setup() לא עושה כלום.
"""
import sys
import ctypes
from ctypes import wintypes

IS_WIN = sys.platform == "win32"

if IS_WIN:
    user32 = ctypes.windll.user32
    dwmapi = ctypes.windll.dwmapi

    # Explicit signatures — on 64-bit, window/monitor HANDLEs are pointers, and
    # letting ctypes default them to C int truncates the pointer (→ hard crash).
    _WP = ctypes.c_void_p
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.GetWindowLongW.argtypes = [_WP, ctypes.c_int]
    user32.SetWindowLongW.restype = ctypes.c_long
    user32.SetWindowLongW.argtypes = [_WP, ctypes.c_int, ctypes.c_long]
    user32.SetWindowPos.restype = ctypes.c_bool
    user32.SetWindowPos.argtypes = [_WP, _WP, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_uint]
    user32.GetWindowRect.restype = ctypes.c_bool
    user32.GetWindowRect.argtypes = [_WP, ctypes.c_void_p]
    user32.MonitorFromWindow.restype = _WP
    user32.MonitorFromWindow.argtypes = [_WP, ctypes.c_uint]
    user32.GetMonitorInfoW.restype = ctypes.c_bool
    user32.GetMonitorInfoW.argtypes = [_WP, ctypes.c_void_p]
    user32.GetWindowPlacement.restype = ctypes.c_bool
    user32.GetWindowPlacement.argtypes = [_WP, ctypes.c_void_p]
    dwmapi.DwmExtendFrameIntoClientArea.restype = ctypes.c_long
    dwmapi.DwmExtendFrameIntoClientArea.argtypes = [_WP, ctypes.c_void_p]

    class RECT(ctypes.Structure):
        _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                    ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

    class NCCALCSIZE_PARAMS(ctypes.Structure):
        _fields_ = [("rgrc", RECT * 3), ("lppos", ctypes.c_void_p)]

    class MARGINS(ctypes.Structure):
        _fields_ = [("cxLeftWidth", ctypes.c_int), ("cxRightWidth", ctypes.c_int),
                    ("cyTopHeight", ctypes.c_int), ("cyBottomHeight", ctypes.c_int)]

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", RECT),
                    ("rcWork", RECT), ("dwFlags", wintypes.DWORD)]

    class WINDOWPLACEMENT(ctypes.Structure):
        _fields_ = [("length", wintypes.UINT), ("flags", wintypes.UINT),
                    ("showCmd", wintypes.UINT), ("ptMinPosition", wintypes.POINT),
                    ("ptMaxPosition", wintypes.POINT), ("rcNormalPosition", RECT)]

    WM_NCCALCSIZE = 0x0083
    WM_NCHITTEST = 0x0084
    GWL_STYLE = -16
    WS_MAXIMIZEBOX = 0x00010000
    WS_MINIMIZEBOX = 0x00020000
    WS_THICKFRAME = 0x00040000
    WS_CAPTION = 0x00C00000
    SWP_NOSIZE = 0x0001
    SWP_NOMOVE = 0x0002
    SWP_NOZORDER = 0x0004
    SWP_NOACTIVATE = 0x0010
    SWP_FRAMECHANGED = 0x0020
    MONITOR_DEFAULTTONEAREST = 2
    SW_SHOWMAXIMIZED = 3

    # hit-test result codes
    HTCLIENT = 1
    HTLEFT, HTRIGHT = 10, 11
    HTTOP, HTTOPLEFT, HTTOPRIGHT = 12, 13, 14
    HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT = 15, 16, 17

    def _is_maximized(hwnd) -> bool:
        wp = WINDOWPLACEMENT()
        wp.length = ctypes.sizeof(WINDOWPLACEMENT)
        user32.GetWindowPlacement(hwnd, ctypes.byref(wp))
        return wp.showCmd == SW_SHOWMAXIMIZED


def setup(window, border: int = 6):
    """Strip the native title bar (keeping frame styles for snap/resize/shadow)."""
    if not IS_WIN:
        return
    window._fl_border = border
    hwnd = int(window.winId())
    style = user32.GetWindowLongW(hwnd, GWL_STYLE)
    user32.SetWindowLongW(hwnd, GWL_STYLE,
                          style | WS_THICKFRAME | WS_CAPTION
                          | WS_MAXIMIZEBOX | WS_MINIMIZEBOX)
    # Keep the system drop-shadow around the frameless window.
    m = MARGINS(0, 0, 1, 0)
    dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(m))
    user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER
                        | SWP_FRAMECHANGED | SWP_NOACTIVATE)


def handle(window, message):
    """Process a native message. Returns (handled: bool, result: int)."""
    if not IS_WIN:
        return (False, 0)
    try:
        return _handle(window, message)
    except Exception:
        import traceback
        traceback.print_exc()
        return (False, 0)


def _handle(window, message):
    msg = wintypes.MSG.from_address(int(message))
    hwnd = msg.hWnd
    m = msg.message

    if m == WM_NCCALCSIZE:
        if msg.wParam:
            # When maximized, clamp the client rect to the monitor work area so the
            # window never overflows onto the taskbar / adjacent monitors.
            if _is_maximized(hwnd):
                p = ctypes.cast(msg.lParam,
                                ctypes.POINTER(NCCALCSIZE_PARAMS)).contents
                monitor = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
                info = MONITORINFO()
                info.cbSize = ctypes.sizeof(MONITORINFO)
                user32.GetMonitorInfoW(monitor, ctypes.byref(info))
                p.rgrc[0] = info.rcWork
        # Returning 0 → client area occupies the whole window (no system frame).
        return (True, 0)

    if m == WM_NCHITTEST:
        if _is_maximized(hwnd):
            return (False, 0)          # no edge-resize while maximized
        x = ctypes.c_short(msg.lParam & 0xffff).value
        y = ctypes.c_short((msg.lParam >> 16) & 0xffff).value
        rect = RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        bw = getattr(window, "_fl_border", 6)
        left, right = x < rect.left + bw, x >= rect.right - bw
        top, bottom = y < rect.top + bw, y >= rect.bottom - bw
        if top and left:
            return (True, HTTOPLEFT)
        if top and right:
            return (True, HTTOPRIGHT)
        if bottom and left:
            return (True, HTBOTTOMLEFT)
        if bottom and right:
            return (True, HTBOTTOMRIGHT)
        if left:
            return (True, HTLEFT)
        if right:
            return (True, HTRIGHT)
        if top:
            return (True, HTTOP)
        if bottom:
            return (True, HTBOTTOM)
        # Anywhere else → let Qt handle it (buttons + title-bar drag).
        return (False, 0)

    return (False, 0)
