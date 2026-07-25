#!/usr/bin/env python3
"""First-run environment bootstrap: create the venv and install dependencies.

This runs BEFORE the application's dependencies exist, so it must import
nothing outside the standard library — no PyQt6, no numpy. The progress UI is
tkinter, which ships with CPython (including the python-build-standalone builds
that run.sh/run.bat download).

Two faces, one code path:

    python bootstrap.py            GUI progress window, falls back to console
                                   if tkinter or a display is unavailable
    python bootstrap.py --console  plain text, for CI and headless machines

Owning this step here rather than in run.sh and run.bat keeps the venv/pip
logic in one place instead of three. The run scripts still handle acquiring
Python (they have to — this file needs an interpreter to run at all) and
launching the app afterwards.

Exit codes:  0 environment ready   1 failed   2 cancelled by the user
"""

from __future__ import annotations

import argparse
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
MARKER = VENV_DIR / ".deps_installed"

WINDOW_TITLE = "Parrot.py Setup"

# The venv is built from whichever interpreter is running this file, so running
# it with the wrong one silently produces a venv for that version. Keep in sync
# with PYTHON_VERSION in run.sh / run.bat.
REQUIRED_PYTHON = (3, 13)


# ----------------------------------------------------------------------------
# Environment facts
# ----------------------------------------------------------------------------
def requirements_file() -> Path:
    name = "requirements-windows.txt" if os.name == "nt" else "requirements-posix.txt"
    return ROOT / name


def venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def venv_exists() -> bool:
    return venv_python().is_file()


def deps_current() -> bool:
    """True if deps were installed and requirements hasn't changed since."""
    if not MARKER.is_file():
        return False
    return MARKER.stat().st_mtime >= requirements_file().stat().st_mtime


def work_needed() -> bool:
    return not venv_exists() or not deps_current()


# ----------------------------------------------------------------------------
# The actual work
# ----------------------------------------------------------------------------
class Cancelled(Exception):
    pass


class Bootstrapper:
    """Creates the venv and installs requirements, reporting progress.

    `emit` receives raw log lines. `phase` receives short human-readable
    status. `should_cancel` is polled between subprocess lines.
    """

    def __init__(self, emit, phase, should_cancel=None):
        self._emit = emit
        self._phase = phase
        self._should_cancel = should_cancel or (lambda: False)

    def log(self, line: str) -> None:
        self._emit(line.rstrip("\n"))

    def run(self) -> None:
        """Raises Cancelled, or RuntimeError with a human-readable message."""
        if not requirements_file().is_file():
            raise RuntimeError(f"Missing {requirements_file().name}")

        if not venv_exists():
            self._create_venv()
        else:
            self.log(f"Virtual environment already present at {VENV_DIR.name}")

        if not deps_current():
            self._install_deps()
        else:
            self.log("Dependencies already up to date")

        self._phase("Ready")

    def _create_venv(self) -> None:
        self._phase("Creating virtual environment")
        self.log(f"Creating virtual environment in {VENV_DIR}")
        # Marker is stale the moment the venv is rebuilt
        if MARKER.exists():
            MARKER.unlink()
        self._stream([sys.executable, "-m", "venv", str(VENV_DIR)],
                     "Could not create the virtual environment")
        if not venv_exists():
            raise RuntimeError(f"venv created but {venv_python()} is missing")

    def _install_deps(self) -> None:
        req = requirements_file()
        self._phase("Installing dependencies")
        self.log(f"Installing from {req.name} (this can take several minutes)")

        cmd = [
            str(venv_python()), "-m", "pip", "install",
            # PyQt6 from source needs qmake; insist on a wheel
            "--only-binary=PyQt6",
            "--progress-bar", "off",   # we surface progress ourselves
            "--disable-pip-version-check",
            "-r", str(req),
        ]
        self._stream(cmd, "Dependency installation failed", pip_phases=True)

        MARKER.parent.mkdir(parents=True, exist_ok=True)
        MARKER.write_text("ok\n", encoding="utf-8")

    def _stream(self, cmd: list[str], failure_msg: str, pip_phases: bool = False) -> None:
        """Run cmd, forwarding output line by line. Raises on non-zero exit."""
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            raise RuntimeError(f"{failure_msg}: {exc}") from exc

        assert proc.stdout is not None
        try:
            for line in proc.stdout:
                self.log(line)
                if pip_phases:
                    self._maybe_update_phase(line)
                if self._should_cancel():
                    proc.terminate()
                    raise Cancelled()
        finally:
            proc.stdout.close()
            code = proc.wait()

        if code != 0:
            raise RuntimeError(f"{failure_msg} (exit code {code})")

    def _maybe_update_phase(self, line: str) -> None:
        """Turn pip's chatter into something worth showing a human.

        pip's lines carry the whole requirements path — "Collecting requests
        (from -r /Users/.../requirements-posix.txt (line 1))" — so they can't
        be shown raw.
        """
        s = line.strip()
        if s.startswith("Collecting "):
            self._phase(f"Resolving {_pkg_name(s[11:])}")
        elif s.startswith("Downloading "):
            self._phase(f"Downloading {_artifact(s[12:])}")
        elif s.startswith("Building wheel for "):
            self._phase(f"Building {_pkg_name(s[19:])}")
        elif s.startswith("Installing collected packages"):
            self._phase("Installing packages")


