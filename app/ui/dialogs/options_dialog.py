import json
import os
import tempfile
from typing import List

import requests
from PySide6.QtCore import QThread, Signal, Slot, Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QVBoxLayout, QWidget, QComboBox, QLineEdit, QTextEdit, QPushButton, \
    QLabel
from PySide6.QtWidgets import QTabWidget
from PySide6.QtCore import QSettings, QByteArray
from app.ui.widgets.AudioWaveWidget import AudioWaveWidget


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



class OptionsDialog(QDialog):

    def __init__(self):
        super().__init__()
        self.settings = QSettings()
        self.audio=None
        self.get_voice_list_worker = None
        self.stream_audio_worker = None
        self.main_layout=QVBoxLayout()

        self.setLayout(self.main_layout)
        self.tab_widget = QTabWidget()
        self.layout().addWidget(self.tab_widget)
        # -- Auth tab --
        self.create_auth_tab()
        # -- Tool server tab --
        self.create_tool_server_tab()
        # -- speech tab --
        self.button_layout=QHBoxLayout()
        self.create_speech_tab()

        self.load_settings()

        # Save on-the-fly when common fields change (optional but nice)
        self.voice_server_url.editingFinished.connect(
            lambda: self._save("speech/voice_server_url", self.voice_server_url.text())
        )
        self.voice_selection.currentTextChanged.connect(
            lambda v: self._save("speech/voice", v)
        )
        # If you added effect combo:
        if hasattr(self, "effect_combo"):
            self.effect_combo.currentTextChanged.connect(
                lambda v: self._save("speech/effect", v.lower())
            )

    def create_auth_tab(self):
        auth_tab=QWidget()
        self.tab_widget.addTab(auth_tab, "Authentication")

    def create_tool_server_tab(self):
        tool_server_tab=QWidget()
        self.tab_widget.addTab(tool_server_tab, "Tool server")

    def create_speech_tab(self):
        speech_tab=QWidget()
        speech_tab_layout = QVBoxLayout()
        speech_tab.setLayout(speech_tab_layout)
        # server address including port
        speech_tab_layout.addWidget( QLabel("Voice Server endpoint"))
        self.voice_server_url = QLineEdit()
        self.voice_server_url.setText("http://127.0.0.1:8008")
        speech_tab_layout.addWidget(self.voice_server_url)
        # voice selection
        voice_selection_layout=QHBoxLayout()
        speech_tab_layout.addWidget(QLabel("Voice"))
        self.voice_selection = QComboBox()
        refresh_voice_list_button=QPushButton("⟳")
        refresh_voice_list_button.setFixedWidth(40)
        voice_selection_layout.addWidget(self.voice_selection)
        voice_selection_layout.addWidget(refresh_voice_list_button)
        speech_tab_layout.addLayout(voice_selection_layout)
        # test
        self.tts_test_text = QTextEdit()
        self.test_tts_button = QPushButton("Test")
        self.wave_player = AudioWaveWidget()
        # Effect selector
        effect_row = QHBoxLayout()
        self.effect_combo = QComboBox()
        self.effect_combo.addItems(["waveform", "spectrum", "vu"])
        effect_row.addWidget(QLabel("Visualizer"))
        effect_row.addWidget(self.effect_combo)
        speech_tab_layout.addLayout(effect_row)

        # Default look
        self.wave_player.set_effect("spectrum", bar_count=64, fft_size=4096, min_db=-80, max_db=0)

        # Change effect at runtime
        def _on_effect_changed(name):
            name = name.lower()
            if name == "waveform":
                self.wave_player.set_effect("waveform")
            elif name == "spectrum":
                self.wave_player.set_effect("spectrum", bar_count=64, fft_size=4096, min_db=-80, max_db=0)
            elif name == "vu":
                self.wave_player.set_effect("vu", vu_window_ms=60)

        self.effect_combo.currentTextChanged.connect(_on_effect_changed)
        speech_tab_layout.addWidget(self.tts_test_text)
        speech_tab_layout.addWidget(self.test_tts_button)
        speech_tab_layout.addWidget(self.wave_player)
        self.tab_widget.addTab(speech_tab, "Speech")

        # -- Signals --
        refresh_voice_list_button.clicked.connect(self.refresh_voice_list)
        self.test_tts_button.clicked.connect(self.test_tts)

    def test_tts(self):
        self.test_tts_button.setEnabled(False)
        text = self.tts_test_text.toPlainText()
        url = self.voice_server_url.text()
        voice = self.voice_selection.currentText()

        self.stream_audio_worker = GenerateAudioWorker(url, voice, text)
        self.stream_audio_worker.audio_ready.connect(self.on_audio_ready)
        self.stream_audio_worker.complete.connect(self.on_tts_test_complete)
        self.stream_audio_worker.start()

    @Slot(str, bool)
    def on_tts_test_complete(self, message, success):
        print(f"TTS Worker finished: {message}")
        self.test_tts_button.setEnabled(True)
        if not success:
            # Optional: surface this in your UI
            pass


    def refresh_voice_list(self):
        self.get_voice_list_worker = GetVoiceListWorker(self.voice_server_url.text())
        self.get_voice_list_worker.start()
        self.get_voice_list_worker.complete.connect(self.got_voice_list)

    def got_voice_list(self, voice_list, success):
        if success:
            self.voice_selection.clear()
            self.voice_selection.addItems(voice_list)
            # Try to re-select user’s last voice
            if getattr(self, "_desired_voice", ""):
                ix = self.voice_selection.findText(self._desired_voice)
                if ix >= 0:
                    self.voice_selection.setCurrentIndex(ix)
        else:
            print(voice_list[0])

    @Slot(object)
    def on_audio_ready(self, wav_bytes):
        """Parse WAV bytes -> store -> update waveform display."""
        import io, wave, numpy as np

        with wave.open(io.BytesIO(wav_bytes), 'rb') as wav:
            sr = wav.getframerate()
            ch = wav.getnchannels()
            sw = wav.getsampwidth()  # bytes per sample
            nframes = wav.getnframes()
            raw = wav.readframes(nframes)

        # Keep a normalized, minimal structure for later playback
        self.audio = {"raw": raw, "sr": sr, "ch": ch, "sw": sw}

        # Push into the visual/player widget (expects raw PCM + format)
        # AudioWaveWidget supports raw 16-bit PCM or float32; we’ll handle 16-bit and float WAVs.
        if sw == 2:
            # int16
            self.wave_player.set_wave(self.audio["raw"], sample_rate=sr, channels=ch, sample_width=2)
        elif sw == 4:
            # Could be float32 or 24-bit-in-32-container. Try float32 first.
            try:
                # Convert float32 WAV frames to float np array then let widget convert to PCM
                arr = np.frombuffer(self.audio["raw"], dtype="<f4")
                if ch > 1:
                    arr = arr.reshape(-1, ch)
                self.wave_player.set_wave(arr, sample_rate=sr, channels=ch, sample_width=4)
            except Exception:
                # If it wasn’t float32, fall back (or raise). Most TTS servers return 16-bit anyway.
                raise Exception("Unsupported 32-bit WAV encoding for this player path.")
        else:
            raise Exception(f"Unsupported sample width: {sw} (expected 16-bit PCM or 32-bit float)")

        print(f"WAV ready: {sr} Hz, {ch} ch, {sw} bytes/sample, frames={nframes}")

    # -------- settings helpers --------
    def _save(self, key: str, value):
        self.settings.setValue(key, value)
        self.settings.sync()

    def _get(self, key: str, default=None, type_=None):
        # QSettings typed read
        if type_ is None:
            return self.settings.value(key, default)
        return self.settings.value(key, default, type=type_)

    def load_settings(self):
        # Geometry
        geo: QByteArray = self._get("dialogs/options/geometry", QByteArray(), QByteArray)
        if not geo.isEmpty():
            self.restoreGeometry(geo)

        # ----- Speech tab -----
        url = self._get("speech/voice_server_url", "http://127.0.0.1:8008", str)
        self.voice_server_url.setText(url)

        # Effect (default to spectrum)
        effect = (self._get("speech/effect", "spectrum", str) or "spectrum").lower()
        if hasattr(self, "effect_combo"):
            # Set combobox if present
            ix = self.effect_combo.findText(effect, Qt.MatchFlag.MatchFixedString | Qt.MatchFlag.MatchCaseSensitive)
            if ix >= 0:
                self.effect_combo.setCurrentIndex(ix)
            # Apply to player
            if effect == "waveform":
                self.wave_player.set_effect("waveform")
            elif effect == "vu":
                self.wave_player.set_effect("vu", vu_window_ms=60)
            else:
                self.wave_player.set_effect("spectrum", bar_count=64, fft_size=4096, min_db=-80, max_db=0)

        # Voice (apply after you’ve loaded the list)
        # We’ll stash the desired voice and apply it in got_voice_list()
        self._desired_voice = self._get("speech/voice", "", str)

        # Optional: restore last test text
        last_text = self._get("speech/test_text", "", str)
        if last_text:
            self.tts_test_text.setPlainText(last_text)

    def save_settings(self):
        # Geometry
        self._save("dialogs/options/geometry", self.saveGeometry())
        # Speech
        self._save("speech/voice_server_url", self.voice_server_url.text())
        if hasattr(self, "effect_combo"):
            self._save("speech/effect", self.effect_combo.currentText().lower())
        self._save("speech/test_text", self.tts_test_text.toPlainText())
        # Voice saved on change; but also ensure current stored on close:
        if self.voice_selection.currentIndex() >= 0:
            self._save("speech/voice", self.voice_selection.currentText())

    # Make sure we persist when dialog is accepted/closed
    def accept(self):
        self.save_settings()
        super().accept()

    def reject(self):
        self.save_settings()
        super().reject()

    def closeEvent(self, e):
        self.save_settings()
        super().closeEvent(e)