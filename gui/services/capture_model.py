"""Frame/capture model for Talon bridge data — a faithful port of
talon-parrot-tester's Buffer / Capture / CaptureCollection semantics:

- a rolling pre-roll buffer so a capture includes the 0.3 s *before* the
  first detection;
- a capture groups frames while detections keep arriving, ends after 350 ms
  without one (here driven by frame timestamps, not wall-clock cron), and is
  capped at 50 frames;
- per-frame, per-pattern rows carry probability (sum of the pattern's sound
  probabilities), status (detected / throttled / "") and the grace flag,
  sorted detected-first then by probability.

Pure Python — shared by the Live view (streaming) and the Captures/A-B
workbench (recorded sessions).
"""

STATUS_ORDER = {"detected": 0, "grace_detected": 1, "throttled": 2, "": 3}
PROBABILITY_FLOOR = 0.1     # patterns below this aren't shown on a frame
PRE_ROLL_S = 0.3
CAPTURE_TIMEOUT_S = 0.35
MAX_FRAMES_PER_CAPTURE = 50


class ViewFrame:
    """One bridge frame enriched with per-pattern rows for display."""

    __slots__ = ("raw", "ts", "power", "f0", "f1", "f2", "patterns",
                 "detected", "id", "index", "ts_delta")

    def __init__(self, raw, patterns_json):
        self.raw = raw
        self.ts = raw.get("ts", 0.0)
        self.power = raw.get("power", 0.0)
        self.f0 = raw.get("f0", 0.0)
        self.f1 = raw.get("f1", 0.0)
        self.f2 = raw.get("f2", 0.0)
        self.id = None
        self.index = None
        self.ts_delta = None

        classes = raw.get("classes", {})
        active = set(raw.get("active", []))
        throttled = set(raw.get("throttled", []))
        grace = set(raw.get("grace", []))
        self.detected = bool(active)

        rows = []
        for name, pattern in (patterns_json or {}).items():
            sounds = pattern.get("sounds") or []
            probability = sum(classes.get(sound, 0.0) for sound in sounds)
            is_active = name in active
            if probability <= PROBABILITY_FLOOR and not is_active:
                continue
            status = ("detected" if is_active
                      else "throttled" if name in throttled
                      else "")
            rows.append({
                "name": name,
                "sounds": sounds,
                "probability": probability,
                "status": status,
                "graceperiod": name in grace,
            })
        rows.sort(key=lambda r: (STATUS_ORDER.get(r["status"], 99),
                                 -r["probability"]))
        self.patterns = rows

    @property
    def winner(self):
        return self.patterns[0] if self.patterns else None

    @property
    def winner_name(self):
        return self.patterns[0]["name"] if self.patterns else ""


class Capture:
    def __init__(self, pre_roll, detect_frame):
        self.frames = list(pre_roll) + [detect_frame]
        self.detect_frames = [detect_frame]
        self.completed = False
        self.id = f"{detect_frame.ts:.3f} {detect_frame.winner_name}"

    def add(self, frame):
        self.frames.append(frame)
        if frame.detected:
            self.detect_frames.append(frame)

    @property
    def last_detect_ts(self):
        return self.detect_frames[-1].ts

    @property
    def pattern_names(self):
        names = []
        for frame in self.detect_frames:
            for row in frame.patterns:
                if row["status"] == "detected" and row["name"] not in names:
                    names.append(row["name"])
        return names

    def complete(self):
        if self.completed:
            return
        first_detect_ts = self.detect_frames[0].ts
        for i, frame in enumerate(self.frames):
            frame.id = i + 1
            frame.index = i
            frame.ts_delta = frame.ts - first_detect_ts
        self.completed = True


class CaptureCollection:
    """Feed bridge frame dicts in timestamp order; captures come out."""

    def __init__(self, patterns_json, max_captures=100):
        self.patterns_json = patterns_json or {}
        self.max_captures = max_captures
        self.captures = []
        self.current = None
        self._pre_roll = []

    def set_patterns(self, patterns_json):
        self.patterns_json = patterns_json or {}

    def add_raw(self, raw):
        """Returns the capture that COMPLETED on this frame, if any."""
        frame = ViewFrame(raw, self.patterns_json)
        completed = None

        if self.current is not None and (
                len(self.current.frames) >= MAX_FRAMES_PER_CAPTURE
                or (not frame.detected
                    and frame.ts - self.current.last_detect_ts > CAPTURE_TIMEOUT_S)):
            completed = self.flush()

        if frame.detected:
            if self.current is None:
                pre = [f for f in self._pre_roll if frame.ts - f.ts < PRE_ROLL_S]
                self.current = Capture(pre, frame)
                self.captures.append(self.current)
                del self.captures[:-self.max_captures]
            else:
                self.current.add(frame)
        elif self.current is not None:
            self.current.add(frame)

        self._pre_roll.append(frame)
        del self._pre_roll[:-24]      # plenty for 0.3 s at Talon frame rates
        return completed

    def flush(self):
        """End the current capture (stream stopped / timeout)."""
        if self.current is None:
            return None
        capture = self.current
        capture.complete()
        self.current = None
        return capture
