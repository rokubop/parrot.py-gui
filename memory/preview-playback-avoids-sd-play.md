---
name: preview-playback-avoids-sd-play
description: Previews must play through gui/services/playback.py, never sd.play() - its Python callback needs the GIL and crackles while the playhead repaints
type: project
---

All preview playback goes through `gui/services/playback.py`. **Never call
`sd.play()` in GUI code.**

`sd.play()` runs its callback *in Python*, so every audio buffer needs the GIL.
A preview repaints its playhead on a 16 ms timer and each repaint holds the main
thread ~4 ms (measured; more with many detection regions overlaid), which is
enough for the callback to miss deadlines. The result is playback that crackles
badly while the recorded WAV is bit-perfect - so it presents as a *recording*
bug and sends you looking in the wrong place. The files were verified
byte-identical to what was handed to the audio device.

The fix is PortAudio's blocking `write()` API, which buffers in C: a worker
thread feeds it, and a stalled main thread can no longer reach the device.

**Latency is not free here, and must be compensated, not buffered away.**
Auditioning a few frames before choosing a cut point is a core interaction.
Measured on macOS CoreAudio at 16 kHz:

| setting | output latency |
|---|---|
| `blocksize=1024, latency="high"` | 388 ms - plainly audible lag |
| `blocksize=0, latency="low"` | 133 ms - the floor |
| same, at 48 kHz | 110 ms - not worth resampling for |

Because ~133 ms cannot be removed, `play()` returns the stream's real latency
and every caller holds its playhead back by it (`_heard_position()` in
`session_card.py`, `recording_view.py`, `edit_view.py`). Without that the line
runs *ahead* of the sound and points past the blip being auditioned - worse than
lag, because it misleads about where to cut.

**How to apply:** Route any new playback through this service. Do not "fix"
future dropouts by enlarging the buffer, and do not expose buffer size as a
user setting - the DAW-style latency-vs-glitching tradeoff does not apply once
Python is out of the audio path, and there is nothing left to trade. Note the
*recording* buffer is not exposable either: `audio_worker.py`'s
`blocksize=round(RATE * RECORD_SECONDS / SLIDING_WINDOW_AMOUNT)` **is** the
15 ms detection frame, so changing it shifts SRT timing away from what existing
models were trained on.

Related: [[audio-rate-is-16khz]], [[qt-traps]]
