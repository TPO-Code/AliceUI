# app/ui/widgets/AudioWaveWidget.py
import sys
from typing import Optional, Union
import numpy as np

from PySide6.QtCore import Qt, QBuffer, QIODevice, QTimer, QSize, Signal
from PySide6.QtGui import QPainter, QBrush, QColor
from PySide6.QtWidgets import QWidget, QApplication, QHBoxLayout, QPushButton, QSizePolicy
from PySide6.QtMultimedia import QAudioFormat

try:
    from PySide6.QtMultimedia import QAudioSink, QMediaDevices
    AudioOutClass = QAudioSink
    USE_SINK = True
except ImportError:  # Qt < 6.4 alias
    from PySide6.QtMultimedia import QAudioOutput as QAudioSink
    from PySide6.QtMultimedia import QMediaDevices
    AudioOutClass = QAudioSink
    USE_SINK = False


# ---------------- Visualizer (single effect: symmetric bins) ----------------

class VisualizerCanvas(QWidget):
    """
    One simple effect:
      - symmetric_bins: N bins per side, lit count ~ VU level, with soft decay
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._sr: int = 0
        self._mono: Optional[np.ndarray] = None
        self._float_ch: Optional[np.ndarray] = None
        self._playhead_frame: int = 0

        # appearance / behavior
        self._fg = self.palette().text().color()
        self._bg = self.palette().base().color()
        self._bins_per_side: int = 16
        self._bin_gap_px: int = 2
        self._fade_decay: float = 0.88  # fade speed when not playing
        self._smoothing: float = 0.45   # follow speed while playing (0..1)

        # dynamic state
        self._last_vu: float = 0.0            # 0..1
        self._shown_lit_bins: float = 0.0     # smooth, can be fractional

    # ---- public API ----
    def set_colors(self, fg: Union[str, QColor], bg: Union[str, QColor]):
        if isinstance(fg, str): fg = QColor(fg)
        if isinstance(bg, str): bg = QColor(bg)
        self._fg = fg
        self._bg = bg
        self.update()

    def set_visual_mode(self, name: str = "symmetric_bins", **params):
        # keep params optional for future tweaks; only one mode now
        self._bins_per_side = int(params.get("bins_per_side", self._bins_per_side))
        self._bin_gap_px = int(params.get("bin_gap_px", self._bin_gap_px))
        self._fade_decay = float(params.get("fade_decay", self._fade_decay))
        self._smoothing = float(params.get("smoothing", self._smoothing))
        self.update()

    def clear_visual(self):
        self._last_vu = 0.0
        self._shown_lit_bins = 0.0
        self.update()

    def fade_step(self, factor: float):
        """Used during post-stop decay."""
        self._shown_lit_bins *= float(factor)
        if self._shown_lit_bins < 0.01:
            self._shown_lit_bins = 0.0
        self.update()

    def set_wave(self, mono: np.ndarray, sr: int, float_ch: Optional[np.ndarray] = None):
        self._mono = mono.astype(np.float32, copy=False) if mono is not None else None
        self._sr = int(sr)
        self._float_ch = float_ch.astype(np.float32, copy=False) if float_ch is not None else None
        self._playhead_frame = 0
        self.clear_visual()

    def set_playhead(self, frame_index: int, playing: bool):
        self._playhead_frame = max(0, int(frame_index))

        # compute VU (peak) over ~50ms window behind the playhead
        if self._sr <= 0 or (self._mono is None and self._float_ch is None):
            vu = 0.0
        else:
            arr = self._float_ch if self._float_ch is not None else self._mono[:, None]
            win = max(1, int(self._sr * 0.050))
            start = max(0, self._playhead_frame - win)
            end = min(arr.shape[0], self._playhead_frame)
            if end <= start:
                vu = 0.0
            else:
                seg = arr[start:end]
                vu = float(np.clip(np.max(np.abs(seg)), 0.0, 1.0))

        self._last_vu = vu

        # update smoothed lit bins
        max_bins = float(self._bins_per_side)
        target = vu * max_bins  # 0..bins_per_side
        if playing:
            alpha = float(np.clip(self._smoothing, 0.01, 0.99))
            self._shown_lit_bins = (1 - alpha) * self._shown_lit_bins + alpha * target
        else:
            self._shown_lit_bins *= self._fade_decay  # decay toward 0

        self.update()

    def minimumSizeHint(self) -> QSize: return QSize(300, 18)
    def sizeHint(self) -> QSize: return QSize(640, 22)

    # ---- paint ----
    def paintEvent(self, _):
        p = QPainter(self)
        rect = self.rect()
        W, H = rect.width(), rect.height()
        p.fillRect(rect, self._bg)

        shown = float(np.clip(self._shown_lit_bins, 0.0, float(self._bins_per_side)))
        bins = int(shown)
        if shown <= 0.01 or self._bins_per_side <= 0:
            return

        # Geometry
        center_x = W // 2
        available_left = max(1, center_x)
        available_right = max(1, W - center_x)
        gap = self._bin_gap_px
        # simple layout: bin width ~ equal on each side
        bw = max(1, min(available_left, available_right) // (self._bins_per_side + 1))

        bar_h = max(2, int(H * 0.8))
        top = (H - bar_h) // 2
        brush = QBrush(self._fg)
        p.setBrush(brush)
        p.setPen(Qt.NoPen)

        # draw full bins
        for i in range(1, bins + 1):
            # left
            lx = center_x - (i * (bw + gap))
            if lx + bw > 0:
                p.fillRect(lx, top, bw, bar_h, brush)
            # right
            rx = center_x + gap + ((i - 1) * (bw + gap))
            if rx < W:
                p.fillRect(rx, top, bw, bar_h, brush)

        # fractional soft bin
        frac = shown - bins
        if frac > 0.01 and bins < self._bins_per_side:
            color = QColor(self._fg)
            color.setAlpha(int(255 * np.clip(frac, 0.0, 1.0)))
            soft = QBrush(color)
            lx = center_x - ((bins + 1) * (bw + gap))
            rx = center_x + gap + (bins * (bw + gap))
            p.fillRect(lx, top, bw, bar_h, soft)
            p.fillRect(rx, top, bw, bar_h, soft)


# ---------------- AudioWaveWidget (compact chip) ----------------

class AudioWaveWidget(QWidget):
    """
    Compact one-row audio chip:
      set_wave(...), set_effect(...), set_colors(...), set_compact(...)
      play(), pause(), stop(hard=False)
    """
    regenerate_requested = Signal()
    playing_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._sample_rate: int = 0
        self._channels: int = 1
        self._pcm_bytes: Optional[bytes] = None
        self._mono_float: Optional[np.ndarray] = None
        self._float_ch: Optional[np.ndarray] = None
        self._audio: Optional[AudioOutClass] = None
        self._buffer: Optional[QBuffer] = None

        self._paused: bool = True
        self._playing: bool = False
        self._starting: bool = False

        self._timer = QTimer(self)
        self._timer.setInterval(33)  # ~30fps
        self._timer.timeout.connect(self._on_tick)

        # post-stop fade
        self._decay_ticks_remaining = 0
        self._post_decay_ms = 450
        self._fade_decay = 0.88  # mirror canvas default

        # visualizer
        self.canvas = VisualizerCanvas(self)
        self.canvas.set_visual_mode("symmetric_bins", bins_per_side=16, bin_gap_px=2, fade_decay=self._fade_decay)

        # layout: [▶] [canvas] [↻]
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        self.play_btn = QPushButton("▶")
        self.play_btn.setFixedWidth(26)
        self.play_btn.clicked.connect(self.toggle_play_pause)

        self.regen_btn = QPushButton("↻")
        self.regen_btn.setFixedWidth(26)
        self.regen_btn.setToolTip("Regenerate")
        self.regen_btn.clicked.connect(self.regenerate_requested.emit)

        row.addWidget(self.play_btn, 0)
        row.addWidget(self.canvas, 1)
        row.addWidget(self.regen_btn, 0)

        self.set_compact(20, show_buttons=True)

    # ---- appearance ----
    def set_compact(self, height_px: int = 20, show_buttons: bool = True):
        height_px = max(14, int(height_px))
        self.canvas.setMinimumHeight(height_px)
        self.canvas.setMaximumHeight(height_px)
        self.setMinimumHeight(height_px)
        self.setMaximumHeight(height_px)
        self.play_btn.setVisible(show_buttons)
        self.regen_btn.setVisible(show_buttons)

    def set_colors(self, fg: Union[str, QColor], bg: Union[str, QColor]):
        self.canvas.set_colors(fg, bg)

    def set_effect(self, name: str = "symmetric_bins", **params):
        self.canvas.set_visual_mode("symmetric_bins", **params)
        # keep our internal fade to match canvas (for decay)
        self._fade_decay = float(params.get("fade_decay", self._fade_decay))

    # ---- data ----
    def set_wave(self, data: Union[np.ndarray, bytes], sample_rate: int, channels: int = 1):
        # cancel any ongoing fade and clear visuals
        self._decay_ticks_remaining = 0
        self.canvas.clear_visual()
        self.stop(hard=False)

        self._sample_rate = int(sample_rate)
        self._channels = int(channels)

        if isinstance(data, bytes):
            int16 = np.frombuffer(data, dtype="<i2")
            frames = int16.reshape(-1, self._channels)
            self._float_ch = (frames.astype(np.float32) / 32767.0)
            self._mono_float = self._float_ch.mean(axis=1)
            self._pcm_bytes = frames.astype("<i2", copy=False).tobytes()
        else:
            arr = np.asarray(data)
            if arr.ndim == 1:
                f = np.clip(arr.astype(np.float32), -1, 1)
                pcm = (f * 32767.0).astype(np.int16)
                if self._channels > 1:
                    pcm = np.tile(pcm[:, None], (1, self._channels))
                self._float_ch = (pcm.astype(np.float32) / 32767.0)
                self._mono_float = self._float_ch.mean(axis=1) if self._channels > 1 else self._float_ch.reshape(-1)
                if self._channels == 1:
                    self._float_ch = self._float_ch.reshape(-1, 1)
                self._pcm_bytes = pcm.astype("<i2", copy=False).tobytes()
            elif arr.ndim == 2:
                assert arr.shape[1] == self._channels, "channels mismatch with array shape"
                if arr.dtype == np.int16:
                    pcm = arr
                    self._float_ch = pcm.astype(np.float32) / 32767.0
                    self._mono_float = self._float_ch.mean(axis=1)
                    self._pcm_bytes = pcm.astype("<i2", copy=False).tobytes()
                else:
                    f = np.clip(arr.astype(np.float32), -1, 1)
                    pcm = (f * 32767.0).astype(np.int16)
                    self._float_ch = f
                    self._mono_float = f.mean(axis=1)
                    self._pcm_bytes = pcm.astype("<i2").tobytes()
            else:
                raise ValueError("Array must be 1D or 2D(frames,channels)")

        self.canvas.set_wave(self._mono_float, self._sample_rate, self._float_ch)

    # ---- controls ----
    def toggle_play_pause(self):
        if self._audio is None or self._paused:
            self.play()
        else:
            self.pause()

    def play(self):
        if not self._pcm_bytes or self._sample_rate <= 0:
            return
        if self._starting:
            return

        self._starting = True
        self._paused = False
        self._playing = True
        self.play_btn.setText("❚❚")
        self.playing_changed.emit(True)

        if not self._timer.isActive():
            self._timer.start()

        # async start to avoid re-entrancy
        QTimer.singleShot(0, self._start_fresh)

    def pause(self):
        # stop audio but don't trigger fade; bins should drop to zero
        if self._audio:
            try:
                self._audio.stop()
            except Exception:
                pass
            self._audio = None
        if self._buffer:
            try:
                self._buffer.close()
            except Exception:
                pass
            self._buffer = None

        self._paused = True
        if self._playing:
            self._playing = False
            self.playing_changed.emit(False)

        self.play_btn.setText("▶")
        # keep timer for a moment to fade bins quickly
        self._decay_ticks_remaining = int(self._post_decay_ms / max(1, self._timer.interval()))
        if not self._timer.isActive():
            self._timer.start()

    def stop(self, hard: bool = False):
        """Stop playback. If hard=True, clear immediately; else run a short decay."""
        if self._audio:
            try:
                self._audio.stop()
            except Exception:
                pass
            self._audio = None
        if self._buffer:
            try:
                self._buffer.close()
            except Exception:
                pass
            self._buffer = None

        self._paused = True
        if self._playing:
            self._playing = False
            self.playing_changed.emit(False)

        self.play_btn.setText("▶")

        if hard:
            self.canvas.clear_visual()
            self._decay_ticks_remaining = 0
            self._timer.stop()
        else:
            self._decay_ticks_remaining = int(self._post_decay_ms / max(1, self._timer.interval()))
            if not self._timer.isActive():
                self._timer.start()

    def is_playing(self) -> bool:
        return bool(self._playing)

    # ---- internals ----
    def _start_fresh(self):
        try:
            fmt = QAudioFormat()
            fmt.setSampleRate(self._sample_rate)
            fmt.setChannelCount(self._channels)
            fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)

            dev = QMediaDevices.defaultAudioOutput()
            self._audio = AudioOutClass(dev, fmt) if USE_SINK else AudioOutClass(fmt, dev)

            self._buffer = QBuffer(self)
            self._buffer.setData(self._pcm_bytes)
            self._buffer.open(QIODevice.ReadOnly)
            self._buffer.seek(0)

            self._audio.start(self._buffer)
            self._paused = False
            if not self._timer.isActive():
                self._timer.start()
            self.canvas.set_playhead(0, playing=True)
        finally:
            self._starting = False

    # ---- ticking ----
    def _on_tick(self):
        # Decay phase
        if self._audio is None and self._decay_ticks_remaining > 0:
            self.canvas.fade_step(self._fade_decay)
            self._decay_ticks_remaining -= 1
            if self._decay_ticks_remaining <= 0:
                self.canvas.clear_visual()
                self.play_btn.setText("▶")
                self._timer.stop()
            return

        # Idle?
        if self._audio is None or self._mono_float is None or self._paused:
            if self._decay_ticks_remaining <= 0:
                self._timer.stop()
            return

        # --- NEW: detect natural end via buffer ---
        if self._buffer is not None and self._buffer.atEnd() and not self._paused:
            # ensure last visual frame, then stop -> emits playing_changed(False)
            self.canvas.set_playhead(len(self._mono_float), playing=False)
            self.stop(hard=False)
            return

        # Normal progress
        try:
            usecs = self._audio.processedUSecs()
        except Exception:
            try:
                usecs = self._audio.elapsedUSecs()
            except Exception:
                usecs = 0

        frames = int((usecs / 1_000_000.0) * self._sample_rate)
        total = len(self._mono_float)

        if frames >= total:
            self.canvas.set_playhead(total, playing=False)
            self.stop(hard=False)
            return

        self.canvas.set_playhead(frames, playing=True)

    def closeEvent(self, e):
        # defensive: stop timers/audio for clean shutdown
        try:
            self.stop(hard=True)
        except Exception:
            pass
        try:
            self._timer.stop()
        except Exception:
            pass
        super().closeEvent(e)


if __name__ == "__main__":
    # simple demo
    app = QApplication(sys.argv)
    w = AudioWaveWidget()
    w.resize(600, 40)
    w.set_compact(22, show_buttons=True)
    w.set_colors("#50fa7b", "#21222C")

    sr = 48000
    t = np.linspace(0, 3.0, int(sr * 3.0), endpoint=False, dtype=np.float32)
    left = 0.6 * np.sin(2 * np.pi * 440.0 * t).astype(np.float32)
    right = 0.6 * np.sin(2 * np.pi * 659.255 * t).astype(np.float32)
    stereo = np.stack([left, right], axis=1)

    w.set_wave(stereo, sample_rate=sr, channels=2)
    w.set_effect("symmetric_bins", bins_per_side=16, bin_gap_px=2, fade_decay=0.88, smoothing=0.45)

    w.show()
    w.play()
    sys.exit(app.exec())
