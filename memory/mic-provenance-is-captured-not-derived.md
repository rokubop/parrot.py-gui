---
name: mic-provenance-is-captured-not-derived
description: A take's mic name is written to a _mic.json sidecar at record time; never resolve mici_<n> to a device name after the fact
type: project
---

Recording filenames are `mici_<index>__<timestamp>`, where `mici` is the **mic
index** (added with multi-microphone recording, `980debe`). The index is
load-bearing, not decoration: simultaneous mics deliberately share one timestamp
so their files group as one take, so the index is the only thing keeping the
names distinct. The sound label is *not* in the filename because it is already
the directory (`library_ops.recording_label`).

**Never turn `mici_<n>` back into a device name.** Device indices shift when
hardware changes (`audio_devices.py` drops saved picks that no longer resolve),
so a lookup at display time would confidently name the wrong microphone. The
name is captured while the stream is being opened and written to
`segments/<base>_mic.json` (`audio_worker._write_mic_info`); read it with
`library_ops.read_mic_info`, which returns None for takes recorded before the
sidecar existed rather than guessing.

Sidecars need no wiring to survive: `recording_sibling_files` matches by base
prefix, so rename, move, delete and the append-segment cleanup all carry or
remove them automatically. Anything else stored per-recording should follow the
same `<base>_*` naming for the same reason.

Sample rate is stored but shown only when it is *not* 16 kHz - see
[[audio-rate-is-16khz]]. A field identical on every card teaches nothing and
implies the rate is variable.

**How to apply:** Do not add the label to recording filenames (redundant), do
not drop the mic index (collides on multi-mic takes), and do not resolve device
indices retroactively anywhere in the UI.
