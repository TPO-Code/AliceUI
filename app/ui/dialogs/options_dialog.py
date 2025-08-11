import json
import os
import tempfile
from typing import List

import requests
from PySide6.QtCore import QThread, Signal, Slot, Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QVBoxLayout, QWidget, QComboBox, QLineEdit, QTextEdit, QPushButton, \
    QLabel, QListWidgetItem, QTableWidgetItem, QMessageBox, QAbstractItemView, QHeaderView, QTableWidget, QGroupBox, \
    QListWidget, QCheckBox
from PySide6.QtWidgets import QTabWidget
from PySide6.QtCore import QSettings, QByteArray
from app.ui.widgets.AudioWaveWidget import AudioWaveWidget
from app.core.settings_manager import SettingsManager
from app.api.llm_api import GetRemoteModelsWorker
class AuthTabWidget(QWidget):
    """
    Lets users add API providers (OpenAI, Anthropic, DeepSeek, Custom...) with keys and a list of models.
    """
    KNOWN_PROVIDERS = [
        {"id": "openai", "name": "OpenAI", "base_url_hint": "", "key_hint": "sk-..."},
        {"id": "anthropic", "name": "Anthropic", "base_url_hint": "", "key_hint": "sk-ant-..."},
        {"id": "deepseek", "name": "DeepSeek", "base_url_hint": "https://api.deepseek.com", "key_hint": "sk-..."},
        {"id": "custom", "name": "Custom (OpenAI-compatible)", "base_url_hint": "https://your-endpoint", "key_hint": "sk-..."},
    ]

    def __init__(self, settings: SettingsManager, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._providers = self.settings.get_providers()

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # --- Editor group ---
        editor = QGroupBox("Add / Edit Provider")
        eg = QVBoxLayout(editor)

        row1 = QHBoxLayout()
        self.provider_type = QComboBox()
        for p in self.KNOWN_PROVIDERS:
            self.provider_type.addItem(p["name"], p)
        row1.addWidget(QLabel("Type:"))
        row1.addWidget(self.provider_type)

        self.display_name = QLineEdit()
        self.display_name.setPlaceholderText("Display name (e.g., OpenAI, Anthropic, My Local API)")
        row1.addWidget(QLabel("Name:"))
        row1.addWidget(self.display_name)

        eg.addLayout(row1)

        row2 = QHBoxLayout()
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.Password)
        self.api_key.setPlaceholderText("API key")
        self.show_key = QCheckBox("Show")
        self.show_key.toggled.connect(lambda on: self.api_key.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
        row2.addWidget(QLabel("API Key:"))
        row2.addWidget(self.api_key, 1)
        row2.addWidget(self.show_key)
        eg.addLayout(row2)

        row3 = QHBoxLayout()
        self.base_url = QLineEdit()
        self.base_url.setPlaceholderText("Optional base URL (needed for custom/OpenAI-compatible endpoints)")
        row3.addWidget(QLabel("Base URL:"))
        row3.addWidget(self.base_url, 1)
        eg.addLayout(row3)

        # Models editor
        models_box = QGroupBox("Models exposed to Chat")
        mb = QVBoxLayout(models_box)
        self.model_input = QLineEdit()
        self.model_input.setPlaceholderText("e.g., gpt-4o-mini, claude-3-5-sonnet, deepseek-chat")
        add_model_btn = QPushButton("Add model")
        self.models_list = QListWidget()
        rm_model_btn = QPushButton("Remove selected")

        rowm = QHBoxLayout()
        rowm.addWidget(self.model_input, 1)
        rowm.addWidget(add_model_btn)
        mb.addLayout(rowm)
        mb.addWidget(self.models_list)
        mb.addWidget(rm_model_btn)
        eg.addWidget(models_box)

        # Buttons
        btns = QHBoxLayout()
        self.fetch_models_btn = QPushButton("Fetch models")  # <-- NEW
        self.add_update_btn = QPushButton("Add/Update Provider")
        self.clear_form_btn = QPushButton("Clear Form")
        btns.addStretch(1)
        btns.addWidget(self.fetch_models_btn)  # <-- NEW
        btns.addWidget(self.add_update_btn)
        btns.addWidget(self.clear_form_btn)
        eg.addLayout(btns)

        root.addWidget(editor)

        # --- Table of providers ---
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Name", "Type", "Models", "Key (masked)"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)

        # row actions
        row_actions = QHBoxLayout()
        self.edit_btn = QPushButton("Edit Selected")
        self.delete_btn = QPushButton("Delete Selected")
        row_actions.addStretch(1)
        row_actions.addWidget(self.edit_btn)
        row_actions.addWidget(self.delete_btn)

        root.addWidget(self.table)
        root.addLayout(row_actions)
        root.addStretch(1)

        # wiring
        add_model_btn.clicked.connect(self._add_model_to_list)
        rm_model_btn.clicked.connect(self._remove_selected_model)
        self.add_update_btn.clicked.connect(self._add_or_update_provider)
        self.clear_form_btn.clicked.connect(self._clear_form)
        self.edit_btn.clicked.connect(self._edit_selected_row)
        self.delete_btn.clicked.connect(self._delete_selected_row)
        self.provider_type.currentIndexChanged.connect(self._apply_type_defaults)
        self.fetch_models_btn.clicked.connect(self._fetch_models_for_current)

        self._apply_type_defaults()
        self._refresh_table()

    def _apply_type_defaults(self):
        meta = self.provider_type.currentData()
        if not self.display_name.text().strip():
            self.display_name.setText(meta["name"])
        if meta.get("base_url_hint"):
            if not self.base_url.text().strip():
                self.base_url.setText(meta["base_url_hint"])
        # place a gentle hint for the key format
        self.api_key.setPlaceholderText(meta.get("key_hint", "sk-..."))

    def _add_model_to_list(self):
        m = self.model_input.text().strip()
        if not m:
            return
        # Avoid duplicates
        for i in range(self.models_list.count()):
            if self.models_list.item(i).text() == m:
                self.model_input.clear()
                return
        self.models_list.addItem(QListWidgetItem(m))
        self.model_input.clear()

    def _remove_selected_model(self):
        for item in self.models_list.selectedItems():
            self.models_list.takeItem(self.models_list.row(item))

    def _collect_models(self):
        return [self.models_list.item(i).text() for i in range(self.models_list.count())]

    def _add_or_update_provider(self):
        pid = self.provider_type.currentData()["id"]
        name = self.display_name.text().strip() or self.provider_type.currentData()["name"]
        key = self.api_key.text().strip()
        base = self.base_url.text().strip()
        models = self._collect_models()

        if not key:
            QMessageBox.warning(self, "Missing key", "Please enter an API key.")
            return

        # Update or insert
        existing = next((p for p in self._providers if p["id"] == pid), None)
        data = {"id": pid, "name": name, "api_key": key, "base_url": base, "models": models}
        if existing:
            existing.update(data)
        else:
            self._providers.append(data)

        self.settings.save_providers(self._providers)
        self._refresh_table()
        self._clear_form()

    def _clear_form(self):
        self.display_name.clear()
        self.api_key.clear()
        self.base_url.clear()
        self.model_input.clear()
        self.models_list.clear()
        self.provider_type.setCurrentIndex(0)
        self._apply_type_defaults()

    def _edit_selected_row(self):
        row = self.table.currentRow()
        if row < 0:
            return
        pid = self.table.item(row, 1).data(Qt.UserRole)
        prov = next((p for p in self._providers if p["id"] == pid), None)
        if not prov:
            return
        # hydrate form
        idx = next((i for i in range(self.provider_type.count()) if self.provider_type.itemData(i)["id"] == prov["id"]), 0)
        self.provider_type.setCurrentIndex(idx)
        self.display_name.setText(prov.get("name", ""))
        self.api_key.setText(prov.get("api_key", ""))
        self.base_url.setText(prov.get("base_url", ""))
        self.models_list.clear()
        for m in prov.get("models", []):
            self.models_list.addItem(QListWidgetItem(m))

    def _delete_selected_row(self):
        row = self.table.currentRow()
        if row < 0:
            return
        pid = self.table.item(row, 1).data(Qt.UserRole)
        self._providers = [p for p in self._providers if p["id"] != pid]
        self.settings.save_providers(self._providers)
        self._refresh_table()

    def _refresh_table(self):
        self.table.setRowCount(0)
        for p in self._providers:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(p.get("name", p["id"])))
            type_item = QTableWidgetItem(p["id"])
            type_item.setData(Qt.UserRole, p["id"])
            self.table.setItem(r, 1, type_item)
            self.table.setItem(r, 2, QTableWidgetItem(", ".join(p.get("models", [])) or "—"))
            masked = "•" * 8 if p.get("api_key") else ""
            self.table.setItem(r, 3, QTableWidgetItem(masked))

    def _current_form_provider(self) -> dict:
        """Build a single-provider dict from the current form."""
        meta = self.provider_type.currentData() or {}
        pid = meta.get("id", "custom")
        return {
            "id": pid,
            "name": self.display_name.text().strip() or meta.get("name", pid),
            "api_key": self.api_key.text().strip(),
            "base_url": self.base_url.text().strip(),
            "models": self._collect_models(),
        }

    def _fetch_models_for_current(self):
        prov = self._current_form_provider()
        pid = (prov.get("id") or "").lower()

        # quick validation
        if not prov.get("api_key"):
            QMessageBox.warning(self, "API key required", "Please enter an API key first.")
            return
        if pid == "custom" and not prov.get("base_url"):
            QMessageBox.warning(self, "Base URL required", "Custom (OpenAI-compatible) requires a Base URL.")
            return

        self.fetch_models_btn.setEnabled(False)

        # Use the worker with a single-provider list
        self._fetch_worker = GetRemoteModelsWorker([prov])
        self._fetch_worker.completed_llm_call.connect(self._on_fetch_models_ok)
        self._fetch_worker.failed_llm_call.connect(self._on_fetch_models_err)
        self._fetch_worker.start()

    def _on_fetch_models_ok(self, mapping: dict):
        """mapping: { provider_id: [model_id, ...] }"""
        self.fetch_models_btn.setEnabled(True)
        prov = self._current_form_provider()
        pid = (prov.get("id") or "").lower()
        auto = mapping.get(pid, []) or []

        # Merge into the list widget (manual first, then fetched uniques)
        before = set(self._collect_models())
        added = 0
        for m in auto:
            if m and m not in before:
                self.models_list.addItem(QListWidgetItem(m))
                before.add(m)
                added += 1

        # If this provider already exists in saved settings, update and save
        existing = next((p for p in self._providers if p["id"] == pid), None)
        if existing:
            existing["models"] = self._collect_models()
            self.settings.save_providers(self._providers)
            self._refresh_table()

        QMessageBox.information(
            self, "Models fetched",
            f"Found {len(auto)} models; added {added} new to the list."
        )

    def _on_fetch_models_err(self, err: str):
        self.fetch_models_btn.setEnabled(True)
        QMessageBox.warning(self, "Fetch failed", f"Could not fetch models:\n\n{err}")

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
        self.settings = SettingsManager(self)
        self._vis_fg = None
        self._vis_bg = None
        self._bins_per_side = 16
        self._bin_gap_px = 2
        self._smoothing = 0.45
        self._fade_decay = 0.88
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
        self.auth_tab = AuthTabWidget(self.settings, self)
        self.tab_widget.addTab(self.auth_tab, "Auth")

    def create_tool_server_tab(self):
        tool_server_tab=QWidget()
        self.tab_widget.addTab(tool_server_tab, "Tool server")

    def create_speech_tab(self):
        speech_tab = QWidget()
        speech_tab_layout = QVBoxLayout(speech_tab)

        # --- Server + voice (unchanged) ---
        speech_tab_layout.addWidget(QLabel("Voice Server endpoint"))
        self.voice_server_url = QLineEdit("http://127.0.0.1:8008")
        speech_tab_layout.addWidget(self.voice_server_url)

        speech_tab_layout.addWidget(QLabel("STT Server endpoint"))
        self.stt_server_url = QLineEdit()
        self.stt_server_url.setText(self._get("speech/stt_server_url", self.voice_server_url.text(), str))
        speech_tab_layout.addWidget(self.stt_server_url)

        self.stt_server_url.editingFinished.connect(
            lambda: self._save("speech/stt_server_url", self.stt_server_url.text())
        )

        voice_row = QHBoxLayout()
        speech_tab_layout.addWidget(QLabel("Voice"))
        self.voice_selection = QComboBox()
        refresh_btn = QPushButton("⟳");
        refresh_btn.setFixedWidth(40)
        voice_row.addWidget(self.voice_selection)
        voice_row.addWidget(refresh_btn)
        speech_tab_layout.addLayout(voice_row)

        # --- Test text + generate ---
        self.tts_test_text = QTextEdit()
        self.tts_test_text.setPlaceholderText("Type something to synthesize…")
        self.test_tts_button = QPushButton("Generate")
        speech_tab_layout.addWidget(self.tts_test_text)
        speech_tab_layout.addWidget(self.test_tts_button)

        # --- New slim visualizer chip ---
        from app.ui.widgets.AudioWaveWidget import AudioWaveWidget
        self.wave_player = AudioWaveWidget()
        self.wave_player.set_compact(height_px=22, show_buttons=True)
        self.wave_player.set_colors("#8be9fd", "#1e1f29")  # will be overridden by settings
        self.wave_player.set_effect("symmetric_bins",
                                    bins_per_side=self._bins_per_side,
                                    bin_gap_px=self._bin_gap_px,
                                    smoothing=self._smoothing,
                                    fade_decay=self._fade_decay
                                    )
        # Regenerate => same as Generate button
        self.wave_player.regenerate_requested.connect(self.test_tts)

        # --- Color pickers ---
        color_row = QHBoxLayout()
        color_row.addWidget(QLabel("Visualizer colors:"))
        self.fg_color_btn = QPushButton("FG");
        self.fg_color_btn.setFixedWidth(36)
        self.bg_color_btn = QPushButton("BG");
        self.bg_color_btn.setFixedWidth(36)
        color_row.addWidget(self.fg_color_btn)
        color_row.addWidget(self.bg_color_btn)
        color_row.addStretch()

        # --- Param controls (bins, gap, smoothing, fade) ---
        from PySide6.QtWidgets import QSpinBox, QDoubleSpinBox
        params_row = QHBoxLayout()
        # Bins/side
        params_row.addWidget(QLabel("Bins/side"))
        self.bins_spin = QSpinBox();
        self.bins_spin.setRange(4, 64);
        self.bins_spin.setValue(self._bins_per_side)
        params_row.addWidget(self.bins_spin)
        # Gap
        params_row.addWidget(QLabel("Gap(px)"))
        self.gap_spin = QSpinBox();
        self.gap_spin.setRange(0, 12);
        self.gap_spin.setValue(self._bin_gap_px)
        params_row.addWidget(self.gap_spin)
        # Smoothing
        params_row.addWidget(QLabel("Smoothing"))
        self.smooth_spin = QDoubleSpinBox();
        self.smooth_spin.setDecimals(2);
        self.smooth_spin.setRange(0.05, 0.95)
        self.smooth_spin.setSingleStep(0.05);
        self.smooth_spin.setValue(self._smoothing)
        params_row.addWidget(self.smooth_spin)
        # Fade decay
        params_row.addWidget(QLabel("Fade"))
        self.fade_spin = QDoubleSpinBox();
        self.fade_spin.setDecimals(2);
        self.fade_spin.setRange(0.70, 0.99)
        self.fade_spin.setSingleStep(0.01);
        self.fade_spin.setValue(self._fade_decay)
        params_row.addWidget(self.fade_spin)
        params_row.addStretch()

        # Add rows + player
        speech_tab_layout.addLayout(color_row)
        speech_tab_layout.addLayout(params_row)
        speech_tab_layout.addWidget(self.wave_player)

        self.tab_widget.addTab(speech_tab, "Speech")

        # --- Signals ---
        refresh_btn.clicked.connect(self.refresh_voice_list)
        self.test_tts_button.clicked.connect(self.test_tts)

        # Color pickers
        from PySide6.QtWidgets import QColorDialog
        def pick_fg():
            c = QColorDialog.getColor(parent=self)
            if c.isValid():
                self._vis_fg = c.name()
                self.wave_player.set_colors(self._vis_fg, self._vis_bg or "#1e1f29")
                self._save("speech/vis_fg", self._vis_fg)

        def pick_bg():
            c = QColorDialog.getColor(parent=self)
            if c.isValid():
                self._vis_bg = c.name()
                self.wave_player.set_colors(self._vis_fg or "#8be9fd", self._vis_bg)
                self._save("speech/vis_bg", self._vis_bg)

        self.fg_color_btn.clicked.connect(pick_fg)
        self.bg_color_btn.clicked.connect(pick_bg)

        # Param changes -> apply + persist
        def apply_params():
            self._bins_per_side = self.bins_spin.value()
            self._bin_gap_px = self.gap_spin.value()
            self._smoothing = float(self.smooth_spin.value())
            self._fade_decay = float(self.fade_spin.value())
            self.wave_player.set_effect("symmetric_bins",
                                        bins_per_side=self._bins_per_side,
                                        bin_gap_px=self._bin_gap_px,
                                        smoothing=self._smoothing,
                                        fade_decay=self._fade_decay
                                        )
            # save
            self._save("speech/bins_per_side", self._bins_per_side)
            self._save("speech/bin_gap_px", self._bin_gap_px)
            self._save("speech/smoothing", self._smoothing)
            self._save("speech/fade_decay", self._fade_decay)

        self.bins_spin.valueChanged.connect(lambda _: apply_params())
        self.gap_spin.valueChanged.connect(lambda _: apply_params())
        self.smooth_spin.valueChanged.connect(lambda _: apply_params())
        self.fade_spin.valueChanged.connect(lambda _: apply_params())

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
    @Slot(object)
    def on_audio_ready(self, wav_bytes):
        """Parse WAV bytes -> feed the compact AudioWaveWidget -> auto-play."""
        import io, wave, numpy as np

        with wave.open(io.BytesIO(wav_bytes), 'rb') as w:
            sr = w.getframerate()
            ch = w.getnchannels()
            sw = w.getsampwidth()  # bytes per sample
            nframes = w.getnframes()
            raw = w.readframes(nframes)

        # Keep a tiny record if you need it elsewhere
        self.audio = {"raw": raw, "sr": sr, "ch": ch, "sw": sw}

        try:
            if sw == 2:
                # 16-bit PCM: let the widget take raw bytes (little-endian)
                self.wave_player.set_wave(raw, sample_rate=sr, channels=ch)
            elif sw == 4:
                # Commonly float32 WAV from TTS servers
                # First try float32; if it explodes, fall back to int32->float path.
                try:
                    arr = np.frombuffer(raw, dtype="<f4")
                    if ch > 1:
                        arr = arr.reshape(-1, ch)
                    # ensure safe range
                    arr = np.clip(arr, -1.0, 1.0).astype(np.float32, copy=False)
                except Exception:
                    # Fallback: treat as signed int32 and normalize
                    i32 = np.frombuffer(raw, dtype="<i4")
                    if ch > 1:
                        i32 = i32.reshape(-1, ch)
                    arr = (i32.astype(np.float32) / 2147483647.0)
                    arr = np.clip(arr, -1.0, 1.0)

                self.wave_player.set_wave(arr, sample_rate=sr, channels=ch)
            else:
                # Uncommon format (e.g., 24-bit). Convert to float32 best-effort.
                # Interpret as signed integer with given width, normalize.
                import numpy as np
                dtype = {1: np.int8, 2: np.int16, 3: np.int32, 4: np.int32}.get(sw, np.int16)
                i_arr = np.frombuffer(raw, dtype=f"<{np.dtype(dtype).str[1:]}")
                if sw == 3:
                    # 24-bit packed rarely lands here; treat as 32 and downscale a bit
                    i_arr = (i_arr >> 8)
                if ch > 1:
                    i_arr = i_arr.reshape(-1, ch)
                max_int = float(np.iinfo(np.int32 if sw >= 3 else dtype).max)
                arr = np.clip(i_arr.astype(np.float32) / max_int, -1.0, 1.0)
                self.wave_player.set_wave(arr, sample_rate=sr, channels=ch)

            # fire it up
            self.wave_player.play()

        except Exception as e:
            # Don't crash the dialog; surface in logs or a debug print
            print(f"[on_audio_ready] Unsupported WAV format (sw={sw}) or parse error: {e}")


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

        # Server URL
        url = self._get("speech/voice_server_url", "http://127.0.0.1:8008", str)
        self.voice_server_url.setText(url)

        stt_url = self._get("speech/stt_server_url", url, str)  # default to the TTS url if unset
        if hasattr(self, "stt_server_url"):
            self.stt_server_url.setText(stt_url)

        # Colors
        self._vis_fg = self._get("speech/vis_fg", "#8be9fd", str)
        self._vis_bg = self._get("speech/vis_bg", "#1e1f29", str)
        if hasattr(self, "wave_player"):
            self.wave_player.set_colors(self._vis_fg, self._vis_bg)

        # Params
        self._bins_per_side = int(self._get("speech/bins_per_side", 16, int))
        self._bin_gap_px = int(self._get("speech/bin_gap_px", 2, int))
        self._smoothing = float(self._get("speech/smoothing", 0.45, float))
        self._fade_decay = float(self._get("speech/fade_decay", 0.88, float))

        if hasattr(self, "bins_spin"):
            self.bins_spin.setValue(self._bins_per_side)
            self.gap_spin.setValue(self._bin_gap_px)
            self.smooth_spin.setValue(self._smoothing)
            self.fade_spin.setValue(self._fade_decay)

        if hasattr(self, "wave_player"):
            self.wave_player.set_effect("symmetric_bins",
                                        bins_per_side=self._bins_per_side,
                                        bin_gap_px=self._bin_gap_px,
                                        smoothing=self._smoothing,
                                        fade_decay=self._fade_decay
                                        )

        # Voice preference
        self._desired_voice = self._get("speech/voice", "", str)

        # Restore last test text
        last_text = self._get("speech/test_text", "", str)
        if last_text:
            self.tts_test_text.setPlainText(last_text)

    def save_settings(self):
        self._save("dialogs/options/geometry", self.saveGeometry())
        self._save("speech/voice_server_url", self.voice_server_url.text())
        self._save("speech/test_text", self.tts_test_text.toPlainText())
        if self.voice_selection.currentIndex() >= 0:
            self._save("speech/voice", self.voice_selection.currentText())

        if hasattr(self, "stt_server_url"):
            self._save("speech/stt_server_url", self.stt_server_url.text())

        if self._vis_fg: self._save("speech/vis_fg", self._vis_fg)
        if self._vis_bg: self._save("speech/vis_bg", self._vis_bg)
        self._save("speech/bins_per_side", self._bins_per_side)
        self._save("speech/bin_gap_px", self._bin_gap_px)
        self._save("speech/smoothing", self._smoothing)
        self._save("speech/fade_decay", self._fade_decay)

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