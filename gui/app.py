from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from gui.windows.main_window import MainWindow


def create_app(argv):
    app = QApplication(argv)
    app.setApplicationName("Parrot.py")
    app.setStyle("Fusion")

    window = MainWindow()
    window.show()

    return app
