# app/ui/dialogs/speech_settings_tab.py
from PySide6.QtCore import Qt, Slot, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QComboBox,
    QPushButton, QTextEdit, QGroupBox, QFormLayout, QSpinBox, QDoubleSpinBox, QColorDialog, QProgressBar, QCheckBox
)
from PySide6.QtGui import QColor

from app.api.speech_api import GetVoiceListWorker, GenerateAudioWorker, MicLevelProbeWorker
from app.core.settings_manager import SettingsManager
from app.ui.widgets.AudioWaveWidget import AudioWaveWidget

class SpeechSettingsTabWidget(QWidget):
    """
    Encapsulated Speech (TTS + STT + visualizer) settings tab.
    Reads/writes QSettings via SettingsManager live (no apply button needed).
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.sm = SettingsManager(self)
        self._tts_worker = None
        self._voice_list_worker = None

        root = QVBoxLayout(self)
        root.setContentsMargins(8,8,8,8)
        root.setSpacing(10)

        # --- Endpoints ---
        ep_box = QGroupBox("Endpoints")
        ep_form = QFormLayout(ep_box)

        self.voice_server_url = QLineEdit(self.sm.value("speech/voice_server_url", "http://127.0.0.1:8008"))
        self.stt_server_url   = QLineEdit(self.sm.value("speech/stt_server_url", self.voice_server_url.text()))
        ep_form.addRow(QLabel("TTS Server:"), self.voice_server_url)
        ep_form.addRow(QLabel("STT Server:"), self.stt_server_url)
        root.addWidget(ep_box)

        # Persist on edit
        self.voice_server_url.editingFinished.connect(lambda: self._save("speech/voice_server_url", self.voice_server_url.text()))
        self.stt_server_url.editingFinished.connect(lambda: self._save("speech/stt_server_url",   self.stt_server_url.text()))

        # --- Voice selection + refresh ---
        voice_box = QGroupBox("Voice")
        h = QHBoxLayout(voice_box)
        self.voice_combo = QComboBox()
        self.voice_combo.setEditable(False)
        self.refresh_btn = QPushButton("⟳")
        self.refresh_btn.setFixedWidth(40)
        h.addWidget(QLabel("Voice:"))
        h.addWidget(self.voice_combo, 1)
        h.addWidget(self.refresh_btn)
        root.addWidget(voice_box)

        # load/restore voice
        self._desired_voice = self.sm.value("speech/voice", "")
        self.refresh_btn.clicked.connect(self._refresh_voice_list)
        self.voice_combo.currentTextChanged.connect(lambda v: self._save("speech/voice", v))

        # --- Visualizer preview + params ---
        vis_box = QGroupBox("Visualizer Preview & Style")
        vb = QVBoxLayout(vis_box)

        # Preview chip
        self.preview = AudioWaveWidget()
        self.preview.set_compact(22, show_buttons=True)
        vb.addWidget(self.preview)

        # Params
        pf = QFormLayout()
        self.bins_per_side = QSpinBox(); self.bins_per_side.setRange(4, 64)
        self.bins_per_side.setValue(int(self.sm.value("speech/bins_per_side", 16)))

        self.bin_gap = QSpinBox(); self.bin_gap.setRange(0, 12)
        self.bin_gap.setValue(int(self.sm.value("speech/bin_gap_px", 2)))

        self.smoothing = QDoubleSpinBox(); self.smoothing.setDecimals(2); self.smoothing.setRange(0.0, 0.99)
        self.smoothing.setValue(float(self.sm.value("speech/smoothing", 0.45)))

        self.fade_decay = QDoubleSpinBox(); self.fade_decay.setDecimals(2); self.fade_decay.setRange(0.5, 0.99)
        self.fade_decay.setValue(float(self.sm.value("speech/fade_decay", 0.88)))

        pf.addRow("Bins/side:", self.bins_per_side)
        pf.addRow("Gap (px):", self.bin_gap)
        pf.addRow("Smoothing:", self.smoothing)
        pf.addRow("Fade decay:", self.fade_decay)

        # Color pickers
        colors_row = QHBoxLayout()
        self.fg_btn = QPushButton("Set Foreground")
        self.bg_btn = QPushButton("Set Background")
        colors_row.addWidget(self.fg_btn)
        colors_row.addWidget(self.bg_btn)

        vb.addLayout(pf)
        vb.addLayout(colors_row)
        root.addWidget(vis_box)

        vad_box = QGroupBox("Speech-to-Text • Natural mode")
        vf = QFormLayout(vad_box)

        self.vad_auto = QCheckBox("Automatic sensitivity (recommended)")
        self.vad_auto.setChecked(bool(self.sm.value("speech/vad_auto", True)))

        self.vad_mult = QDoubleSpinBox()
        self.vad_mult.setRange(1.5, 10.0)
        self.vad_mult.setDecimals(2)
        self.vad_mult.setSingleStep(0.1)
        self.vad_mult.setValue(float(self.sm.value("speech/vad_multiplier", 3.5)))
        self.vad_mult.setToolTip("Trigger = max(min floor, noise floor × multiplier)")

        self.vad_min_floor = QDoubleSpinBox()
        self.vad_min_floor.setRange(0.001, 0.2)
        self.vad_min_floor.setDecimals(3)
        self.vad_min_floor.setSingleStep(0.001)
        self.vad_min_floor.setValue(float(self.sm.value("speech/vad_min_floor", 0.020)))
        self.vad_min_floor.setToolTip("Lower bound for the trigger threshold")

        self.vad_manual_thresh = QDoubleSpinBox();
        self.vad_manual_thresh.setRange(0.001, 0.5)
        self.vad_manual_thresh.setDecimals(3)
        self.vad_manual_thresh.setSingleStep(0.002)
        self.vad_manual_thresh.setValue(float(self.sm.value("speech/vad_rms_thresh", 0.030)))

        self.vad_silence_ms = QSpinBox()
        self.vad_silence_ms.setRange(150, 3000)
        self.vad_silence_ms.setSingleStep(50)
        self.vad_silence_ms.setSuffix(" ms")
        self.vad_silence_ms.setValue(int(self.sm.value("speech/vad_silence_ms", 500)))

        # Live meter row
        meter_row = QHBoxLayout()
        self.vad_meter = QProgressBar()
        self.vad_meter.setRange(0, 100)
        self.vad_meter.setTextVisible(False)
        self.vad_thresh_lbl = QLabel("threshold: —")
        self.vad_cal_btn = QPushButton("Calibrate (1s silence)")
        meter_row.addWidget(self.vad_meter, 1)
        meter_row.addWidget(self.vad_thresh_lbl)
        meter_row.addWidget(self.vad_cal_btn)

        vf.addRow(self.vad_auto)
        vf.addRow("Multiplier:", self.vad_mult)
        vf.addRow("Min floor:", self.vad_min_floor)
        vf.addRow("Manual level:", self.vad_manual_thresh)
        vf.addRow("Silence to stop:", self.vad_silence_ms)
        vf.addRow("Mic level:", meter_row)

        root.addWidget(vad_box)

        # enable/disable manual vs auto controls
        def _toggle_vad_mode(checked: bool):
            self.vad_mult.setEnabled(checked)
            self.vad_min_floor.setEnabled(checked)
            self.vad_cal_btn.setEnabled(checked)
            self.vad_manual_thresh.setEnabled(not checked)

        _toggle_vad_mode(self.vad_auto.isChecked())

        # persist + toggle
        self.vad_auto.toggled.connect(lambda v: (self._save("speech/vad_auto", bool(v)), _toggle_vad_mode(bool(v))))
        self.vad_mult.valueChanged.connect(lambda v: self._save("speech/vad_multiplier", float(v)))
        self.vad_min_floor.valueChanged.connect(lambda v: self._save("speech/vad_min_floor", float(v)))
        self.vad_manual_thresh.valueChanged.connect(lambda v: self._save("speech/vad_rms_thresh", float(v)))
        self.vad_silence_ms.valueChanged.connect(lambda v: self._save("speech/vad_silence_ms", int(v)))

        # --- Live meter via MicLevelProbeWorker ---
        self._probe = MicLevelProbeWorker(parent=self)
        self._probe.level.connect(self._on_probe_level)
        self._probe.error.connect(lambda e: print("[Probe] error:", e))
        self._probe.start()

        self.vad_cal_btn.clicked.connect(self._calibrate_noise_floor)
        # Save-on-change for VAD params
        self.vad_manual_thresh.valueChanged.connect(
            lambda v: (self._save("speech/vad_manual_thresh", float(v)))
        )
        self.vad_silence_ms.valueChanged.connect(
            lambda v: (self._save("speech/vad_silence_ms", int(v)))
        )

        # Colors from settings
        self._fg = QColor(self.sm.value("speech/vis_fg", "#8be9fd"))
        self._bg = QColor(self.sm.value("speech/vis_bg", "#1e1f29"))
        self.preview.set_colors(self._fg, self._bg)

        # Apply preview effect
        self._apply_preview_effect()



        # Save-on-change for params (and update preview)
        self.bins_per_side.valueChanged.connect(self._on_params_changed)
        self.bin_gap.valueChanged.connect(self._on_params_changed)
        self.smoothing.valueChanged.connect(self._on_params_changed)
        self.fade_decay.valueChanged.connect(self._on_params_changed)

        self.fg_btn.clicked.connect(lambda: self._pick_color("speech/vis_fg", True))
        self.bg_btn.clicked.connect(lambda: self._pick_color("speech/vis_bg", False))

        # --- Test text + Generate ---
        test_box = QGroupBox("Quick TTS Test")
        tb = QVBoxLayout(test_box)
        self.test_text = QTextEdit()
        self.test_text.setPlaceholderText("Type some text and press Generate…")
        self.gen_btn = QPushButton("Generate & Play")
        tb.addWidget(self.test_text)
        tb.addWidget(self.gen_btn)
        root.addWidget(test_box)

        self.gen_btn.clicked.connect(self._generate_test)

        # Fill voice list
        self._refresh_voice_list()

    # ---------- persistence ----------
    def _save(self, key, val):
        self.sm.setValue(key, val)
        self.sm.sync()

    def _on_params_changed(self, *_):
        self._save("speech/bins_per_side", self.bins_per_side.value())
        self._save("speech/bin_gap_px", self.bin_gap.value())
        self._save("speech/smoothing", self.smoothing.value())
        self._save("speech/fade_decay", self.fade_decay.value())
        self._apply_preview_effect()

    def _pick_color(self, key: str, is_fg: bool):
        start = self._fg if is_fg else self._bg
        c = QColorDialog.getColor(start, self, "Pick color")
        if not c.isValid(): return
        self._save("speech/vis_fg" if is_fg else "speech/vis_bg", c.name())
        if is_fg: self._fg = c
        else:     self._bg = c
        self.preview.set_colors(self._fg, self._bg)

    def _apply_preview_effect(self):
        self.preview.set_effect(
            "symmetric_bins",
            bins_per_side=self.bins_per_side.value(),
            bin_gap_px=self.bin_gap.value(),
            smoothing=self.smoothing.value(),
            fade_decay=self.fade_decay.value()
        )

    # ---------- voices ----------
    def _refresh_voice_list(self):
        url = self.voice_server_url.text().strip()
        if not url:
            return
        self.refresh_btn.setEnabled(False)
        self._voice_list_worker = GetVoiceListWorker(url)
        self._voice_list_worker.complete.connect(self._on_voices)
        self._voice_list_worker.start()

    @Slot(list, bool)
    def _on_voices(self, voice_list, ok):
        self.refresh_btn.setEnabled(True)
        if not ok:
            print(voice_list)  # error string
            return
        self.voice_combo.clear()
        self.voice_combo.addItems(voice_list)
        # restore desired voice if present
        want = self._desired_voice or self.sm.value("speech/voice", "")
        if want:
            ix = self.voice_combo.findText(want)
            if ix >= 0:
                self.voice_combo.setCurrentIndex(ix)
        # also persist the current
        if self.voice_combo.count():
            self._save("speech/voice", self.voice_combo.currentText())

    # ---------- test TTS ----------
    def _generate_test(self):
        txt = self.test_text.toPlainText().strip()
        if not txt: return
        url = self.voice_server_url.text().strip()
        voice = self.voice_combo.currentText().strip()
        self.gen_btn.setEnabled(False)
        self._tts_worker = GenerateAudioWorker(url, voice, txt)
        self._tts_worker.audio_ready.connect(self._on_audio_ready)
        self._tts_worker.complete.connect(self._on_test_done)
        self._tts_worker.start()

    @Slot(object)
    def _on_audio_ready(self, wav_bytes):
        # Same robust WAV handling you liked
        import io, wave, numpy as np
        with wave.open(io.BytesIO(wav_bytes), 'rb') as w:
            sr = w.getframerate(); ch = w.getnchannels(); sw = w.getsampwidth()
            raw = w.readframes(w.getnframes())
        if sw == 2:
            self.preview.set_wave(raw, sample_rate=sr, channels=ch)
        elif sw == 4:
            try:
                arr = np.frombuffer(raw, dtype="<f4")
                if ch > 1: arr = arr.reshape(-1, ch)
                arr = np.clip(arr, -1.0, 1.0).astype(np.float32, copy=False)
            except Exception:
                i32 = np.frombuffer(raw, dtype="<i4")
                if ch > 1: i32 = i32.reshape(-1, ch)
                arr = (i32.astype(np.float32) / 2147483647.0)
                arr = np.clip(arr, -1.0, 1.0)
            self.preview.set_wave(arr, sample_rate=sr, channels=ch)
        else:
            import numpy as np
            dtype = {1: np.int8, 2: np.int16, 3: np.int32, 4: np.int32}.get(sw, np.int16)
            i_arr = np.frombuffer(raw, dtype=dtype)
            if sw == 3: i_arr = (i_arr >> 8)
            if ch > 1: i_arr = i_arr.reshape(-1, ch)
            max_int = float(np.iinfo(np.int32 if sw >= 3 else dtype).max)
            arr = np.clip(i_arr.astype(np.float32) / max_int, -1.0, 1.0)
            self.preview.set_wave(arr, sample_rate=sr, channels=ch)
        self.preview.play()

    @Slot(str, bool)
    def _on_test_done(self, _msg, _ok):
        self.gen_btn.setEnabled(True)

    # ---------- external helper ----------
    def apply_to_audio_chip(self, chip: AudioWaveWidget):
        """Convenience: apply current visual params/colors to an external chip (e.g., Chat view)."""
        chip.set_colors(self._fg, self._bg)
        chip.set_effect(
            "symmetric_bins",
            bins_per_side=self.bins_per_side.value(),
            bin_gap_px=self.bin_gap.value(),
            smoothing=self.smoothing.value(),
            fade_decay=self.fade_decay.value()
        )

    @Slot(float)
    def _on_probe_level(self, rms: float):
        # Update meter 0..100 and show effective threshold
        self.vad_meter.setValue(int(max(0.0, min(1.0, rms)) * 100))
        if self.vad_auto.isChecked():
            # approximate threshold display based on current settings
            mult = self.vad_mult.value()
            floor = self.vad_min_floor.value()
            # Use a tiny EMA locally just to display something stable
            if not hasattr(self, "_disp_ema"): self._disp_ema = floor
            self._disp_ema = 0.95 * getattr(self, "_disp_ema", floor) + 0.05 * rms
            thr = max(floor, self._disp_ema * mult)
        else:
            thr = self.vad_manual_thresh.value()
        self.vad_thresh_lbl.setText(f"threshold: {thr:.3f}")

    def _calibrate_noise_floor(self):
        """
        Quick 1s silence capture: sample probe levels for 1s and
        set min_floor to the 20th percentile (robust to occasional bumps).
        """
        samples = []

        def grab(r):
            samples.append(r)

        self._probe.level.connect(grab)
        self.vad_cal_btn.setEnabled(False);
        self.vad_cal_btn.setText("Calibrating…")

        def end():
            try:
                self._probe.level.disconnect(grab)
            except Exception:
                pass
            if samples:
                # pick a conservative low percentile as noise floor
                samples_sorted = sorted(samples)
                p20 = samples_sorted[max(0, int(0.2 * len(samples_sorted)) - 1)]
                # store as new min floor if higher, so we don't set it too low
                new_floor = max(self.vad_min_floor.value(), round(p20, 3))
                self.vad_min_floor.setValue(new_floor)
            self.vad_cal_btn.setText("Calibrate (1s silence)")
            self.vad_cal_btn.setEnabled(True)

        # collect ~1s at ~30Hz
        QTimer.singleShot(1100, end)

    def closeEvent(self, e):
        try:
            if hasattr(self, "_probe") and self._probe:
                self._probe.stop_probe()
                self._probe.wait(500)
        except Exception:
            pass
        super().closeEvent(e)

