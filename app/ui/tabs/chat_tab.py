from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QComboBox, QSplitter, QTextEdit, QHBoxLayout, QCheckBox, QMessageBox

from app.api.llm_api import GetModelListWorker
from app.core.settings_manager import SettingsManager
from app.data.colors import UIColors
from app.data.app_data import app_data
from app.ui.dialogs.options_dialog import GenerateAudioWorker
from app.ui.widgets.chat_text_input_widget import ChatTextInputWidget
from app.ui.widgets.chat_view_widget import ChatViewWidget


class ChatTab(QWidget):
    def __init__(self):
        super().__init__()
        self._last_spoken_text = ""
        self._tts_worker = None
        app_data.set("messages", [])
        self.settings = SettingsManager(self)
        self._remote_models: dict[str, list[str]] = {}
        self._remote_models_worker_started = False
        main_layout = QVBoxLayout()
        self.setLayout(main_layout)

        # --  Model selection and options  --
        options_layout=QHBoxLayout()
        self.model_selection = QComboBox()
        self.TTS_toggle =QCheckBox("Text To Speech")
        main_layout.addWidget(self.model_selection)
        main_layout.addWidget(self.TTS_toggle)
        options_layout.addWidget(self.model_selection)
        options_layout.addWidget(self.TTS_toggle)
        main_layout.addLayout(options_layout)

        splitter = QSplitter(Qt.Orientation.Vertical)

        main_layout.addWidget(splitter)
        # --  System prompt  --

        self.system_prompt = QTextEdit()
        self.system_prompt.setPlaceholderText("System Prompt")
        self.system_prompt.setStyleSheet(f"""
            QTextEdit{{
            margin: 8px;
            padding: 8px;
            border: 1px solid;
            border-color: {app_data.get('setting.theme.highlight_color', UIColors.highlight_color)};
            border-radius: 10px;
            background: {app_data.get('setting.theme.input_field_color', UIColors.input_field_color)};
            }}
            """
                                         )
        splitter.addWidget(self.system_prompt)

        # --  Chat view  --
        self.chat_view = ChatViewWidget()
        self.chat_view.setStyleSheet(f"""QWidget{{
            padding: 8px;
            border-radius: 10px;
            background: {app_data.get('setting.theme.input_field_color', UIColors.input_field_color)}
            }}
            """
                                     )
        splitter.addWidget(self.chat_view)

        # --   Input  ---
        self.input_field = ChatTextInputWidget()
        self.input_field.setStyleSheet(f"""
            QTextEdit{{
            margin: 8px;
            padding: 8px;
            border: 1px solid;
            border-color: {app_data.get('setting.theme.highlight_color', UIColors.highlight_color)};
            border-radius: 10px;
            background: {app_data.get('setting.theme.input_field_color', UIColors.input_field_color)}}}""")

        self._apply_audio_chip_settings_from_qsettings()
        # Show/hide chip on toggle
        self.TTS_toggle.toggled.connect(self._on_tts_toggled)
        # Bubble speak requests (Regenerate) bubble up here
        self.chat_view.speak_requested.connect(self._speak_text)
        # start with current toggle state
        self._on_tts_toggled(self.TTS_toggle.isChecked())
        splitter.addWidget(self.input_field)

        splitter.setSizes([40, 3000, 40])

        # --  connections  --
        self.input_field.send_message.connect(self.send_message)

        self.get_model_list_worker = GetModelListWorker()
        self.get_model_list_worker.start()
        self.get_model_list_worker.completed_llm_call.connect(self.got_model_list)

        self.settings.providers_changed.connect(lambda _: self._rebuild_model_selection())

    def send_message(self, message: str):
        data = self.model_selection.currentData()
        if not data:
            QMessageBox.warning(self, "No model selected", "Please pick a model.")
            return

        # === Build messages with latest system prompt ===
        system_text = self.system_prompt.toPlainText()
        history = app_data.get("messages", []) or []
        # Remove any previous system messages from history
        history_wo_system = [m for m in history if m.get("role") != "system"]

        # New conversation structure: system prompt first, then history, then the new user message
        messages = [{"role": "system", "content": system_text}] + history_wo_system
        messages.append({"role": "user", "content": message})

        # Show the user's message immediately
        self.chat_view.add_message(message, True)
        self.input_field.setEnabled(False)

        # === Route by provider type ===
        if data.get("source") == "ollama":
            from app.api.llm_api import SendMessageWorker
            selected_model = data.get("model") or self.model_selection.currentText()
            self.allama_request_worker = SendMessageWorker(messages, selected_model)
            self.allama_request_worker.completed_llm_call.connect(self.got_llm_response)
            self.allama_request_worker.failed_llm_call.connect(self._on_llm_error)
            self.allama_request_worker.start()

        elif data.get("source") == "remote":
            from app.core.settings_manager import SettingsManager
            from app.api.llm_api import SendRemoteMessageWorker

            sm = SettingsManager(self)
            prov = sm.get_provider(data["provider_id"])
            if not prov:
                QMessageBox.warning(self, "Missing provider", "Provider settings not found.")
                self.input_field.setEnabled(True)
                return

            self.remote_worker = SendRemoteMessageWorker(
                messages=messages,
                provider_id=data["provider_id"],
                model=data["model"],
                api_key=prov.get("api_key", ""),
                base_url=prov.get("base_url") or None,
                options=None  # optional dict: {"temperature": 0.7, "max_tokens": 1024}
            )
            self.remote_worker.completed_llm_call.connect(self.got_llm_response)
            self.remote_worker.failed_llm_call.connect(self._on_llm_error)
            self.remote_worker.start()

    def _on_llm_error(self, err: str):
        self.chat_view.add_message(f"[Error]\n{err}", False)
        self.input_field.setEnabled(True)

    def got_llm_response(self, result: str):
        """Handle a completed LLM call (local or remote)."""
        history = app_data.get("messages", []) or []
        history.append({"role": "assistant", "content": result})
        app_data.set("messages", history)

        self.chat_view.add_message(result, False)
        self.input_field.setEnabled(True)
        if self.TTS_toggle.isChecked():
            self._speak_text(result)

    def got_model_list(self, models: list):
        # Save Ollama models and rebuild full selector (local + remote)
        self._ollama_models = models or []
        self._rebuild_model_selection()

    def _rebuild_model_selection(self):
        prev_data = self.model_selection.currentData()
        self.model_selection.clear()

        def add_section(label: str):
            self.model_selection.addItem(f"— {label} —")
            idx = self.model_selection.count() - 1
            self.model_selection.model().item(idx).setEnabled(False)

        # Local (Ollama)
        add_section("Local (Ollama)")
        for m in self._ollama_models:
            self.model_selection.addItem(f"Ollama • {m}", {"source": "ollama", "model": m})

        # Remote providers (manual + auto-fetched union)
        from app.core.settings_manager import SettingsManager
        sm = SettingsManager(self)
        providers = sm.get_providers()

        # Kick off auto-fetch once
        if not self._remote_models_worker_started and providers:
            from app.api.llm_api import GetRemoteModelsWorker
            self._remote_models_worker_started = True
            self._remote_worker_models = GetRemoteModelsWorker(providers)
            self._remote_worker_models.completed_llm_call.connect(self._on_remote_models)
            self._remote_worker_models.failed_llm_call.connect(self._on_llm_error)
            self._remote_worker_models.start()

        for p in providers:
            label = p.get("name", p.get("id", "provider"))
            pid = (p.get("id") or "").lower()
            add_section(label)

            # union: models saved manually in Auth tab + auto-fetched for that key
            manual = p.get("models") or []
            auto = self._remote_models.get(pid, []) or []

            # Prefer unique order: manual first, then any new auto
            seen = set()
            merged = []
            for m in manual + auto:
                if m and m not in seen:
                    seen.add(m)
                    merged.append(m)

            if not merged:
                # Optional nice UX
                self.model_selection.addItem("(no models found)", None)
                self.model_selection.model().item(self.model_selection.count() - 1).setEnabled(False)
            else:
                for m in merged:
                    self.model_selection.addItem(
                        f"{label} • {m}",
                        {"source": "remote", "provider_id": pid, "provider_name": label, "model": m}
                    )

        # restore previous selection if possible
        if prev_data is not None:
            for i in range(self.model_selection.count()):
                if self.model_selection.itemData(i) == prev_data:
                    self.model_selection.setCurrentIndex(i)
                    break

    def _on_remote_models(self, mapping: dict):
        """
        mapping: { provider_id: [model_id, ...], ... }
        """
        self._remote_models = mapping or {}
        # Rebuild to include newly discovered models
        self._rebuild_model_selection()

    def _on_tts_toggled(self, enabled: bool):
        self.chat_view.set_tts_enabled(bool(enabled))
        self.TTS_toggle.toggled.connect(lambda _: self._apply_audio_chip_settings_from_qsettings())

    def _apply_audio_chip_settings_from_qsettings(self):
        """Read visualizer settings from QSettings and apply to the chat audio chip."""
        sm = SettingsManager(self)
        fg = sm.value("speech/vis_fg", "#8be9fd")
        bg = sm.value("speech/vis_bg", "#1e1f29")
        bins = int(sm.value("speech/bins_per_side", 16))
        gap = int(sm.value("speech/bin_gap_px", 2))
        smoothing = float(sm.value("speech/smoothing", 0.45))
        fade_decay = float(sm.value("speech/fade_decay", 0.88))

        try:
            self.chat_view.audio_chip.set_colors(fg, bg)
            self.chat_view.audio_chip.set_effect(
                "symmetric_bins",
                bins_per_side=bins,
                bin_gap_px=gap,
                smoothing=smoothing,
                fade_decay=fade_decay
            )
        except Exception as e:
            print(f"[ChatTab] Failed to apply audio chip settings: {e}")

    def _speak_text(self, text: str):
        """Kick off TTS for given text using OptionsDialog's worker and feed the chat audio chip."""
        if not text or not self.TTS_toggle.isChecked():
            return

        # Read server & voice from settings (same keys used in OptionsDialog)
        sm = SettingsManager(self)
        url = sm.value("speech/voice_server_url", "http://127.0.0.1:8008")
        voice = sm.value("speech/voice", "")

        # If no voice list/selection stored, we still try; your TTS server may use a default.
        try:
            self._tts_worker = GenerateAudioWorker(url, voice, text)
            self._tts_worker.audio_ready.connect(self._on_tts_audio_ready)
            self._tts_worker.complete.connect(self._on_tts_complete)
            self._tts_worker.start()
            self._last_spoken_text = text
        except Exception as e:
            self.chat_view.audio_chip.stop(hard=True)
            self.chat_view.audio_chip.setVisible(self.TTS_toggle.isChecked())
            print(f"[ChatTab] TTS worker error: {e}")

    def _on_tts_audio_ready(self, wav_bytes: bytes):
        """Parse the WAV and feed the chat's audio chip, then auto-play."""
        import io, wave, numpy as np
        try:
            with wave.open(io.BytesIO(wav_bytes), 'rb') as w:
                sr = w.getframerate()
                ch = w.getnchannels()
                sw = w.getsampwidth()
                nframes = w.getnframes()
                raw = w.readframes(nframes)

            if sw == 2:
                self.chat_view.audio_chip.set_wave(raw, sample_rate=sr, channels=ch)
            elif sw == 4:
                try:
                    arr = np.frombuffer(raw, dtype="<f4")
                    if ch > 1:
                        arr = arr.reshape(-1, ch)
                    arr = np.clip(arr, -1.0, 1.0)
                except Exception:
                    i32 = np.frombuffer(raw, dtype="<i4")
                    if ch > 1:
                        i32 = i32.reshape(-1, ch)
                    arr = np.clip(i32.astype(np.float32) / 2147483647.0, -1.0, 1.0)
                self.chat_view.audio_chip.set_wave(arr.astype(np.float32, copy=False), sample_rate=sr, channels=ch)
            else:
                # Fallback normalize
                dtype = {1: np.int8, 2: np.int16, 3: np.int32, 4: np.int32}.get(sw, np.int16)
                i_arr = np.frombuffer(raw, dtype=dtype)
                if sw == 3:  # 24-bit packed in 32
                    i_arr = (i_arr >> 8)
                if ch > 1:
                    i_arr = i_arr.reshape(-1, ch)
                max_int = float(np.iinfo(np.int32 if sw >= 3 else dtype).max)
                arr = np.clip(i_arr.astype(np.float32) / max_int, -1.0, 1.0)
                self.chat_view.audio_chip.set_wave(arr, sample_rate=sr, channels=ch)

            # reveal chip (if hidden by toggle) and play
            self.chat_view.audio_chip.setVisible(self.TTS_toggle.isChecked())
            self.chat_view.audio_chip.play()
        except Exception as e:
            print(f"[ChatTab] Failed to parse/play WAV: {e}")

    def _on_tts_complete(self, message: str, success: bool):
        if not success:
            self.chat_view.audio_chip.stop(hard=True)