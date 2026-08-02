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
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

_PROGRESS_RE = re.compile(r"^Progress (\d+) of (\d+)$")
_ARTIFACT_RE = re.compile(r"^(Downloading|Using cached) (\S+)(?: \(([^)]+)\))?")

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
MARKER = VENV_DIR / ".deps_installed"

WINDOW_TITLE = "Parrot.py Setup"
ICON_DIR = ROOT / "gui" / "assets"

# The venv is built from whichever interpreter is running this file, so running
# it with the wrong one silently produces a venv for that version. Keep in sync
# with PYTHON_VERSION in run.sh / run.bat.
REQUIRED_PYTHON = (3, 13)

# Setup as a checklist: the GUI draws a row per step, the console prints each
# one as it lands. Both faces are driven by the same Bootstrapper callback.
STEP_PYTHON = "python"
STEP_VENV = "venv"
STEP_DOWNLOAD = "download"
STEP_INSTALL = "install"


def step_labels() -> list[tuple[str, str]]:
    running = ".".join(map(str, sys.version_info[:2]))
    return [
        (STEP_PYTHON, f"Python {running}"),
        (STEP_VENV, "Virtual environment"),
        (STEP_DOWNLOAD, "Download packages"),
        (STEP_INSTALL, "Install packages"),
    ]


# ----------------------------------------------------------------------------
# Environment facts
# ----------------------------------------------------------------------------
def requirements_file() -> Path:
    name = "requirements-windows.txt" if os.name == "nt" else "requirements-posix.txt"
    return ROOT / name


