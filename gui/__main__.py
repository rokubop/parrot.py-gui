import gc
import os
import sys
import time

ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


def _preload():
    """Everything slow, in the order Windows needs it.

    On Windows, torch's DLLs (c10.dll) fail to initialize if Qt's are loaded
    first (WinError 1114 - conflicting bundled runtimes). Everything that
    touches models (training, inspect, accuracy/live tests) imports torch
    lazily, so it MUST be resident before the first PyQt6 import. Costs ~1 s
    of startup on Windows only; no effect where the conflict doesn't exist.
    """
    if os.name == "nt":
        try:
            import torch  # noqa: F401
        except ImportError:
            pass
    import gui.app  # noqa: F401


def _claim_taskbar_identity():
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("parrot.py")
    except Exception:
        pass


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

        _claim_taskbar_identity()
        root = tk.Tk()
        root.title("Parrot.py")
        root.resizable(False, False)
        try:
            if os.name == "nt":
                root.iconbitmap(os.path.join(ASSETS, "parrot.ico"))
            else:
                root._icon = tk.PhotoImage(file=os.path.join(ASSETS, "parrot.png"))
                root.iconphoto(True, root._icon)
        except Exception:
            pass

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
    _load_with_splash()
    # destroy() leaves the Tcl interpreter in a cycle. Collect it here or a Qt
    # worker collects it later and Tcl aborts: Tcl_AsyncDelete, wrong thread.
    gc.collect()

    from gui.app import create_app
    app = create_app(sys.argv)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
