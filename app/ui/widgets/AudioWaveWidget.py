# app/ui/widgets/AudioWaveWidget.py
import sys
from typing import Optional, Union, Dict
import numpy as np

from PySide6.QtCore import Qt, QBuffer, QIODevice, QTimer, QSize
from PySide6.QtGui import QPainter, QPen, QBrush
from PySide6.QtWidgets import QWidget, QApplication, QVBoxLayout, QPushButton, QHBoxLayout, QLabel, QSizePolicy
from PySide6.QtMultimedia import QAudioFormat
try:
    from PySide6.QtMultimedia import QAudioSink, QMediaDevices
    AudioOutClass = QAudioSink
    USE_SINK = True
except ImportError:
    from PySide6.QtMultimedia import QAudioOutput as QAudioSink
    from PySide6.QtMultimedia import QMediaDevices
    AudioOutClass = QAudioSink
    USE_SINK = False


class VisualizerCanvas(QWidget):
    """waveform / spectrum / vu modes"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._sr: int = 0
        self._mono: Optional[np.ndarray] = None
        self._float_ch: Optional[np.ndarray] = None
        self._playhead_frame: int = 0
        self._peaks: Optional[np.ndarray] = None
        self._last_bars: Optional[np.ndarray] = None
        self._last_vu: Optional[np.ndarray] = None
        self._mode: str = "waveform"
        self._params: Dict[str, float | int] = {
            "fft_size": 4096,
            "bar_count": 64,
            "min_db": -80.0,
            "max_db": 0.0,
            "vu_window_ms": 50,
        }
        self._bg = self.palette().base().color()
        self._fg = self.palette().text().color()

    def set_visual_mode(self, mode: str, **params):
        m = mode.lower()
        if m not in ("waveform", "spectrum", "vu"):
            raise ValueError("mode must be 'waveform', 'spectrum', or 'vu'")
        self._mode = m
        if params:
            self._params.update(params)
        self.update()

    def set_wave(self, mono: np.ndarray, sr: int, float_ch: Optional[np.ndarray] = None):
        self._mono = mono.astype(np.float32, copy=False)
        self._sr = int(sr)
        self._float_ch = float_ch.astype(np.float32, copy=False) if float_ch is not None else None
        self._playhead_frame = 0
        self._recompute_peaks()
        self.update()

    def set_playhead(self, frame_index: int):
        self._playhead_frame = max(0, frame_index)
        if self._mode == "spectrum":
            self._compute_spectrum_bars()
        elif self._mode == "vu":
            self._compute_vu_levels()
        self.update()

    def minimumSizeHint(self) -> QSize: return QSize(300, 120)
    def sizeHint(self) -> QSize: return QSize(640, 180)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._recompute_peaks()
        self._last_bars = None

    def paintEvent(self, _):
        p = QPainter(self)
        rect = self.rect()
        W, H = rect.width(), rect.height()
        mid_y = rect.center().y()
        p.fillRect(rect, self._bg)

        if self._mode == "waveform":
            p.setPen(QPen(self._fg, 1))
            p.drawLine(rect.left(), mid_y, rect.right(), mid_y)
            self._paint_waveform(p, W, H, mid_y)
            self._paint_playhead(p, W, H)
        elif self._mode == "spectrum":
            self._paint_spectrum(p, W, H)
        elif self._mode == "vu":
            self._paint_vu(p, W, H)

    # ---- painters ----
    def _paint_waveform(self, p: QPainter, W: int, H: int, mid_y: int):
        if self._peaks is None: return
        half = H / 2.0
        p.setPen(QPen(self._fg, 1))
        scale = half * 0.9
        peaks = self._peaks
        for x in range(min(W, peaks.shape[0])):
            mn, mx = peaks[x]
            y1 = int(mid_y - mx * scale)
            y2 = int(mid_y - mn * scale)
            p.drawLine(x, y1, x, y2)

    def _paint_playhead(self, p: QPainter, W: int, H: int):
        if self._mono is None or self._sr <= 0: return
        total_frames = len(self._mono)
        if total_frames <= 0: return
        frac = min(1.0, max(0.0, self._playhead_frame / total_frames))
        px = int(frac * (W - 1))
        p.setPen(QPen(Qt.red, 2))
        p.drawLine(px, 0, px, H)

    def _paint_spectrum(self, p: QPainter, W: int, H: int):
        p.setPen(QPen(self._fg, 1))
        p.drawLine(0, H - 1, W, H - 1)
        if self._last_bars is None or len(self._last_bars) == 0: return
        nb = len(self._last_bars)
        gap = max(1, W // (nb * 8))
        bar_w = max(1, (W - (nb + 1) * gap) // nb)
        x = gap
        brush = QBrush(self._fg)
        p.setBrush(brush)
        p.setPen(Qt.NoPen)
        for v in self._last_bars:
            h = int(v * (H - 2))
            p.fillRect(x, H - h, bar_w, h, brush)
            x += bar_w + gap

    def _paint_vu(self, p: QPainter, W: int, H: int):
        ch = 2 if (self._float_ch is not None and self._float_ch.shape[1] >= 2) else 1
        values = self._last_vu if self._last_vu is not None else np.zeros(ch, dtype=np.float32)
        margin = 8
        bar_h = (H - margin * (ch + 1)) // ch
        for i in range(ch):
            y = margin + i * (bar_h + margin)
            p.fillRect(margin, y, W - 2 * margin, bar_h, self._bg.darker(105))
            level_px = int(values[i] * (W - 2 * margin))
            p.fillRect(margin, y, level_px, bar_h, self._fg)
            clip_x = int(0.98 * (W - 2 * margin))
            p.setPen(QPen(Qt.red, 1, Qt.DashLine))
            p.drawLine(margin + clip_x, y, margin + clip_x, y + bar_h)

    # ---- computations ----
    def _recompute_peaks(self):
        if self._mono is None or self.width() <= 1:
            self._peaks = None; return
        mono = self._mono
        W = max(1, self.width())
        n = len(mono)
        spp = max(1, n // W)
        pad = (-n) % spp
        if pad: mono = np.pad(mono, (0, pad), mode="constant")
        cols = mono.reshape(-1, spp)
        if cols.shape[0] != W:
            idx = np.linspace(0, cols.shape[0] - 1, W).astype(int)
            cols = cols[idx]
        mins = cols.min(axis=1); maxs = cols.max(axis=1)
        self._peaks = np.stack([mins, maxs], axis=1)

    def _compute_spectrum_bars(self):
        if self._mono is None or self._sr <= 0:
            self._last_bars = None; return
        nfft = int(self._params.get("fft_size", 4096))
        nbars = int(self._params.get("bar_count", 64))
        min_db = float(self._params.get("min_db", -80.0))
        max_db = float(self._params.get("max_db", 0.0))

        half = nfft // 2
        start = max(0, self._playhead_frame - half)
        end = start + nfft
        if end > len(self._mono):
            segment = np.zeros(nfft, dtype=np.float32)
            avail = len(self._mono) - start
            if avail > 0: segment[:avail] = self._mono[start:start + avail]
        else:
            segment = self._mono[start:end]

        window = np.hanning(nfft).astype(np.float32)
        spec = np.fft.rfft(segment * window)
        mag = np.abs(spec) + 1e-12

        nyq = self._sr / 2.0
        f_edges = np.geomspace(20.0, max(40.0, nyq), nbars + 1)
        freqs = np.fft.rfftfreq(nfft, d=1.0 / self._sr)

        bars = np.zeros(nbars, dtype=np.float32)
        for i in range(nbars):
            f1, f2 = f_edges[i], f_edges[i + 1]
            idx = np.where((freqs >= f1) & (freqs < f2))[0]
            if idx.size == 0:
                bars[i] = 0.0
            else:
                db = 20.0 * np.log10(mag[idx].max())
                v = (db - min_db) / (max_db - min_db)
                bars[i] = float(np.clip(v, 0.0, 1.0))
        self._last_bars = bars

    def _compute_vu_levels(self):
        if self._float_ch is None or self._sr <= 0:
            if self._mono is None: self._last_vu = None; return
            ch_arr = self._mono[:, None]
        else:
            ch_arr = self._float_ch

        win_ms = int(self._params.get("vu_window_ms", 50))
        win = max(1, int(self._sr * (win_ms / 1000.0)))
        start = max(0, self._playhead_frame - win)
        end = min(len(ch_arr), self._playhead_frame)
        if end <= start:
            self._last_vu = np.zeros(ch_arr.shape[1], dtype=np.float32); return
        seg = ch_arr[start:end]
        peak = np.max(np.abs(seg), axis=0)
        self._last_vu = np.clip(peak, 0.0, 1.0)


class AudioWaveWidget(QWidget):
    """
    set_wave(data, sample_rate, channels=1, sample_width=2)
    set_effect(name: 'waveform'|'spectrum'|'vu', **params)
    play(), stop()
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._sample_rate: int = 0
        self._channels: int = 1
        self._sample_width: int = 2
        self._pcm_bytes: Optional[bytes] = None
        self._mono_float: Optional[np.ndarray] = None
        self._float_ch: Optional[np.ndarray] = None
        self._audio: Optional[AudioOutClass] = None
        self._buffer: Optional[QBuffer] = None

        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._on_tick)

        self.canvas = VisualizerCanvas(self)

        controls = QWidget(self)
        hb = QHBoxLayout(controls); hb.setContentsMargins(0, 0, 0, 0)
        self.play_btn = QPushButton("Play")
        self.stop_btn = QPushButton("Stop")
        self.info_lbl = QLabel("00:00 / 00:00")
        self.play_btn.clicked.connect(self.play)
        self.stop_btn.clicked.connect(self.stop)
        hb.addWidget(self.play_btn); hb.addWidget(self.stop_btn); hb.addStretch(); hb.addWidget(self.info_lbl)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)
        layout.addWidget(controls)

    def set_wave(self, data: Union[np.ndarray, bytes], sample_rate: int, channels: int = 1, sample_width: int = 2):
        self.stop()
        self._sample_rate = int(sample_rate)
        self._channels = int(channels)
        self._sample_width = int(sample_width)

        if isinstance(data, bytes):
            assert self._sample_width == 2, "Raw bytes path expects 16-bit PCM."
            int16 = np.frombuffer(data, dtype="<i2")
            frames = int16.reshape(-1, self._channels)
            self._float_ch = (frames.astype(np.float32) / 32767.0)
            self._mono_float = self._float_ch.mean(axis=1)
            self._pcm_bytes = frames.astype("<i2", copy=False).tobytes()
            self._sample_width = 2
        else:
            arr = np.asarray(data)
            if arr.ndim == 1:
                f = np.clip(arr.astype(np.float32), -1, 1)
                pcm = (f * 32767.0).astype(np.int16)
                if self._channels > 1: pcm = np.tile(pcm[:, None], (1, self._channels))
                self._float_ch = (pcm.astype(np.float32) / 32767.0)
                self._mono_float = self._float_ch.mean(axis=1) if self._channels > 1 else self._float_ch.reshape(-1)
                if self._channels == 1: self._float_ch = self._float_ch.reshape(-1, 1)
                self._pcm_bytes = pcm.astype("<i2", copy=False).tobytes()
            elif arr.ndim == 2:
                assert arr.shape[1] == self._channels, "channels mismatch with array shape"
                if arr.dtype == np.int16:
                    pcm = arr
                    self._float_ch = pcm.astype(np.float32) / 32767.0
                    self._mono_float = self._float_ch.mean(axis=1)
                    self._pcm_bytes = pcm.astype("<i2", copy=False).tobytes()
                    self._sample_width = 2
                else:
                    f = np.clip(arr.astype(np.float32), -1, 1)
                    pcm = (f * 32767.0).astype(np.int16)
                    self._float_ch = f
                    self._mono_float = f.mean(axis=1)
                    self._pcm_bytes = pcm.astype("<i2").tobytes()
                    self._sample_width = 2
            else:
                raise ValueError("Array must be 1D (frames,) or 2D (frames, channels)")

        self.canvas.set_wave(self._mono_float, self._sample_rate, self._float_ch)
        self._update_info(0)

    def set_effect(self, name: str, **params):
        self.canvas.set_visual_mode(name, **params)

    def play(self):
        if not self._pcm_bytes or self._sample_rate <= 0: return
        self.stop()
        fmt = QAudioFormat()
        fmt.setSampleRate(self._sample_rate)
        fmt.setChannelCount(self._channels)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        dev = QMediaDevices.defaultAudioOutput()
        self._audio = AudioOutClass(dev, fmt) if USE_SINK else AudioOutClass(fmt, dev)
        self._buffer = QBuffer(); self._buffer.setData(self._pcm_bytes); self._buffer.open(QIODevice.ReadOnly)
        self._audio.start(self._buffer)
        self._timer.start()
        self.canvas.set_playhead(0)

    def stop(self):
        self._timer.stop()
        if self._audio is not None:
            try: self._audio.stop()
            except Exception: pass
            self._audio = None
        if self._buffer is not None:
            try: self._buffer.close()
            except Exception: pass
            self._buffer = None
        if self._mono_float is not None:
            self.canvas.set_playhead(0)
            self._update_info(0)

    def _on_tick(self):
        if self._audio is None or self._mono_float is None:
            self._timer.stop(); return
        try: u = self._audio.processedUSecs()
        except Exception: u = getattr(self._audio, "elapsedUSecs", lambda: 0)()
        frames = int((u / 1_000_000.0) * self._sample_rate)
        total_frames = len(self._mono_float)
        frames = min(frames, total_frames)
        self.canvas.set_playhead(frames)
        self._update_info(frames)
        if frames >= total_frames: self.stop()

    def _update_info(self, frame_idx: int):
        if self._sample_rate <= 0 or self._mono_float is None:
            self.info_lbl.setText("00:00 / 00:00"); return
        cur_s = frame_idx / self._sample_rate
        tot_s = len(self._mono_float) / self._sample_rate
        self.info_lbl.setText(f"{self._fmt_time(cur_s)} / {self._fmt_time(tot_s)}")

    @staticmethod
    def _fmt_time(sec: float) -> str:
        sec = int(round(sec)); m, s = divmod(sec, 60)
        return f"{m:02d}:{s:02d}"


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = AudioWaveWidget(); w.resize(900, 260)
    sr = 48000
    t = np.linspace(0, 3.0, int(sr * 3.0), endpoint=False, dtype=np.float32)
    left = 0.6 * np.sin(2 * np.pi * 440.0 * t).astype(np.float32)
    right = 0.6 * np.sin(2 * np.pi * 659.255 * t).astype(np.float32)
    stereo = np.stack([left, right], axis=1)
    w.set_wave(stereo, sample_rate=sr, channels=2)
    w.set_effect("spectrum", bar_count=72, fft_size=4096, min_db=-80, max_db=0)
    w.show(); w.play()
    sys.exit(app.exec())