def _pkg_name(text: str) -> str:
    """'requests<4,>=2.5 (from ...)' -> 'requests'"""
    token = text.split(" ", 1)[0]
    for sep in ("<", ">", "=", "!", "~", "[", ";"):
        token = token.split(sep, 1)[0]
    return token.strip() or "package"


def _artifact(text: str) -> str:
    """'https://.../torch-2.13.0-cp313.whl (1.2 MB)' -> 'torch-2.13.0... (1.2 MB)'"""
    head = text.split(" ", 1)[0].rsplit("/", 1)[-1]
    if len(head) > 46:
        head = head[:43] + "..."
    size = ""
    tail = text.rstrip()
    if tail.endswith(")") and "(" in tail:
        size = " " + tail[tail.rfind("("):]
    return head + size


# ----------------------------------------------------------------------------
# Console face
# ----------------------------------------------------------------------------
def run_console(verbose: bool = True) -> int:
    def emit(line: str) -> None:
        if verbose and line:
            print(f"  {line}", flush=True)

    def phase(text: str) -> None:
        print(f"\n  == {text} ==", flush=True)

    try:
        Bootstrapper(emit, phase).run()
    except Cancelled:
        print("\n  Cancelled.", flush=True)
        return 2
    except RuntimeError as exc:
        print(f"\n  {exc}", flush=True)
        return 1
    return 0


# ----------------------------------------------------------------------------
# GUI face
# ----------------------------------------------------------------------------
def gui_available() -> bool:
    """Can we realistically open a window right now?"""
    if os.name == "posix" and sys.platform != "darwin":
        if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
            return False
    try:
        import tkinter  # noqa: F401
    except Exception:
        return False
    return True