def _norm(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def requirements_packages() -> list[str]:
    """The names as written in the requirements file, in order."""
    names = []
    try:
        text = requirements_file().read_text(encoding="utf-8")
    except OSError:
        return names
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        for sep in ("<", ">", "=", "!", "~", "[", ";", " "):
            line = line.split(sep, 1)[0]
        if line:
            names.append(line)
    return names


def _package_of(artifact: str) -> str:
    """'scikit_learn-1.5.0-cp313-win_amd64.whl' -> 'scikit-learn'"""
    stem = artifact.rsplit("/", 1)[-1]
    return _norm(stem.split("-", 1)[0])


def _mb(size: float) -> str:
    return f"{size / 1_048_576:.0f} MB" if size >= 1_048_576 else \
           f"{size / 1024:.0f} kB"


def venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def site_packages() -> Path | None:
    """pip writes a .dist-info here as each package finishes installing,
    which is the only per-package signal the install phase gives off."""
    candidates = [VENV_DIR / "Lib" / "site-packages"]
    candidates += sorted(VENV_DIR.glob("lib/python*/site-packages"))
    for path in candidates:
        if path.is_dir():
            return path
    return None


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
    status. `step` receives (key, "running" | "done") for the checklist.
    `should_cancel` is polled between subprocess lines.
    """

    def __init__(self, emit, phase, should_cancel=None, step=None, package=None):
        self._emit = emit
        self._phase = phase
        self._should_cancel = should_cancel or (lambda: False)
        self._step_report = step or (lambda key, state: None)
        self._step_states: dict[str, str] = {}
        self._package_report = package or (lambda name, state, detail: None)
        self._package_states: dict[str, tuple] = {}
        self._wanted = {_norm(n): n for n in requirements_packages()}
        self._downloading: str | None = None
        self._extras: set[str] = set()
        self._rate_mark = (0.0, 0)

    def log(self, line: str) -> None:
        self._emit(line.rstrip("\n"))

    def step(self, key: str, state: str) -> None:
        """Idempotent: pip's output and our own bookkeeping both close steps."""
        if self._step_states.get(key) == state:
            return
        self._step_states[key] = state
        self._step_report(key, state)

    def package(self, name: str, state: str, detail: str = "") -> None:
        known = self._package_states.get(name)
        if name and not detail and known:
            detail = known[1]  # keep the size once it is known
        if known == (state, detail):
            return
        self._package_states[name] = (state, detail)
        self._package_report(name, state, detail)

    def _extra(self, normalized: str) -> None:
        """A transitive dependency: counted, not listed."""
        if normalized not in self._extras:
            self._extras.add(normalized)
            self.package("", "extras", str(len(self._extras)))

    def _watch_installs(self, stop: threading.Event) -> None:
        """Tick packages off as pip lands them.

        pip says nothing between "Installing collected packages" and
        "Successfully installed", minutes of silence on 1.4 GB.
        """
        packages = site_packages()
        if packages is None:
            return
        seen: set[str] = set()
        installed_extras = 0
        while not stop.wait(0.5):
            try:
                entries = [e.name for e in os.scandir(packages)]
            except OSError:
                return
            for entry in entries:
                if not entry.endswith(".dist-info") or entry in seen:
                    continue
                seen.add(entry)
                name = _norm(entry[:-len(".dist-info")].rsplit("-", 1)[0])
                if name in self._wanted:
                    self.package(self._wanted[name], "done", "")
                elif name in self._extras:
                    installed_extras += 1
                    self.package("", "extras-detail",
                                 f"{installed_extras} of {len(self._extras)} installed")

    def run(self) -> None:
        """Raises Cancelled, or RuntimeError with a human-readable message."""
        # run.sh / run.bat and main() both settle this before we get here
        self.step(STEP_PYTHON, "done")

        if not requirements_file().is_file():
            raise RuntimeError(f"Missing {requirements_file().name}")

        if not venv_exists():
            self._create_venv()
        else:
            self.log(f"Virtual environment already present at {VENV_DIR.name}")
            self.step(STEP_VENV, "done")

        if not deps_current():
            self._install_deps()
        else:
            self.log("Dependencies already up to date")
            self.step(STEP_DOWNLOAD, "done")
            self.step(STEP_INSTALL, "done")

        self._phase("Ready")

    def _create_venv(self) -> None:
        self.step(STEP_VENV, "running")
        self._phase("Creating virtual environment")
        self.log(f"Creating virtual environment in {VENV_DIR}")
        # Marker is stale the moment the venv is rebuilt
        if MARKER.exists():
            MARKER.unlink()
        self._stream([sys.executable, "-m", "venv", str(VENV_DIR)],
                     "Could not create the virtual environment")
        if not venv_exists():
            raise RuntimeError(f"venv created but {venv_python()} is missing")
        self.step(STEP_VENV, "done")

    def _install_deps(self) -> None:
        req = requirements_file()
        self.step(STEP_DOWNLOAD, "running")
        self._phase("Installing dependencies")
        self.log(f"Installing from {req.name} (this can take several minutes)")

        cmd = [
            str(venv_python()), "-m", "pip", "install",
            # PyQt6 from source needs qmake; insist on a wheel
            "--only-binary=PyQt6",
            # raw is byte counts on their own lines, so no \r parsing
            "--progress-bar", "raw",
            "--disable-pip-version-check",
            "-r", str(req),
        ]
        stop_watching = threading.Event()
        watcher = threading.Thread(target=self._watch_installs,
                                   args=(stop_watching,), daemon=True)
        watcher.start()
        try:
            self._stream(cmd, "Dependency installation failed", pip_phases=True)
        finally:
            stop_watching.set()
            watcher.join(timeout=2)

        # A fully cached run never prints "Installing collected packages",
        # so close both steps here rather than trusting pip to say so.
        self.step(STEP_DOWNLOAD, "done")
        self.step(STEP_INSTALL, "done")
        if self._extras:
            self.package("", "extras-done", "")

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
                if not pip_phases or self._read_pip_line(line):
                    self.log(line)
                if self._should_cancel():
                    proc.terminate()
                    raise Cancelled()
        finally:
            proc.stdout.close()
            code = proc.wait()

        if code != 0:
            raise RuntimeError(f"{failure_msg} (exit code {code})")

    def _read_pip_line(self, line: str) -> bool:
        """Drive the phase and package displays. False means do not log it.

        pip's lines carry the whole requirements path — "Collecting requests
        (from -r /Users/.../requirements-posix.txt (line 1))" — so they can't
        be shown raw.
        """
        s = line.strip()

        match = _PROGRESS_RE.match(s)
        if match:
            self._on_bytes(int(match.group(1)), int(match.group(2)))
            return False

        match = _ARTIFACT_RE.match(s)
        if match:
            cached = match.group(1) == "Using cached"
            artifact, size = match.group(2), match.group(3)
            if artifact.endswith(".metadata"):
                return True  # the index lookup, not the package
            name = _package_of(artifact)
            if name in self._wanted:
                # running, not done: it is downloaded, not installed yet. The
                # watcher ticks it when pip actually lands it.
                self._downloading = None if cached else (self._wanted[name], False)
                self.package(self._wanted[name], "running",
                             size or ("cached" if cached else ""))
            else:
                self._downloading = None if cached else (name, True)
                self._extra(name)
                if not cached and size:
                    self.package("", "extras-detail", f"{name}  {size}")
            verb = "Reusing" if cached else "Downloading"
            self._phase(f"{verb} {_artifact(artifact + (f' ({size})' if size else ''))}")
            return True

        if s.startswith("Collecting "):
            name = _norm(_pkg_name(s[11:]))
            if name not in self._wanted:
                self._extra(name)
            self._phase(f"Resolving {_pkg_name(s[11:])}")
        elif s.startswith("Building wheel for "):
            self._phase(f"Building {_pkg_name(s[19:])}")
        elif s.startswith("Installing collected packages"):
            # one line naming all ~77 packages, every one of them already
            # logged on its own line when it was collected
            names = [n for n in s.split(":", 1)[1].split(",") if n.strip()]
            self._downloading = None
            self.step(STEP_DOWNLOAD, "done")
            self.step(STEP_INSTALL, "running")
            self._phase("Installing packages")
            self.log(f"Installing {len(names)} packages")
            return False
        elif s.startswith("Successfully installed "):
            tokens = s[23:].split()
            for token in tokens:
                name = _norm(token.rsplit("-", 1)[0])
                if name in self._wanted:
                    self.package(self._wanted[name], "done", "")
            self.log(f"Installed {len(tokens)} packages")
            return False
        return True

    def _on_bytes(self, done: int, total: int) -> None:
        if not self._downloading or not total:
            return
        name, is_extra = self._downloading
        now = time.monotonic()
        mark_time, mark_bytes = self._rate_mark
        if not mark_time or now - mark_time > 2:
            self._rate_mark = (now, done)
        rate = ""
        if mark_time and now > mark_time:
            speed = (done - mark_bytes) / (now - mark_time)
            if speed > 0:
                rate = f"   {speed / 1_048_576:.1f} MB/s"
        if done >= total:
            if is_extra:
                self.package("", "extras-detail", "")
            else:
                self.package(name, "running", _mb(total))
            self._downloading = None
            self._rate_mark = (0.0, 0)
            return
        progress = f"{_mb(done)} / {_mb(total)}{rate}"
        if is_extra:
            self.package("", "extras-detail", f"{name}  {progress}")
        else:
            self.package(name, "running", progress)


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
    labels = dict(step_labels())
    running_step: dict[str, str | None] = {"key": None}

    def emit(line: str) -> None:
        if verbose and line:
            print(f"  {line}", flush=True)

    def phase(text: str) -> None:
        print(f"\n  == {text} ==", flush=True)

    def step(key: str, state: str) -> None:
        if state == "running":
            running_step["key"] = key
            return
        running_step["key"] = None
        mark = "x" if state == "done" else "!"
        print(f"  [{mark}] {labels.get(key, key)}", flush=True)

    def package(name: str, state: str, detail: str) -> None:
        if state == "done" and name:
            print(f"      {name} {detail}".rstrip(), flush=True)

    def fail_running() -> None:
        if running_step["key"]:
            step(running_step["key"], "failed")

    try:
        Bootstrapper(emit, phase, step=step, package=package).run()
    except Cancelled:
        fail_running()
        print("\n  Cancelled.", flush=True)
        return 2
    except RuntimeError as exc:
        fail_running()
        print(f"\n  {exc}", flush=True)
        return 1
    return 0


# ----------------------------------------------------------------------------
# GUI face
# ----------------------------------------------------------------------------
STEP_GLYPH = {"pending": "·", "running": "▸",
              "done": "✓", "failed": "✗"}
STEP_COLOR = {"pending": "#999999", "running": "",
              "done": "#2e7d32", "failed": "#c62828"}


def _ellipsis(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit - 3] + "..."


def _claim_taskbar_identity() -> None:
    """Windows groups the taskbar by AppUserModelID. Without our own, setup
    shows up as python.exe. Same id as the app so they group together."""
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("parrot.py")
    except Exception:
        pass


def _set_window_icon(root, tk) -> None:
    """Without this the setup window wears Tk's default feather."""
    try:
        if os.name == "nt":
            root.iconbitmap(str(ICON_DIR / "parrot.ico"))
        else:
            # PhotoImage must outlive this call or Tk drops the icon
            root._parrot_icon = tk.PhotoImage(file=str(ICON_DIR / "parrot.png"))
            root.iconphoto(True, root._parrot_icon)
    except Exception:
        pass


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

    messages: "queue.Queue[tuple[str, object]]" = queue.Queue()
    cancel_flag = threading.Event()
    result: dict[str, object] = {}

    _claim_taskbar_identity()

    root = tk.Tk()
    root.title(WINDOW_TITLE)
    root.minsize(620, 260)
    _set_window_icon(root, tk)

    outer = ttk.Frame(root, padding=16)
    outer.pack(fill="both", expand=True)

    heading = ttk.Label(outer, text="Setting up Parrot.py",
                        font=("TkDefaultFont", 14, "bold"))
    heading.pack(anchor="w")

    heading.pack_configure(pady=(0, 14))

    body = ttk.Frame(outer)
    body.pack(fill="both", expand=True)
    body.columnconfigure(1, weight=1)
    body.rowconfigure(0, weight=1)

    left = ttk.Frame(body)
    left.grid(row=0, column=0, sticky="nw")

    steps_frame = ttk.Frame(left)
    steps_frame.pack(anchor="w")
    step_rows = {}
    for index, (key, label) in enumerate(step_labels()):
        glyph = ttk.Label(steps_frame, text=STEP_GLYPH["pending"], width=2,
                          foreground=STEP_COLOR["pending"])
        glyph.grid(row=index, column=0, sticky="w")
        name = ttk.Label(steps_frame, text=label,
                         foreground=STEP_COLOR["pending"])
        name.grid(row=index, column=1, sticky="w")
        step_rows[key] = (glyph, name, None)

    pkg_frame = ttk.Frame(left)
    pkg_frame.pack(anchor="w", fill="x", pady=(14, 0))
    pkg_frame.columnconfigure(2, weight=1)
    pkg_rows = {}
    for index, pkg in enumerate(requirements_packages()):
        glyph = ttk.Label(pkg_frame, text=STEP_GLYPH["pending"], width=2,
                          foreground=STEP_COLOR["pending"])
        glyph.grid(row=index, column=0, sticky="w")
        name = ttk.Label(pkg_frame, text=pkg, foreground=STEP_COLOR["pending"])
        name.grid(row=index, column=1, sticky="w")
        detail = ttk.Label(pkg_frame, text="", foreground="#666666")
        detail.grid(row=index, column=2, sticky="e", padx=(12, 0))
        pkg_rows[pkg] = (glyph, name, detail)
    extras_row = len(pkg_rows)
    extras_glyph = ttk.Label(pkg_frame, text="", width=2,
                             foreground=STEP_COLOR["pending"])
    extras_glyph.grid(row=extras_row, column=0, sticky="w", pady=(6, 0))
    extras_label = ttk.Label(pkg_frame, text="", foreground="#999999")
    extras_label.grid(row=extras_row, column=1, sticky="w", pady=(6, 0))
    extras_detail = ttk.Label(pkg_frame, text="", foreground="#999999")
    extras_detail.grid(row=extras_row, column=2, sticky="e",
                       padx=(12, 0), pady=(6, 0))

    def set_package(pkg, state, detail):
        if state == "extras":
            extras_glyph.configure(text=STEP_GLYPH["running"],
                                   foreground=STEP_COLOR["running"])
            extras_label.configure(text=f"+ {detail} dependencies")
            return
        if state == "extras-done":
            extras_glyph.configure(text=STEP_GLYPH["done"],
                                   foreground=STEP_COLOR["done"])
            extras_label.configure(foreground=STEP_COLOR["done"])
            extras_detail.configure(text="")
            return
        if state == "extras-detail":
            extras_detail.configure(text=detail)
            return
        row = pkg_rows.get(pkg)
        if row is None:
            return
        glyph, name, detail_label = row
        glyph.configure(text=STEP_GLYPH[state], foreground=STEP_COLOR[state])
        name.configure(foreground=STEP_COLOR[state])
        detail_label.configure(text=detail)

    running_step: dict[str, object] = {"key": None}

    def set_step(key: str, state: str) -> None:
        glyph, name, _ = step_rows[key]
        glyph.configure(text=STEP_GLYPH[state], foreground=STEP_COLOR[state])
        name.configure(foreground=STEP_COLOR[state])
        if state == "running":
            running_step["key"] = key
        elif running_step["key"] == key:
            running_step["key"] = None

    def set_detail(text: str) -> None:
        phase_var.set(_ellipsis(text, 70))

    phase_var = tk.StringVar(value="")
    ttk.Label(outer, textvariable=phase_var).pack(anchor="w", pady=(10, 0))

    bar = ttk.Progressbar(outer, mode="indeterminate", length=580)
    bar.pack(fill="x", pady=(6, 10))
    bar.start(12)

    # Details pane, collapsed by default but expanded on first run so the user
    # can see it is doing something rather than staring at a bar.
    details_shown = tk.BooleanVar(value=True)
    toggle_row = ttk.Frame(outer)
    toggle_row.pack(fill="x")

    log_frame = ttk.Frame(body)
    # word, not none: ScrolledText has no horizontal bar, so a long line
    # would simply be unreachable
    log = ScrolledText(log_frame, height=14, width=52, wrap="word",
                       font=("TkFixedFont", 9))
    log.pack(fill="both", expand=True)
    log.configure(state="disabled")

    def sync_details() -> None:
        if details_shown.get():
            log_frame.grid(row=0, column=1, sticky="nsew", padx=(28, 0))
            toggle.configure(text="Hide details")
            root.minsize(1000, 560)
        else:
            log_frame.grid_remove()
            toggle.configure(text="Show details")
            root.minsize(520, 560)

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

        def step(key: str, state: str) -> None:
            messages.put(("step", (key, state)))

        def package(name: str, state: str, detail: str) -> None:
            messages.put(("package", (name, state, detail)))

        try:
            Bootstrapper(emit, phase, cancel_flag.is_set, step=step,
                         package=package).run()
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
        if failed and running_step["key"]:
            set_step(running_step["key"], "failed")
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
                    set_detail(payload)
                elif kind == "step":
                    set_step(*payload)
                elif kind == "package":
                    set_package(*payload)
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
