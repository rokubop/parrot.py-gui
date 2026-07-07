"""Offline replay of recorded Talon bridge sessions against a patterns.json.

A faithful port of the integration's detection state machine (NoisePattern /
PatternBuilder / Delegate.pattern_match from parrot_integration.py), driven by
recorded frames instead of the live engine. This makes threshold edits
evaluable against a real recorded session without re-performing the sounds:
record once, tweak, compare.

Fidelity notes:
- The recording contains exactly the frames that passed Talon's power gate.
  Replaying with a LOWER ``>power`` than was deployed may under-report — the
  gated-out silent frames simply don't exist in the recording. Surfaced to
  the caller via ``ReplayResult.power_floor_warning``.
- Talon resets duration/grace state when transitioning to silence (no forward
  pass). The recording shows that as a gap in frame timestamps; gaps longer
  than ``silence_gap`` trigger the same reset here.
- ``>ratio``/``<ratio`` divide by a class probability; recorded values are
  rounded and can be exactly 0. The original would never see that; we treat a
  zero-division as "rule not matched" instead of crashing.
"""
from dataclasses import dataclass, field

SILENCE_GAP_S = 0.15


class _Timestamps:
    __slots__ = ("last_detected_at", "duration_start", "graceperiod_until",
                 "throttled_at", "throttled_until")

    def __init__(self):
        self.last_detected_at = 0.0
        self.duration_start = 0.0
        self.graceperiod_until = 0.0
        self.throttled_at = 0.0
        self.throttled_until = 0.0


class _Frame:
    __slots__ = ("ts", "power", "f0", "f1", "f2", "classes")

    def __init__(self, raw):
        self.ts = raw.get("ts", 0.0)
        self.power = raw.get("power", 0.0)
        self.f0 = raw.get("f0", 0.0)
        self.f1 = raw.get("f1", 0.0)
        self.f2 = raw.get("f2", 0.0)
        self.classes = raw.get("classes", {})


def _matching_functions(thresholds, sounds):
    """Port of PatternBuilder.generate_matching_functions — same rule set,
    same semantics, in the same order."""
    calls = []
    if '>probability' in thresholds:
        calls.append(lambda f, t=thresholds['>probability'], s=sounds:
                     sum(f.classes[snd] for snd in s) >= t)
    if '>power' in thresholds:
        calls.append(lambda f, t=thresholds['>power']: f.power >= t)
    if '>ratio' in thresholds and len(sounds) > 1:
        calls.append(lambda f, t=thresholds['>ratio'], s=sounds:
                     f.classes[s[0]] / f.classes[s[1]] >= t)
    if '>f0' in thresholds:
        calls.append(lambda f, t=thresholds['>f0']: f.f0 >= t)
    if '>f1' in thresholds:
        calls.append(lambda f, t=thresholds['>f1']: f.f1 >= t)
    if '>f2' in thresholds:
        calls.append(lambda f, t=thresholds['>f2']: f.f2 >= t)
    if '<probability' in thresholds:
        calls.append(lambda f, t=thresholds['<probability'], s=sounds:
                     sum(f.classes[snd] for snd in s) < t)
    if '<power' in thresholds:
        calls.append(lambda f, t=thresholds['<power']: f.power < t)
    if '<ratio' in thresholds and len(sounds) > 1:
        calls.append(lambda f, t=thresholds['<ratio'], s=sounds:
                     f.classes[s[0]] / f.classes[s[1]] < t)
    if '<f0' in thresholds:
        calls.append(lambda f, t=thresholds['<f0']: f.f0 < t)
    if '<f1' in thresholds:
        calls.append(lambda f, t=thresholds['<f1']: f.f1 < t)
    if '<f2' in thresholds:
        calls.append(lambda f, t=thresholds['<f2']: f.f2 < t)
    return calls


