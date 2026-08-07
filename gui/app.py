import os
import sys
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon
import pyqtgraph as pg
from gui.windows.main_window import MainWindow
from gui import theme, indicator_style
from gui.widgets import wheel_guard

# macOS docks expect the rounded-tile version (a free-form mark renders
# oversized next to other apps). Windows takes the multi-size .ico so the
# taskbar, alt-tab and title bar each pick their own resolution.
if sys.platform == "darwin":
    _ICON_FILE = "parrot-tile.png"
elif sys.platform == "win32":
    _ICON_FILE = "parrot.ico"
else:
    _ICON_FILE = "parrot.png"
ICON_PATH = os.path.join(os.path.dirname(__file__), "assets", _ICON_FILE)


def _claim_taskbar_identity():
    """Windows taskbar groups by AppUserModelID; without our own we get
    python.exe's icon. Must run before the first window."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("parrot.py")
    except Exception:
        pass


def create_app(argv):
    _claim_taskbar_identity()
    app = QApplication(argv)
    app.setApplicationName("Parrot.py")
    app.setWindowIcon(QIcon(ICON_PATH))
    indicator_style.install(app)

    pg.setConfigOptions(antialias=True)

    theme.apply(app, theme.current_name())
    wheel_guard.install(app)

    window = MainWindow()
    window.show()
    # Strong reference: `window` is only a local, and once create_app() returns
    # GC would delete the C++ widget (and every child) under the event loop.
    app._main_window = window

    return app
