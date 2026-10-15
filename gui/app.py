from PyQt6.QtWidgets import QApplication
import pyqtgraph as pg
from gui.windows.main_window import MainWindow
from gui import theme


def create_app(argv):
    app = QApplication(argv)
    app.setApplicationName("Parrot.py")
    app.setStyle("Fusion")

    pg.setConfigOptions(antialias=True)

    theme.apply(app, theme.current_name())

    # Playback writes to PortAudio on a background thread. Quitting without
    # waiting for it tears the interpreter down mid-write, which segfaults.
    from gui.services import playback
    app.aboutToQuit.connect(playback.shutdown)

    window = MainWindow()
    window.show()
    # Strong reference: `window` is only a local, and once create_app() returns
    # GC would delete the C++ widget (and every child) under the event loop.
    app._main_window = window

    return app
