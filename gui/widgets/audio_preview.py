import math
import wave
import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QTimer, QRectF, QVariantAnimation, QEasingCurve, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QVBoxLayout, QWidget, QScrollBar
from lib.srt import parse_srt_file
from config.config import RECORD_SECONDS, SLIDING_WINDOW_AMOUNT
from gui import theme

_MS_PER_FRAME = math.floor(RECORD_SECONDS / SLIDING_WINDOW_AMOUNT * 1000)


class AudioPreviewWidget(QWidget):
    """A single tall plot showing a recording as either a waveform or a
    spectrogram. Detection segments are overlaid as shaded regions, a playhead
    tracks playback, and the X axis is the time axis shared by both views.

    Zoom/pan is locked to the X axis with hard limits, and the waveform is
    re-rendered as a min/max envelope whenever the view range changes so detail
    sharpens on zoom instead of aliasing.
    """

    seeked = pyqtSignal(float)            # seconds - user clicked to seek
    pressed = pyqtSignal()                # user interacted; used for selection
    selection_changed = pyqtSignal(float, float)  # start, end (seconds)
    selection_cleared = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._samples = None      # mono float32, normalized to [-1, 1]
        self._sample_rate = None
        self._duration = 0.0
        self._peak = 0.0          # max abs sample, for visual normalization
        self._normalized = False
        self._mode = "waveform"
        self._spectrogram = None  # cached (image, levels)
        self._anim = None
        self._selection = None    # (start, end) seconds, or None
        self._sel_anchor = None   # drag origin while painting a selection

        t = theme.colors()
        self._colors = t

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.plot = pg.PlotWidget(background=t["plot_bg"])
        self.plot.setLabel("bottom", "Time", units="s")
        self.plot.setMenuEnabled(False)
        self.plot.hideButtons()
        self.plot.setMouseEnabled(x=True, y=False)
        self.plot.showGrid(x=True, y=False, alpha=t["grid_alpha"])
        layout.addWidget(self.plot)

        # Horizontal scrollbar: appears only when zoomed in so you can pan the
        # visible window along the clip without losing the zoom level.
        self._scroll_scale = 1000.0  # view seconds <-> scrollbar units (ms)
        self._updating_scroll = False
        # Keep the scrollbar inside a fixed-height row so showing/hiding it never
        # resizes (and shifts) the plot above.
        self._scroll_row = QWidget()
        self._scroll_row.setFixedHeight(14)
        scroll_layout = QVBoxLayout(self._scroll_row)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        self.hscroll = QScrollBar(Qt.Orientation.Horizontal)
        self.hscroll.setVisible(False)
        self.hscroll.valueChanged.connect(self._on_hscroll)
        scroll_layout.addWidget(self.hscroll)
        layout.addWidget(self._scroll_row)

        self._vb = self.plot.getViewBox()

        # Filled waveform (min/max envelope between two curves)
        pen = pg.mkPen(QColor(*t["wave"]), width=1)
        self._max_curve = self.plot.plot(pen=pen)
        self._min_curve = self.plot.plot(pen=pen)
        self._fill = pg.FillBetweenItem(self._max_curve, self._min_curve,
                                        brush=QColor(*t["wave_fill"]))
        self.plot.addItem(self._fill)

        # Spectrogram image (added lazily)
        self._image = pg.ImageItem()
        self._image.setVisible(False)
        self.plot.addItem(self._image)

        self._regions = []

        # Selection band: drag across the waveform to mark a time range. Fit
        # zooms to it and playback can be limited to it.
        accent = QColor(t["accent"])
        sel_brush = QColor(accent); sel_brush.setAlpha(55)
        self.selection_item = pg.LinearRegionItem(values=[0, 0], movable=False,
                                                  brush=sel_brush, pen=pg.mkPen(accent, width=1))
        self.selection_item.setZValue(5)
        self.selection_item.setVisible(False)
        # Let clicks pass through the band to the plot so a click dismisses it.
        self.selection_item.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        for _line in getattr(self.selection_item, "lines", []):
            _line.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.plot.addItem(self.selection_item)

        # Auto-scroll the view while dragging a selection past the visible edge.
        self._drag_scene_pos = None
        self._drag_timer = QTimer(self)
        self._drag_timer.setInterval(20)
        self._drag_timer.timeout.connect(self._drag_autoscroll)
        self.sel_label = pg.TextItem(color=accent, anchor=(0.5, 0))
        self.sel_label.setZValue(17)
        self.sel_label.setVisible(False)
        self.plot.addItem(self.sel_label)

        # Drag paints a selection instead of panning (panning is the scrollbar's
        # job); the wheel zooms time even over the left axis (no dead zone).
        self._vb.mouseDragEvent = self._on_vb_drag
        self.plot.getAxis("left").wheelEvent = self._vb.wheelEvent

        # Draggable playhead: grab it to scrub. A fatter invisible hover region
        # makes it easy to catch with the cursor.
        self.playhead = pg.InfiniteLine(pos=0, angle=90, movable=True,
                                        pen=pg.mkPen(QColor(*t["playhead"]), width=2))
        self.playhead.setHoverPen(pg.mkPen(QColor(*t["playhead"]), width=4))
        self.playhead.setZValue(20)
        self._dragging_playhead = False
        self.playhead.sigDragged.connect(self._on_playhead_dragged)
        self.playhead.sigPositionChangeFinished.connect(self._on_playhead_released)
        self.plot.addItem(self.playhead)

        # Hover crosshair + time readout
        cursor_pen = pg.mkPen(QColor(t["text_dim"]), width=1, style=Qt.PenStyle.DashLine)
        self.cursor = pg.InfiniteLine(pos=0, angle=90, movable=False, pen=cursor_pen)
        self.cursor.setZValue(15)
        self.cursor.setVisible(False)
        self.plot.addItem(self.cursor)
        self.readout = pg.TextItem(color=QColor(t["text_bright"]), anchor=(0, 1))
        self.readout.setZValue(16)
        self.readout.setVisible(False)
        self.plot.addItem(self.readout)
        self.plot.scene().sigMouseMoved.connect(self._on_mouse_moved)

        # Debounced re-render on zoom/pan
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(15)
        self._render_timer.timeout.connect(self._render_waveform)
        self._vb.sigXRangeChanged.connect(lambda *_: self._render_timer.start())
        self._vb.sigXRangeChanged.connect(lambda *_: self._sync_scrollbar())

        self.plot.scene().sigMouseClicked.connect(self._on_clicked)

    # ---- loading -------------------------------------------------------

    def load(self, wav_path, srt_path):
        self._spectrogram = None
        try:
            wf = wave.open(wav_path, "rb")
            channels = wf.getnchannels()
            self._sample_rate = wf.getframerate()
            n_frames = wf.getnframes()
            raw = wf.readframes(n_frames)
            wf.close()
            data = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
            if channels > 1:
                data = data.reshape(-1, channels).mean(axis=1)
            self._samples = data / 32768.0
            self._peak = float(np.abs(self._samples).max()) if len(self._samples) else 0.0
            # Derive duration from the samples we actually decoded, not from the
            # WAV header: some recordings store a byte count in the nframes field,
            # which would double the duration and leave Fit showing half-blank.
            self._duration = len(self._samples) / self._sample_rate if self._sample_rate else 0.0
        except Exception:
            self._samples = None
            self._duration = 0.0
            return

        self.plot.setLimits(xMin=0, xMax=self._duration)
        self._vb.setXRange(0, self._duration, padding=0)
        self.playhead.setBounds([0, self._duration])
        self._apply_y_range()
        self._load_regions(srt_path)
        self._render_waveform()

    def _load_regions(self, srt_path):
        for region in self._regions:
            self.plot.removeItem(region)
        self._regions = []
        if not srt_path:
            return
        try:
            events = parse_srt_file(srt_path, _MS_PER_FRAME, show_errors=False)
        except Exception:
            return
        for i, event in enumerate(events):
            if event.label == "silence":
                continue
            start = event.start_ms / 1000.0
            end = events[i + 1].start_ms / 1000.0 if i + 1 < len(events) else self._duration
            region = pg.LinearRegionItem(
                values=[start, end], movable=False,
                brush=QColor(*self._colors["detect_brush"]),
                pen=pg.mkPen(QColor(*self._colors["detect_pen"])),
            )
            region.setZValue(-10)
            self.plot.addItem(region)
            self._regions.append(region)

    # ---- view mode -----------------------------------------------------

    def set_mode(self, mode):
        if mode == self._mode:
            return
        self._mode = mode
        is_wave = mode == "waveform"
        self._max_curve.setVisible(is_wave)
        self._min_curve.setVisible(is_wave)
        self._fill.setVisible(is_wave)
        self._image.setVisible(not is_wave)
        if is_wave:
            self.plot.setLabel("left", "")
            self.plot.setMouseEnabled(x=True, y=False)
            self._apply_y_range()
            self._render_waveform()
        else:
            self._render_spectrogram()

    def set_normalized(self, normalized):
        self._normalized = normalized
        if self._mode == "waveform":
            self._apply_y_range()

    def _apply_y_range(self):
        if self._normalized and self._peak > 0:
            lim = max(self._peak, 0.02)
        else:
            lim = 1.0
        self.plot.setLimits(yMin=-lim * 1.08, yMax=lim * 1.08)
        self._vb.setYRange(-lim, lim, padding=0)

    def _render_spectrogram(self):
        if self._samples is None or self._sample_rate is None:
            return
        if self._spectrogram is None:
            self._spectrogram = self._compute_spectrogram()
        if self._spectrogram is None:
            return
        img, levels = self._spectrogram
        nyquist = self._sample_rate / 2.0
        self._image.setImage(img, autoLevels=False, levels=levels)
        self._image.setRect(QRectF(0, 0, self._duration, nyquist))
        self._image.setLookupTable(pg.colormap.get("inferno").getLookupTable(0.0, 1.0, 256))
        self.plot.setLabel("left", "Frequency", units="Hz")
        self.plot.setLimits(yMin=0, yMax=nyquist)
        self._vb.setYRange(0, nyquist, padding=0)

    def _compute_spectrogram(self, nfft=1024, hop=256):
        samples = self._samples
        if samples is None or len(samples) < nfft:
            return None
        frames = np.lib.stride_tricks.sliding_window_view(samples, nfft)[::hop]
        window = np.hanning(nfft).astype(np.float32)
        mag = np.abs(np.fft.rfft(frames * window, axis=1))
        db = 20.0 * np.log10(mag + 1e-6)  # shape (time, freq)
        top = float(db.max())
        return db, (top - 80.0, top)

    # ---- waveform envelope --------------------------------------------

    def _render_waveform(self):
        if self._mode != "waveform" or self._samples is None or self._sample_rate is None:
            return
        x0, x1 = self._vb.viewRange()[0]
        x0 = max(0.0, x0)
        x1 = min(self._duration, x1)
        if x1 <= x0:
            return

        sr = self._sample_rate
        i0 = int(x0 * sr)
        i1 = min(len(self._samples), int(x1 * sr))
        seg = self._samples[i0:i1]
        if len(seg) == 0:
            return

        width_px = max(self.plot.width(), 800)
        buckets = min(len(seg), width_px * 2)

        if len(seg) <= buckets:
            t = (i0 + np.arange(len(seg))) / sr
            self._max_curve.setData(t, seg)
            self._min_curve.setData(t, seg)
            return

        trim = len(seg) - (len(seg) % buckets)
        reshaped = seg[:trim].reshape(buckets, -1)
        env_max = reshaped.max(axis=1)
        env_min = reshaped.min(axis=1)
        step = (trim / buckets) / sr
        t = x0 + (np.arange(buckets) + 0.5) * step
        self._max_curve.setData(t, env_max)
        self._min_curve.setData(t, env_min)

    # ---- playback / interaction ---------------------------------------

    def set_playhead(self, seconds):
        # Don't fight the user while they're dragging the line.
        if self._dragging_playhead:
            return
        self.playhead.setPos(seconds)

    def _on_playhead_dragged(self):
        # Live drag: keep the readout visible at the playhead and mark us as the
        # selected card, but defer the actual seek until the drag finishes.
        self._dragging_playhead = True
        x = max(0.0, min(self.playhead.value(), self._duration))
        self.cursor.setVisible(False)
        self.readout.setText(f"{x:.3f}s")
        self.readout.setPos(x, self._vb.viewRange()[1][1])
        self.readout.setVisible(True)
        self.pressed.emit()

    def _on_playhead_released(self):
        if not self._dragging_playhead:
            return
        self._dragging_playhead = False
        self.readout.setVisible(False)
        x = max(0.0, min(self.playhead.value(), self._duration))
        self.seeked.emit(x)

    def fit(self):
        """Fit to the selection if there is one, else to the whole clip."""
        if self._duration <= 0:
            return
        if self._selection is not None:
            a, b = self._selection
            if b - a > 0:
                self._animate_x_range(a, b)
                if self._mode == "waveform":
                    self._apply_y_range()
                return
        self.fit_full()

    def fit_full(self):
        if self._duration <= 0:
            return
        self._animate_x_range(0.0, self._duration)
        if self._mode == "waveform":
            self._apply_y_range()

    def toggle_fit(self):
        """F: toggle between fitting the selection and fitting the whole clip.
        If a selection exists and we're not already zoomed to it, fit to it;
        otherwise fit the whole clip."""
        if self._duration <= 0:
            return
        sel = self._selection
        if sel is not None and sel[1] - sel[0] > 0:
            a, b = sel
            x0, x1 = self._vb.viewRange()[0]
            span = b - a
            already = abs(x0 - a) <= span * 0.15 and abs(x1 - b) <= span * 0.15
            if not already:
                self.fit()      # zoom to the selection
                return
        self.fit_full()

    # ---- selection -----------------------------------------------------

    def _min_selection(self):
        """A drag narrower than ~4 px is treated as a click, not a selection."""
        x0, x1 = self._vb.viewRange()[0]
        return (x1 - x0) / max(1, self.plot.width()) * 4

    def _set_selection(self, a, b):
        a = max(0.0, min(a, self._duration))
        b = max(0.0, min(b, self._duration))
        self._selection = (a, b)
        self.selection_item.setRegion((a, b))
        self.selection_item.setVisible(True)
        self.sel_label.setText(f"{b - a:.3f}s")
        self.sel_label.setPos((a + b) / 2.0, self._vb.viewRange()[1][1])
        self.sel_label.setVisible(True)

    def _clear_selection(self):
        if self._selection is None:
            return
        self._selection = None
        self.selection_item.setVisible(False)
        self.sel_label.setVisible(False)
        self.selection_cleared.emit()

    def _on_vb_drag(self, ev, axis=None):
        if ev.button() != Qt.MouseButton.LeftButton:
            pg.ViewBox.mouseDragEvent(self._vb, ev, axis=axis)
            return
        ev.accept()
        self._drag_scene_pos = ev.scenePos()
        x = max(0.0, min(self._vb.mapSceneToView(ev.scenePos()).x(), self._duration))
        if ev.isStart():
            self.pressed.emit()
            self._clear_selection()      # any new drag drops the previous range
            self._sel_anchor = x
            self._set_selection(x, x)
            self._drag_timer.start()
        elif ev.isFinish():
            self._drag_timer.stop()
            anchor = self._sel_anchor
            self._sel_anchor = None
            if anchor is None:
                return
            a, b = sorted((anchor, x))
            if (b - a) < self._min_selection():
                # Too small to be a range - treat it as a click/seek.
                self._clear_selection()
                self.seeked.emit(x)
            else:
                self._set_selection(a, b)
                self.selection_changed.emit(a, b)
        elif self._sel_anchor is not None:
            a, b = sorted((self._sel_anchor, x))
            self._set_selection(a, b)

    def _drag_autoscroll(self):
        """While dragging a selection, pan the view so it follows the cursor when
        it runs off either edge, extending the selection to keep up."""
        if self._sel_anchor is None or self._drag_scene_pos is None:
            return
        xv = self._vb.mapSceneToView(self._drag_scene_pos).x()
        x0, x1 = self._vb.viewRange()[0]
        step = (x1 - x0) * 0.07
        if xv > x1 and x1 < self._duration:
            shift = min(step, self._duration - x1)
            self._vb.setXRange(x0 + shift, x1 + shift, padding=0)
        elif xv < x0 and x0 > 0:
            shift = min(step, x0)
            self._vb.setXRange(x0 - shift, x1 - shift, padding=0)
        else:
            return
        # Re-read under the (now shifted) view and extend the selection.
        xc = max(0.0, min(self._vb.mapSceneToView(self._drag_scene_pos).x(), self._duration))
        a, b = sorted((self._sel_anchor, xc))
        self._set_selection(a, b)

    # ---- playback audio (shared with the owning card) ------------------

    def playback_audio(self):
        """Return (mono float32 samples, sample_rate) already decoded for the
        waveform, so the card needn't re-read the file to play it."""
        return self._samples, self._sample_rate

    def duration(self):
        return self._duration

    def current_selection(self):
        """The selected (start, end) range in seconds, or None."""
        return self._selection

    def select_all(self):
        """Select the whole clip (Ctrl/Cmd+A)."""
        if self._duration > 0:
            self._set_selection(0.0, self._duration)
            self.selection_changed.emit(0.0, self._duration)

    def clear_selection(self):
        """Drop any current selection (Esc)."""
        self._clear_selection()

    # ---- horizontal scrollbar -----------------------------------------

    def _sync_scrollbar(self):
        """Mirror the visible X window onto the scrollbar; hide it when the whole
        clip is in view."""
        if self._updating_scroll or self._duration <= 0:
            return
        x0, x1 = self._vb.viewRange()[0]
        span = x1 - x0
        if span >= self._duration - 1e-6:
            self.hscroll.setVisible(False)
            return
        s = self._scroll_scale
        self._updating_scroll = True
        self.hscroll.setMinimum(0)
        self.hscroll.setMaximum(max(0, int((self._duration - span) * s)))
        self.hscroll.setPageStep(max(1, int(span * s)))
        self.hscroll.setSingleStep(max(1, int(span * s / 20)))
        self.hscroll.setValue(int(max(0.0, x0) * s))
        self.hscroll.setVisible(True)
        self._updating_scroll = False

    def _on_hscroll(self, value):
        if self._updating_scroll:
            return
        x0, x1 = self._vb.viewRange()[0]
        span = x1 - x0
        new_x0 = value / self._scroll_scale
        self._updating_scroll = True
        self._vb.setXRange(new_x0, new_x0 + span, padding=0)
        self._updating_scroll = False

    def _animate_x_range(self, target_x0, target_x1):
        """Ease the visible X range to the target instead of snapping."""
        if self._anim is not None:
            self._anim.stop()
        start_x0, start_x1 = self._vb.viewRange()[0]
        anim = QVariantAnimation(self)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setDuration(240)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        def step(f):
            x0 = start_x0 + (target_x0 - start_x0) * f
            x1 = start_x1 + (target_x1 - start_x1) * f
            self._vb.setXRange(x0, x1, padding=0)

        anim.valueChanged.connect(step)
        anim.start()
        self._anim = anim

    def cleanup(self):
        """Tear down plot items before deletion so pyqtgraph doesn't paint
        an InfiniteLine whose ViewBox has already gone away."""
        self._render_timer.stop()
        self._drag_timer.stop()
        if self._anim is not None:
            self._anim.stop()
            self._anim = None
        for signal in (self._vb.sigXRangeChanged, self.plot.scene().sigMouseMoved,
                       self.plot.scene().sigMouseClicked):
            try:
                signal.disconnect()
            except (TypeError, RuntimeError):
                pass
        self.plot.clear()

    def _on_mouse_moved(self, scene_pos):
        if self._samples is None:
            return
        if not self._vb.sceneBoundingRect().contains(scene_pos):
            self.cursor.setVisible(False)
            self.readout.setVisible(False)
            return
        point = self._vb.mapSceneToView(scene_pos)
        x = max(0.0, min(point.x(), self._duration))
        self.cursor.setPos(x)
        y_top = self._vb.viewRange()[1][1]
        self.readout.setText(f"{x:.3f}s")
        self.readout.setPos(x, y_top)
        self.cursor.setVisible(True)
        self.readout.setVisible(True)

    def _on_clicked(self, event):
        self.pressed.emit()
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if event.double():
            self._clear_selection()
            self.fit_full()
            return
        self._clear_selection()
        x = self._vb.mapSceneToView(event.scenePos()).x()
        self.seeked.emit(max(0.0, min(x, self._duration)))