class _Pattern:
    """Port of NoisePattern — identical field-for-field state transitions."""

    def __init__(self, name, config):
        self.name = name
        self.labels = frozenset(config.get("sounds") or [])
        self.detection_after = config.get("detect_after", 0)
        self.graceperiod_length = config.get("graceperiod", 0)
        self.throttles = config.get("throttle") or {}
        self.duration = 0
        self.timestamps = _Timestamps()
        self._calls = _matching_functions(config.get("threshold") or {},
                                          config.get("sounds") or [])
        if "grace_threshold" in config:
            self._grace_calls = _matching_functions(config["grace_threshold"],
                                                    config.get("sounds") or [])
        else:
            self._grace_calls = list(self._calls)

    def _detect_all(self, frame, calls):
        try:
            for call in calls:
                if call(frame) is False:
                    return False
        except ZeroDivisionError:
            return False
        return True

    def _match(self, frame, graceperiod_until):
        calls = self._grace_calls if frame.ts < graceperiod_until else self._calls
        return self._detect_all(frame, calls)

    def is_active(self, ts):
        return self.timestamps.throttled_until < ts

    def detect(self, frame):
        grace_detected = False
        detected = False
        if self.is_active(frame.ts):
            if self._match(frame, self.timestamps.graceperiod_until):
                self.timestamps.duration_start = (
                    self.timestamps.duration_start
                    if self.timestamps.duration_start > 0 else frame.ts)
                grace_detected = True
                if (self.timestamps.duration_start + self.detection_after) <= frame.ts:
                    detected = True
                    self.timestamps.last_detected_at = frame.ts
                    self.timestamps.graceperiod_until = \
                        frame.ts + self.graceperiod_length
                    self.duration = frame.ts - self.timestamps.duration_start

        if grace_detected is False:
            self.timestamps.graceperiod_until = 0
            self.duration = 0

        if self.timestamps.duration_start > 0 and detected is False \
                and grace_detected is False \
                and self.timestamps.graceperiod_until < (frame.ts + self.graceperiod_length):
            self.timestamps.duration_start = 0
            self.duration = 0

        return detected

    def reset_timestamps(self):
        self.timestamps.graceperiod_until = 0
        self.timestamps.duration_start = 0
        self.duration = 0

    def throttle(self, until, at):
        if until > self.timestamps.throttled_until:
            self.timestamps.throttled_at = at
            self.timestamps.throttled_until = until
            self.timestamps.graceperiod_until = 0


@dataclass
class ReplayResult:
    per_frame: list = field(default_factory=list)   # [{"ts", "active": [names]}]
    fires: dict = field(default_factory=dict)       # name -> detected-frame count
    skipped_patterns: list = field(default_factory=list)
    power_floor_warning: bool = False


def replay(raw_frames, patterns_json, silence_gap=SILENCE_GAP_S,
           deployed_patterns=None):
    """Run the recorded frames through ``patterns_json``. ``deployed_patterns``
    (the config that was live when the session was recorded) enables the
    lowered-power-floor warning."""
    classes = set()
    for raw in raw_frames[:20]:
        classes.update((raw.get("classes") or {}).keys())

    patterns = {}
    skipped = []
    for name, config in (patterns_json or {}).items():
        if not isinstance(config, dict) or not config.get("sounds"):
            skipped.append(name)
            continue
        if classes and frozenset(config["sounds"]) - classes:
            skipped.append(name)   # same as Delegate.apply_patterns
            continue
        patterns[name] = _Pattern(name, config)

    result = ReplayResult(skipped_patterns=skipped,
                          fires={name: 0 for name in patterns})

    if deployed_patterns:
        def floor(p):
            values = [c.get("threshold", {}).get(">power")
                      for c in p.values() if isinstance(c, dict)]
            values = [v for v in values if isinstance(v, (int, float))]
            return min(values) if values else None
        old_floor, new_floor = floor(deployed_patterns), floor(patterns_json)
        if old_floor is not None and new_floor is not None and new_floor < old_floor:
            result.power_floor_warning = True

    previous_ts = None
    for raw in raw_frames:
        frame = _Frame(raw)
        # Talon resets duration state on transitions to silence (frames stop
        # arriving); a timestamp gap in the recording is that transition.
        if previous_ts is not None and frame.ts - previous_ts > silence_gap:
            for pattern in patterns.values():
                pattern.reset_timestamps()
        previous_ts = frame.ts

        active = []
        for pattern in patterns.values():
            if pattern.detect(frame):
                active.append(pattern.name)
                result.fires[pattern.name] += 1
                for target, seconds in pattern.throttles.items():
                    other = patterns.get(target)
                    if other is not None:
                        other.throttle(frame.ts + seconds, frame.ts)
        result.per_frame.append({"ts": frame.ts, "active": active})

    return result


def compare(raw_frames, patterns_a, patterns_b, deployed_patterns=None):
    """Replay against two configs; returns (result_a, result_b, changes) where
    changes = [{"ts", "only_a": [...], "only_b": [...]}] for frames that differ."""
    result_a = replay(raw_frames, patterns_a, deployed_patterns=deployed_patterns)
    result_b = replay(raw_frames, patterns_b, deployed_patterns=deployed_patterns)
    changes = []
    for fa, fb in zip(result_a.per_frame, result_b.per_frame):
        only_a = [n for n in fa["active"] if n not in fb["active"]]
        only_b = [n for n in fb["active"] if n not in fa["active"]]
        if only_a or only_b:
            changes.append({"ts": fa["ts"], "only_a": only_a, "only_b": only_b})
    return result_a, result_b, changes
