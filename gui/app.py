from PyQt6.QtWidgets import QApplication
import pyqtgraph as pg
from gui.windows.main_window import MainWindow
from gui import theme


def create_app(argv):
    app = QApplication(argv)
    app.setApplicationName("Parrot.py")
    app.setStyle("Fusion")

    # Smoother, antialiased pyqtgraph curves
    pg.setConfigOptions(antialias=True)

    theme.apply(app, theme.current_name())

    window = MainWindow()
    window.show()
    # Keep a strong reference on the application object. Without this, `window`
    # is only a local here; once create_app() returns, Python's GC can collect
    # the MainWindow and delete the underlying C++ widget (and all its children:
    # pages, scroll areas, layouts) out from under the running event loop.
    app._main_window = window

    return app
