import os
import sys

# On Windows, torch's DLLs (c10.dll) fail to initialize if Qt's are loaded
# first (WinError 1114 — conflicting bundled runtimes). Everything that
# touches models (training, inspect, accuracy/live tests) imports torch
# lazily, so it MUST be resident before the first PyQt6 import. Costs ~1 s
# of startup on Windows only; no effect where the conflict doesn't exist.
if os.name == "nt":
    try:
        import torch  # noqa: F401
    except ImportError:
        pass

from gui.app import create_app

def main():
    app = create_app(sys.argv)
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
