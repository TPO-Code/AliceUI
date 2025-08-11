import io
import time
import wave

import numpy as np
import requests
from PySide6.QtCore import Signal, QThread, Slot
from PySide6.QtMultimedia import QMediaDevices, QAudioSource, QAudioFormat


class MicRecorderWorker(QThread):
    recorded = Signal(bytes)  # WAV bytes
    error = Signal(str)

    def __init__(self, sr=16000, channels=1, parent=None):
        super().__init__(parent)
        self._sr = sr
        self._ch = channels
        self._running = False
        self._source = None
        self._buffer = io.BytesIO()

    def run(self):
        try:
            fmt = QAudioFormat()
            fmt.setSampleRate(self._sr)
            fmt.setChannelCount(self._ch)
            fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            dev = QMediaDevices.defaultAudioInput()
            if not dev.isNull():
                self._source = QAudioSource(dev, fmt)
            else:
                self.error.emit("No audio input device found")
                return

            self._buffer = io.BytesIO()
            # write a placeholder WAV header; we’ll fix sizes on stop
            with wave.open(self._buffer, 'wb') as w:
                w.setnchannels(self._ch)
                w.setsampwidth(2)
                w.setframerate(self._sr)
                # keep file open; we’ll append raw PCM manually below

            # start Qt capture
            io_dev = self._source.start()
            if io_dev is None:
                self.error.emit("Failed to start audio input")
                return

            self._running = True
            chunk = 4096
            while self._running:
                if self._source.bytesAvailable() >= chunk:
                    data = io_dev.read(chunk)
                    if data:
                        # append raw to the RIFF after the header (we’ll rebuild header at the end)
                        self._buffer.seek(0, io.SEEK_END)
                        self._buffer.write(bytes(data))
                self.msleep(10)

            # finalize: rebuild proper WAV with sizes
            raw = self._buffer.getvalue()
            # first 44 bytes are our earlier header, the rest is PCM—we’ll regenerate properly:
            pcm = raw[44:] if len(raw) >= 44 else raw
            out = io.BytesIO()
            with wave.open(out, 'wb') as w:
                w.setnchannels(self._ch)
                w.setsampwidth(2)
                w.setframerate(self._sr)
                w.writeframes(pcm)
            self.recorded.emit(out.getvalue())

        except Exception as e:
            self.error.emit(str(e))
        finally:
            try:
                if self._source:
                    self._source.stop()
            except Exception:
                pass
            self._source = None

    def stop_recording(self):
        self._running = False

class MicVADWorker(QThread):
    segment = Signal(bytes)  # WAV bytes for each detected utterance
    error = Signal(str)

    def __init__(self, sr=16000, channels=1, rms_thresh=0.03, min_active_ms=200, silence_ms=500, parent=None):
        super().__init__(parent)
        self._sr = sr
        self._ch = channels
        self._rms_thresh = rms_thresh
        self._min_active = min_active_ms
        self._silence = silence_ms
        self._running = False
        self._blocked = False  # pause capturing during LLM or playback
        self._source = None

    @Slot(bool)
    def set_blocked(self, blocked: bool):
        self._blocked = bool(blocked)

    def run(self):
        try:
            fmt = QAudioFormat()
            fmt.setSampleRate(self._sr)
            fmt.setChannelCount(self._ch)
            fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            dev = QMediaDevices.defaultAudioInput()
            if not dev.isNull():
                self._source = QAudioSource(dev, fmt)
            else:
                self.error.emit("No audio input device found")
                return

            io_dev = self._source.start()
            if io_dev is None:
                self.error.emit("Failed to start audio input")
                return

            self._running = True
            chunk = 2048  # ~64-128ms depending on sample rate
            active = False
            active_start_ms = 0
            last_voice_ms = 0
            pcm_chunks: list[bytes] = []

            def now_ms(): return int(time.time() * 1000)

            while self._running:
                # If blocked, drain input but don't accumulate; reset state
                if self._blocked:
                    active = False
                    pcm_chunks.clear()
                    # drain
                    _ = io_dev.readAll()
                    self.msleep(20)
                    continue

                if self._source.bytesAvailable() >= chunk:
                    data = io_dev.read(chunk)
                    if not data:
                        self.msleep(5); continue
                    b = bytes(data)
                    # compute RMS quickly
                    if len(b) >= 2:
                        arr = np.frombuffer(b, dtype="<i2").astype(np.float32) / 32767.0
                        rms = float(np.sqrt(np.mean(arr * arr))) if arr.size else 0.0
                    else:
                        rms = 0.0

                    t = now_ms()
                    if rms >= self._rms_thresh:
                        last_voice_ms = t
                        if not active:
                            active = True
                            active_start_ms = t
                            pcm_chunks = [b]
                        else:
                            pcm_chunks.append(b)
                    else:
                        if active:
                            pcm_chunks.append(b)
                            # if we’ve been quiet long enough, close segment
                            if t - last_voice_ms >= self._silence and (last_voice_ms - active_start_ms) >= self._min_active:
                                # package WAV
                                out = io.BytesIO()
                                with wave.open(out, 'wb') as w:
                                    w.setnchannels(self._ch)
                                    w.setsampwidth(2)
                                    w.setframerate(self._sr)
                                    w.writeframes(b"".join(pcm_chunks))
                                self.segment.emit(out.getvalue())
                                active = False
                                pcm_chunks.clear()
                            elif t - last_voice_ms >= self._silence:
                                # too short; drop
                                active = False
                                pcm_chunks.clear()
                else:
                    self.msleep(10)

        except Exception as e:
            self.error.emit(str(e))
        finally:
            try:
                if self._source:
                    self._source.stop()
            except Exception:
                pass
            self._source = None

    def stop_vad(self):
        self._running = False


class TranscribeWorker(QThread):
    finished = Signal(str, bool)  # (text, success)

    def __init__(self, base_url: str, wav_bytes: bytes, device: str = "cuda"):
        super().__init__()
        self.url = base_url.rstrip("/") + "/speech/transcribe"
        self.wav = wav_bytes
        self.device = device

    def run(self):
        try:
            files = {"file": ("input.wav", self.wav, "audio/wav")}
            data = {"device": self.device}
            r = requests.post(self.url, files=files, data=data, timeout=60)
            r.raise_for_status()
            js = r.json()
            text = js.get("text", "")
            self.finished.emit(text, True)
        except Exception as e:
            self.finished.emit(str(e), False)
