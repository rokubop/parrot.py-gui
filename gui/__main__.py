import sys


def main():
    from importlib.util import find_spec
    # pyqtgraph draws the audio graphs on the Sounds tab
    if find_spec("PyQt6") is None or find_spec("pyqtgraph") is None:
        sys.exit("The GUI needs PyQt6 and pyqtgraph: "
                 "pip install -r requirements-gui.txt")

    from gui.app import create_app
    app = create_app(sys.argv)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