def run_gui() -> int:
    import tkinter as tk
    from tkinter import ttk
    from tkinter.scrolledtext import ScrolledText

    messages: "queue.Queue[tuple[str, str]]" = queue.Queue()
    cancel_flag = threading.Event()
    result: dict[str, object] = {}

    root = tk.Tk()
    root.title(WINDOW_TITLE)
    root.minsize(620, 200)

    outer = ttk.Frame(root, padding=16)
    outer.pack(fill="both", expand=True)

    heading = ttk.Label(outer, text="Setting up Parrot.py",
                        font=("TkDefaultFont", 14, "bold"))
    heading.pack(anchor="w")

    subtitle = ttk.Label(
        outer,
        text="First run only. This downloads and installs the Python packages "
             "the app needs.",
        wraplength=580,
        foreground="#666666",
    )
    subtitle.pack(anchor="w", pady=(2, 12))

    phase_var = tk.StringVar(value="Starting")
    ttk.Label(outer, textvariable=phase_var).pack(anchor="w")

    bar = ttk.Progressbar(outer, mode="indeterminate", length=580)
    bar.pack(fill="x", pady=(6, 10))
    bar.start(12)

    # Details pane, collapsed by default but expanded on first run so the user
    # can see it is doing something rather than staring at a bar.
    details_shown = tk.BooleanVar(value=True)
    toggle_row = ttk.Frame(outer)
    toggle_row.pack(fill="x")

    log_frame = ttk.Frame(outer)
    log = ScrolledText(log_frame, height=14, wrap="none", font=("TkFixedFont", 10))
    log.pack(fill="both", expand=True)
    log.configure(state="disabled")

    def sync_details() -> None:
        if details_shown.get():
            log_frame.pack(fill="both", expand=True, pady=(8, 0))
            toggle.configure(text="Hide details")
            root.minsize(620, 460)
        else:
            log_frame.pack_forget()
            toggle.configure(text="Show details")
            root.minsize(620, 200)

    def on_toggle() -> None:
        details_shown.set(not details_shown.get())
        sync_details()

    toggle = ttk.Button(toggle_row, text="Hide details", command=on_toggle, width=14)
    toggle.pack(side="left")

    button_row = ttk.Frame(outer)
    button_row.pack(fill="x", pady=(12, 0))

    def on_cancel() -> None:
        cancel_flag.set()
        phase_var.set("Cancelling...")
        cancel_btn.configure(state="disabled")

    cancel_btn = ttk.Button(button_row, text="Cancel", command=on_cancel)
    cancel_btn.pack(side="right")

    close_btn = ttk.Button(button_row, text="Close", command=root.destroy)

    sync_details()

    def append(line: str) -> None:
        log.configure(state="normal")
        log.insert("end", line + "\n")
        log.see("end")
        log.configure(state="disabled")

    def worker() -> None:
        def emit(line: str) -> None:
            if line:
                messages.put(("log", line))

        def phase(text: str) -> None:
            messages.put(("phase", text))

        try:
            Bootstrapper(emit, phase, cancel_flag.is_set).run()
            messages.put(("done", ""))
        except Cancelled:
            messages.put(("cancelled", ""))
        except RuntimeError as exc:
            messages.put(("error", str(exc)))
        except Exception as exc:  # unexpected — still needs to reach the user
            messages.put(("error", f"{type(exc).__name__}: {exc}"))

    def finish(code: int, phase_text: str, *, failed: bool) -> None:
        result["code"] = code
        bar.stop()
        bar.configure(mode="determinate", value=0 if failed else 100)
        phase_var.set(phase_text)
        cancel_btn.pack_forget()
        close_btn.pack(side="right")
        if failed:
            # A failure is the one case where the log is the whole point
            if not details_shown.get():
                details_shown.set(True)
                sync_details()
        else:
            root.after(600, root.destroy)

    def drain() -> None:
        try:
            while True:
                kind, payload = messages.get_nowait()
                if kind == "log":
                    append(payload)
                elif kind == "phase":
                    phase_var.set(payload)
                elif kind == "done":
                    finish(0, "Ready", failed=False)
                    return
                elif kind == "cancelled":
                    append("Cancelled by user.")
                    finish(2, "Cancelled", failed=True)
                    return
                elif kind == "error":
                    append("")
                    append(f"ERROR: {payload}")
                    finish(1, "Setup failed", failed=True)
                    return
        except queue.Empty:
            pass
        root.after(60, drain)

    def on_window_close() -> None:
        if "code" in result:
            root.destroy()
        else:
            on_cancel()

    root.protocol("WM_DELETE_WINDOW", on_window_close)

    threading.Thread(target=worker, daemon=True).start()
    root.after(60, drain)
    root.mainloop()

    return int(result.get("code", 2))


# ----------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--console", action="store_true",
                        help="never open a window; print progress as text")
    parser.add_argument("--check", action="store_true",
                        help="exit 0 if the environment is already ready, else 3")
    parser.add_argument("--any-python", action="store_true",
                        help=f"skip the Python {'.'.join(map(str, REQUIRED_PYTHON))} check")
    args = parser.parse_args(argv)

    running = sys.version_info[:2]
    if running != REQUIRED_PYTHON and not args.any_python:
        want = ".".join(map(str, REQUIRED_PYTHON))
        have = ".".join(map(str, running))
        print(
            f"  This needs Python {want}, but is running under {have}:\n"
            f"    {sys.executable}\n\n"
            f"  The virtual environment is built from the interpreter running this\n"
            f"  file, so continuing would create a Python {have} environment.\n\n"
            f"  Use ./run.sh (or run.bat), which acquires the right Python for you,\n"
            f"  or pass --any-python to override.",
            file=sys.stderr,
        )
        return 1

    if args.check:
        return 0 if not work_needed() else 3

    if not work_needed():
        print("  Dependencies: up to date", flush=True)
        return 0

    if args.console or not gui_available():
        return run_console()
    return run_gui()


if __name__ == "__main__":
    sys.exit(main())
