"""About / concepts page.

Explains the ideas a user needs to read the rest of the app: what a sound and
a recording are, how detection/segmentation works, what the data-quantity
rating means, and what models are. Pure read-only content; thresholds are
pulled from the same source the rest of the app uses so the numbers never drift.
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QScrollArea, QLabel, QFrame

from gui import theme
from config.config import (
    RATE, RECORD_SECONDS, SLIDING_WINDOW_AMOUNT, CURRENT_DETECTION_STRATEGY,
    THRESHOLD_DETECTION,
)

# Data-quantity thresholds, mirrored from lib/print_status.get_quantity_rating
# so the About copy and the live ratings always agree.
_SUFFICIENT_S = 16.5
_GOOD_S = 41.25
_EXCELLENT_S = 82.5


class AboutPage(QWidget):
    def __init__(self, app_state, parent=None):
        super().__init__(parent)
        self.app_state = app_state
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        layout.addWidget(scroll)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(32, 28, 32, 28)
        body_layout.setSpacing(6)

        label = QLabel(self._html())
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.RichText)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        label.setOpenExternalLinks(True)
        label.setMaximumWidth(820)
        body_layout.addWidget(label)
        body_layout.addStretch()

        scroll.setWidget(body)

    def refresh_theme(self):
        # Rebuild so colors track the theme.
        for child in self.findChildren(QLabel):
            child.setText(self._html())

    def _html(self):
        t = theme.colors()
        accent = t["accent"]
        bright = t["text_bright"]
        dim = t["text_dim"]
        text = t["text"]
        ms_per_frame = int(RECORD_SECONDS / SLIDING_WINDOW_AMOUNT * 1000)

        def h(txt):
            return (f"<h2 style='color:{bright}; margin-top:22px; "
                    f"margin-bottom:4px;'>{txt}</h2>")

        def rating_row(color, name, rng):
            return (f"<tr>"
                    f"<td style='padding:3px 14px 3px 0; color:{color}; "
                    f"font-weight:bold;'>{name}</td>"
                    f"<td style='padding:3px 0; color:{dim};'>{rng}</td></tr>")

        q = theme.QUANTITY_COLORS
        ratings = (
            rating_row(q["Not enough"], "Not enough",
                       f"under {_SUFFICIENT_S:g}s of detected sound"),
            rating_row(q["Sufficient"], "Sufficient",
                       f"{_SUFFICIENT_S:g}s - {_GOOD_S:g}s"),
            rating_row(q["Good"], "Good",
                       f"{_GOOD_S:g}s - {_EXCELLENT_S:g}s"),
            rating_row(q["Excellent"], "Excellent",
                       f"{_EXCELLENT_S:g}s and above"),
        )

        return f"""
        <div style='color:{text}; font-size:14px; line-height:150%;'>
        <h1 style='color:{bright}; margin-bottom:2px;'>Parrot.py</h1>
        <p style='color:{dim}; margin-top:0;'>
            Train a model to recognize the sounds you make - clicks, pops,
            vowels, hisses - and use them to control your computer. You record
            examples of each sound, Parrot segments out the actual sound from
            the silence, and then trains a classifier on those segments.
        </p>

        {h("Sounds &amp; recordings")}
        <p>A <b style='color:{accent};'>sound</b> is one label you want the model
        to recognize (for example <i>pop</i> or <i>ah</i>). Each sound holds one
        or more <b style='color:{accent};'>recordings</b> - individual capture
        sessions. The more varied, clean examples a sound has, the better the
        model learns it.</p>
        <p style='color:{dim};'>On disk, each recording is a source
        <code>.wav</code> plus a segments <code>.srt</code> that marks where the
        sound actually occurs.</p>

        {h("Detection &amp; the blue overlay")}
        <p>Most of a recording is silence between sounds. Parrot splits each
        recording into {ms_per_frame}&nbsp;ms frames and decides, frame by frame,
        whether each one is <i>signal</i> or <i>silence</i> by comparing its
        loudness (measured in <b>dBFS</b> - decibels relative to full scale,
        where 0 is the loudest possible and more negative is quieter) against a
        threshold.</p>
        <p>The <b style='color:#5ab0f5;'>blue bands</b> drawn over a waveform are
        the detected-sound regions - the frames that landed above the threshold.
        Everything outside them is treated as silence and ignored during
        training. You can re-run detection at a different threshold, or hand-edit
        a recording, from its edit view.</p>
        <p>The threshold itself is worked out in three layers:</p>
        <p style='margin-left:12px;'><b>1. Live calibration</b> - while you
        record, Parrot listens to your noise floor and the sounds you make and
        calibrates the threshold on the fly. It needs roughly ten finished
        sounds before it settles, so judgments made early in a take are
        provisional.</p>
        <p style='margin-left:12px;'><b>2. Settled re-judge</b> - when a
        recording is saved or re-detected, the whole take is judged again with
        the thresholds that settled over all of it, so the first sounds are
        segmented with exactly the same criteria as the last. (Two-pass
        detection - on by default, can be switched off in Settings.)</p>
        <p style='margin-left:12px;'><b>3. Manual override</b> - set a threshold
        yourself in a recording's edit view and it wins over both, for that
        recording only.</p>

        {h("Discrete vs continuous")}
        <p>A <b>discrete</b> sound is short and punchy (a click or a pop). A
        <b>continuous</b> sound is sustained (a held vowel or a hiss). Parrot
        estimates this <i>duration type</i> per recording because it changes how
        aggressively short detections are kept or rejected. You can override it
        when editing a recording.</p>

        {h("Data quantity")}
        <p>For each sound, Parrot adds up the <b>detected</b> sound time (the blue
        regions only - not the silence) and rates how much training data you have:
        </p>
        <table style='margin:6px 0 6px 4px;'>{''.join(ratings)}</table>
        <p style='color:{dim};'>These are guidelines, not hard limits. “Good” is
        usually enough to train a usable model; “Excellent” gives the classifier
        plenty of variety. A sound stuck at “Not enough” will tend to be the one
        the model confuses most, so it's the best place to add recordings.</p>

        {h("Sound quality (SNR)")}
        <p>Separate from <i>how much</i> data you have is <i>how clean</i> it is.
        Signal-to-noise ratio (SNR) compares the loudness of your sound to the
        background noise around it. A quiet room and a consistent mic distance
        give high SNR and crisper detection; a noisy room blurs the line between
        sound and silence.</p>

        {h("Models")}
        <p>A <b style='color:{accent};'>model</b> is what you train from your
        sounds. It can be made of several neural <b>nets</b> trained together -
        more nets can raise accuracy at the cost of training time and size.
        Models can also be <b>combined</b> (ensemble or hierarchical) to merge the
        strengths of several. You train and manage models from the
        <b>Models</b> tab.</p>

        {h("Talon patterns (patterns.json)")}
        <p>When a model is deployed to Talon, <code>patterns.json</code> maps
        model sounds to <b>patterns</b> - the named triggers your .talon files
        bind actions to. Each pattern has:</p>
        <p style='margin-left:12px;'><b>sounds</b> - which model sounds count
        toward this pattern (their probabilities are summed).</p>
        <p style='margin-left:12px;'><b>threshold</b> - rules that must
        <i>all</i> pass for a frame to fire: <code>&gt;probability</code>
        (summed model confidence, 0-1), <code>&gt;power</code> (loudness in
        Talon's units), <code>&gt;f0/f1/f2</code> (pitch/formants in Hz, e.g.
        to split a high hiss from a low one), each also available as
        <code>&lt;</code>. A fired frame keeps firing on every frame that
        passes - throttles are what stop a machine-gun trigger.</p>
        <p style='margin-left:12px;'><b>throttle</b> - after this pattern
        fires, silence the listed <i>patterns</i> (including itself) for N
        seconds. Targets must be pattern names, not sound names.</p>
        <p style='margin-left:12px;'><b>graceperiod / grace_threshold</b> -
        right after a detection, softer rules apply for N seconds so a sound
        you're holding doesn't stutter as its probability wobbles.</p>
        <p style='margin-left:12px;'><b>detect_after</b> - the rules must hold
        this many seconds before the first fire (turns a pop-like trigger into
        a hold-to-activate).</p>
        <p style='color:{dim};'>The Integrations tab edits all of this with
        validation, keeps snapshots of every deploy, and its Live/Captures
        views show the real power and probability values your sounds produce -
        the numbers thresholds should be judged against. Note that
        <code>power</code>/<code>f0</code> there are Talon-engine units, not
        the dBFS shown elsewhere in this app.</p>

        {h("Recording strategies")}
        <p>The detection strategy controls how onsets, rejections, and gap-mending
        are handled while segmenting. The current strategy is
        <code style='color:{dim};'>{CURRENT_DETECTION_STRATEGY}</code>, and the
        threshold mode is <b>{THRESHOLD_DETECTION}</b> - <i>strict</i> suits
        rapid back-to-back sounds, <i>lenient</i> leaves more room between sounds
        to settle on a threshold. You can pick a strategy when recording.</p>

        <p style='color:{dim}; margin-top:24px; font-size:12px;'>
            Audio is captured at {RATE} Hz and processed in {ms_per_frame} ms
            frames. Your recordings live under <code>data/recordings/</code> and
            models under <code>data/models/</code>.
        </p>
        </div>
        """
