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
    segment = Signal(bytes)
    error = Signal(str)

    def __init__(self, sr=16000, channels=1, rms_thresh=0.03,
                 min_active_ms=200, silence_ms=500, parent=None,
                 auto=False, auto_multiplier=3.5, auto_min_floor=0.02,
                 noise_ema_alpha=0.05):
        super().__init__(parent)
        self._sr = sr; self._ch = channels
        self._rms_thresh = rms_thresh
        self._min_active = min_active_ms
        self._silence = silence_ms
        self._running = False
        self._blocked = False
        self._source = None
        # auto params
        self._auto = bool(auto)
        self._auto_mult = float(auto_multiplier)
        self._auto_floor = float(auto_min_floor)
        self._alpha = float(noise_ema_alpha)
        self._noise_ema = self._auto_floor

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
            if dev.isNull():
                self.error.emit("No audio input device found"); return
            self._source = QAudioSource(dev, fmt)
            io_dev = self._source.start()
            if io_dev is None:
                self.error.emit("Failed to start audio input"); return

            self._running = True
            chunk = 2048
            active = False
            active_start_ms = 0
            last_voice_ms = 0
            pcm_chunks: list[bytes] = []

            def now_ms(): return int(time.time() * 1000)

            while self._running:
                if self._blocked:
                    active = False; pcm_chunks.clear()
                    _ = io_dev.readAll()
                    self.msleep(20); continue

                if self._source.bytesAvailable() >= chunk:
                    data = io_dev.read(chunk)
                    b = bytes(data) if data else b""
                    if len(b) >= 2:
                        arr = np.frombuffer(b, dtype="<i2").astype(np.float32) / 32767.0
                        rms = float(np.sqrt(np.mean(arr * arr))) if arr.size else 0.0
                    else:
                        rms = 0.0

                    # ---- adaptive thresholding ----
                    if self._auto:
                        # update noise floor when we're probably not speaking
                        # (below current threshold)
                        cur_thresh = max(self._auto_floor, self._noise_ema * self._auto_mult)
                        if rms < cur_thresh:
                            self._noise_ema = (1 - self._alpha) * self._noise_ema + self._alpha * rms
                            cur_thresh = max(self._auto_floor, self._noise_ema * self._auto_mult)
                        thresh = cur_thresh
                    else:
                        thresh = self._rms_thresh

                    t = now_ms()
                    if rms >= thresh:
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
                            long_enough = (last_voice_ms - active_start_ms) >= self._min_active
                            quiet_enough = (t - last_voice_ms) >= self._silence
                            if quiet_enough and long_enough:
                                out = io.BytesIO()
                                with wave.open(out, 'wb') as w:
                                    w.setnchannels(self._ch); w.setsampwidth(2); w.setframerate(self._sr)
                                    w.writeframes(b"".join(pcm_chunks))
                                self.segment.emit(out.getvalue())
                                active = False; pcm_chunks.clear()
                            elif quiet_enough:
                                active = False; pcm_chunks.clear()
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

    @Slot(float, int, int)
    def update_params(self, rms_thresh: float = None, min_active_ms: int = None, silence_ms: int = None):
        if rms_thresh is not None:
            self._rms_thresh = float(rms_thresh)
        if min_active_ms is not None:
            self._min_active = int(min_active_ms)
        if silence_ms is not None:
            self._silence = int(silence_ms)


class GetVoiceListWorker(QThread):
    complete = Signal(list,bool)

    def __init__(self, voice_server_url):
        super().__init__()
        self.url=voice_server_url

    @Slot()
    def run(self):
        print("Getting Voice List")
        try:# http://{host}:{port}/voices/list
            result=requests.get(self.url+"/voices/list")
            result.raise_for_status()
            print(result.json())
            print("Voice List received")
            #message_content = result.get('message', {}).get('content', '')
            self.complete.emit(result.json(), True)

        except Exception as e:
            self.complete.emit(f"Failed to retrieve the voice list from sever at {self.url}: {e}", False)


class GenerateAudioWorker(QThread):
    audio_ready = Signal(object)        # WAV bytes
    complete = Signal(str, bool)        # message, success

    def __init__(self, voice_server_url, voice, text):
        super().__init__()
        self.endpoint = voice_server_url + "/speech/generate"
        self.voice = voice
        self.text = text

    @Slot()
    def run(self):
        try:
            payload = {"text": self.text, "voice": self.voice}
            response = requests.post(self.endpoint, json=payload)
            response.raise_for_status()
            wav_bytes = response.content
            self.audio_ready.emit(wav_bytes)
            self.complete.emit("Audio fetched successfully.", True)
        except requests.exceptions.RequestException as e:
            self.complete.emit(f"Network error: {e}", False)
        except Exception as e:
            self.complete.emit(f"An error occurred: {e}", False)


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

class MicLevelProbeWorker(QThread):
    level = Signal(float)   # current RMS 0..1
    error = Signal(str)

    def __init__(self, sr=16000, channels=1, parent=None):
        super().__init__(parent)
        self._sr = sr
        self._ch = channels
        self._running = False
        self._source = None

    def run(self):
        try:
            fmt = QAudioFormat()
            fmt.setSampleRate(self._sr)
            fmt.setChannelCount(self._ch)
            fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            dev = QMediaDevices.defaultAudioInput()
            if dev.isNull():
                self.error.emit("No audio input device found")
                return
            self._source = QAudioSource(dev, fmt)
            io_dev = self._source.start()
            if io_dev is None:
                self.error.emit("Failed to start audio input")
                return
            self._running = True
            chunk = 2048
            while self._running:
                if self._source.bytesAvailable() >= chunk:
                    data = io_dev.read(chunk)
                    b = bytes(data) if data else b""
                    if len(b) >= 2:
                        arr = np.frombuffer(b, dtype="<i2").astype(np.float32) / 32767.0
                        rms = float(np.sqrt(np.mean(arr * arr))) if arr.size else 0.0
                    else:
                        rms = 0.0
                    self.level.emit(rms)
                self.msleep(30)
        except Exception as e:
            self.error.emit(str(e))
        finally:
            try:
                if self._source:
                    self._source.stop()
            except Exception:
                pass
            self._source = None

    def stop_probe(self):
        self._running = False
