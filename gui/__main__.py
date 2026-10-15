import gc
import os
import sys
import time


def _preload():
    """Everything slow, in the order Windows needs it.

    On Windows, torch's DLLs fail to initialize if Qt's are loaded first
    (WinError 1114), and torch is imported lazily everywhere else, so it
    must be resident before the first PyQt6 import.
    """
    if os.name == "nt":
        try:
            import torch  # noqa: F401
        except ImportError:
            pass
    import gui.app  # noqa: F401


def _load_with_splash():
    """Cold start pages ~2 GB off disk, so the first launch is half a
    minute of nothing. tkinter because a Qt splash cannot appear until the
    import it covers has finished.

    Imports stay on the main thread: on a worker they segfault once Qt
    starts. The import hook pumps Tk instead.
    """
    try:
        import tkinter as tk
        from tkinter import ttk

        root = tk.Tk()
        root.title("Parrot.py")
        root.resizable(False, False)

        frame = ttk.Frame(root, padding=24)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Starting Parrot.py",
                  font=("TkDefaultFont", 13, "bold")).pack(anchor="w")
        ttk.Label(frame, wraplength=380, foreground="#666666",
                  text="Loading audio and model libraries.").pack(
                      anchor="w", pady=(4, 14))
        bar = ttk.Progressbar(frame, mode="indeterminate", length=380)
        bar.pack(fill="x")
        bar.start(12)

        root.update_idletasks()
        x = (root.winfo_screenwidth() - root.winfo_width()) // 2
        y = (root.winfo_screenheight() - root.winfo_height()) // 3
        root.geometry(f"+{x}+{y}")
    except Exception:
        _preload()
        return

    alive = {"ok": True}
    last_pump = [0.0]

    def pump():
        if not alive["ok"] or time.monotonic() - last_pump[0] < 0.05:
            return
        last_pump[0] = time.monotonic()
        try:
            root.update()
        except Exception:  # the user closed it; carry on loading
            alive["ok"] = False

    class _PumpOnImport:
        """Claims nothing, just gets called on every module lookup."""

        @staticmethod
        def find_spec(name, path=None, target=None):
            pump()
            return None

    sys.meta_path.insert(0, _PumpOnImport)
    try:
        _preload()
    finally:
        try:
            sys.meta_path.remove(_PumpOnImport)
        except ValueError:
            pass
        if alive["ok"]:
            try:
                root.destroy()
            except Exception:
                pass


def main():
    # find_spec, not import: importing either loads Qt, and on Windows that
    # has to wait until torch is in (see _preload).
    from importlib.util import find_spec
    if find_spec("PyQt6") is None or find_spec("pyqtgraph") is None:
        sys.exit("The GUI needs two more packages: "
                 "pip install -r requirements-gui.txt")
    _load_with_splash()
    # destroy() leaves the Tcl interpreter in a cycle. Collect it here or a Qt
    # worker collects it later and Tcl aborts: Tcl_AsyncDelete, wrong thread.
    gc.collect()

    from gui.app import create_app
    app = create_app(sys.argv)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
