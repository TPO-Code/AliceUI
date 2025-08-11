# app/ui/tabs/chat_tab.py
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Slot, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QComboBox, QSplitter, QTextEdit, QHBoxLayout, QCheckBox,
    QMessageBox, QLabel, QPushButton, QInputDialog, QLineEdit
)

from app.api.llm_api import GetModelListWorker
from app.api.speech_api import TranscribeWorker, MicVADWorker, MicRecorderWorker, GenerateAudioWorker
from app.core.settings_manager import SettingsManager
from app.data.colors import UIColors
from app.ui.widgets.chat_text_input_widget import ChatTextInputWidget
from app.ui.widgets.chat_view_widget import ChatViewWidget

# >>> conversations
from app.core.conversation_manager import ConversationManager
from app.ui.widgets.conversation_panel import ConversationPanel


class ChatTab(QWidget):
    def __init__(self):
        super().__init__()
        self._stt_queue = []
        self._stt_workers_pool = []
        self._last_spoken_text = ""
        self._tts_worker = None

        self.settings = SettingsManager(self)
        self._remote_models: dict[str, list[str]] = {}
        self._remote_models_worker_started = False

        self._inference_active = False
        self._stt_vad_worker = None
        self._stt_push_worker = None
        self._stt_transcribe_worker = None
        self._vad_block_timer = QTimer(self)
        self._vad_block_timer.setInterval(120)
        self._vad_block_timer.timeout.connect(self._update_block)

        # >>> conversations: init manager + password dialog
        self.convman = ConversationManager(data_dir=os.path.expanduser("~/.aliceui"))
        try:
            if not self.convman.has_password():
                pwd, ok = QInputDialog.getText(
                    self,
                    "Set Master Password",
                    "Create a master password:",
                    QLineEdit.EchoMode.Password
                )
                if not ok or not pwd:
                    raise RuntimeError("Master password required to proceed.")
                self.convman.set_master_password(pwd)
            else:
                pwd, ok = QInputDialog.getText(
                    self,
                    "Unlock Conversations",
                    "Enter master password:",
                    QLineEdit.EchoMode.Password
                )
                if not ok or not pwd:
                    raise RuntimeError("Master password required to proceed.")
                self.convman.set_master_password(pwd)
        except Exception as e:
            QMessageBox.critical(self, "Encryption", f"Failed to unlock storage:\n{e}")
            raise

        # >>> conversations: load latest or create
        meta, payload = self.convman.load_or_create_latest()
        self._current_conv_id = meta.id

        # =======================
        # UI LAYOUT
        # =======================
        main_layout = QVBoxLayout()
        self.setLayout(main_layout)

        # --  Model selection and options  --
        options_layout = QHBoxLayout()
        self.model_selection = QComboBox()
        self.TTS_toggle = QCheckBox("Text To Speech")
        main_layout.addLayout(options_layout)
        options_layout.addWidget(self.model_selection)
        options_layout.addWidget(self.TTS_toggle)

        # --- Horizontal splitter: LEFT = conversation panel, RIGHT = your existing vertical stack
        hr = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(hr)

        # LEFT: collapsible conversation panel
        self.conv_panel = ConversationPanel()
        hr.addWidget(self.conv_panel)
        hr.setCollapsible(0, True)
        hr.setStretchFactor(0, 0)

        # RIGHT: vertical splitter (system prompt, chat view, input)
        splitter = QSplitter(Qt.Orientation.Vertical)
        hr.addWidget(splitter)
        hr.setStretchFactor(1, 1)

        # --  System prompt  --
        self.system_prompt = QTextEdit()
        self.system_prompt.setPlaceholderText("System Prompt")
        self.system_prompt.setStyleSheet(f"""
            QTextEdit{{
            margin: 8px;
            padding: 8px;
            border: 1px solid;
            border-color: {UIColors.highlight_color};
            border-radius: 10px;
            background: {UIColors.input_field_color};
            }}
            """
                                         )
        splitter.addWidget(self.system_prompt)

        # --  Chat view  --
        self.chat_view = ChatViewWidget()
        self.chat_view.setStyleSheet(f"""QWidget{{
            padding: 8px;
            border-radius: 10px;
            background: {UIColors.input_field_color}
            }}
            """
                                     )
        splitter.addWidget(self.chat_view)

        stt_row = QHBoxLayout()
        self.stt_mode = QComboBox()
        self.stt_mode.addItems(["Off", "Push to talk", "Natural"])
        self.ptt_btn = QPushButton("🎙️ Talk")
        self.ptt_btn.setCheckable(True)
        self.ptt_btn.setEnabled(False)  # enabled only when mode != Off
        stt_row.addWidget(QLabel("Speech input:"))
        stt_row.addWidget(self.stt_mode)
        stt_row.addStretch(1)
        stt_row.addWidget(self.ptt_btn)

        # Insert speech row above the splitter (keeps your original layout intent)
        main_layout.insertLayout(1, stt_row)

        # --   Input  ---
        self.input_field = ChatTextInputWidget()
        self.input_field.setStyleSheet(f"""
            QTextEdit{{
            margin: 8px;
            padding: 8px;
            border: 1px solid;
            border-color: {UIColors.highlight_color};
            border-radius: 10px;
            background: {UIColors.input_field_color}}}""")
        splitter.addWidget(self.input_field)
        splitter.setSizes([40, 3000, 40])

        # --  connections  --
        self.chat_view.audio_chip.playing_changed.connect(self._on_tts_playing_changed)
        self.input_field.send_message.connect(self.send_message)

        self.get_model_list_worker = GetModelListWorker()
        self.get_model_list_worker.start()
        self.get_model_list_worker.completed_llm_call.connect(self.got_model_list)

        self.settings.providers_changed.connect(lambda _: self._rebuild_model_selection())
        self.stt_mode.currentIndexChanged.connect(self._on_stt_mode_changed)
        self.ptt_btn.toggled.connect(self._on_ptt_toggled)

        # TTS toggle & audio chip setup
        self._apply_audio_chip_settings_from_qsettings()
        self.TTS_toggle.toggled.connect(self._on_tts_toggled)
        self.chat_view.speak_requested.connect(self._speak_text)
        self._on_tts_toggled(self.TTS_toggle.isChecked())

        # >>> conversations: hydrate UI with loaded payload
        self._hydrate_from_payload(payload)
        self._refresh_conv_panel(select_id=self._current_conv_id)

        self.conv_panel.selected_changed.connect(self._on_conv_selected)
        self.conv_panel.new_requested.connect(self._on_new_conv)
        self.conv_panel.rename_requested.connect(self._on_rename_conv)
        self.conv_panel.delete_requested.connect(self._on_delete_conv)
        # Save system prompt when it loses focus
        self.system_prompt.focusOutEvent = self._wrap_focus_out(self.system_prompt.focusOutEvent)

    # -------------------------
    # Conversations: helpers
    # -------------------------
    def _wrap_focus_out(self, orig):
        def _handler(ev):
            try:
                self.convman.set_system(self._current_conv_id, self.system_prompt.toPlainText())
            except Exception as e:
                print("[ChatTab] Failed to save system:", e)
            return orig(ev)
        return _handler

    def _hydrate_from_payload(self, payload: dict):
        msgs = payload.get("messages", []) or []
        self.system_prompt.setPlainText(payload.get("system", ""))

        # Ordered batch: pre-create slots, then queue each message into its slot
        self.chat_view.begin_ordered_batch(len(msgs))
        for i, m in enumerate(msgs):
            self.chat_view.add_message_ordered(
                m.get("content", ""),
                is_user=(m.get("role") == "user"),
                index=i
            )
        self.chat_view.end_ordered_batch()

    def _clear_chat_view_messages(self):
        # Kill any queued bubble-adds
        try:
            self.chat_view.pending_bubbles.clear()
        except Exception:
            pass
        layout = self.chat_view.chat_layout
        # Remove everything
        for i in reversed(range(layout.count())):
            item = layout.itemAt(i)
            if item and item.widget():
                w = item.widget()
                layout.removeWidget(w)
                w.deleteLater()
            else:
                layout.removeItem(item)
        # Re-add stretch
        layout.addStretch()

    def _refresh_conv_panel(self, select_id: str | None):
        try:
            metas = self.convman.list()
            self.conv_panel.populate(metas, select_id)
        except Exception as e:
            print("[ChatTab] panel refresh failed:", e)

    @Slot(str)
    def _on_conv_selected(self, conv_id: str):
        # Always (re)load, even if it's already the current id
        if not conv_id:
            return
        try:
            payload = self.convman.load(conv_id)
            self._current_conv_id = conv_id
        except Exception as e:
            QMessageBox.critical(self, "Conversation", f"Failed to load conversation:\n{e}")
            return
        self._hydrate_from_payload(payload)

    @Slot()
    def _on_new_conv(self):
        try:
            current = self.convman.load(self._current_conv_id)
            is_new = len([m for m in current.get("messages", []) if m.get("role") in ("user", "assistant")]) == 0
            if is_new:
                self.convman.replace_messages(self._current_conv_id, [])
                self.system_prompt.clear()
                self._hydrate_from_payload({"system": "", "messages": []})
                return

            meta = self.convman.create("New conversation")
            self._current_conv_id = meta.id

            # Update the sidebar list (no implicit selection callback)
            self._refresh_conv_panel(select_id=meta.id)

            # Hydrate the empty convo exactly once
            payload = {"system": "", "messages": []}
            self._hydrate_from_payload(payload)
        except Exception as e:
            QMessageBox.critical(self, "Conversation", f"Could not create new conversation:\n{e}")

    @Slot(str)
    def _on_rename_conv(self, conv_id: str):
        title, ok = QInputDialog.getText(self, "Rename", "Title:")
        if not ok or not title.strip():
            return
        try:
            self.convman.rename(conv_id, title.strip())
            self._refresh_conv_panel(select_id=conv_id)
        except Exception as e:
            QMessageBox.critical(self, "Conversation", f"Rename failed:\n{e}")

    @Slot(str)
    def _on_delete_conv(self, conv_id: str):
        if QMessageBox.question(self, "Delete", "Delete this conversation? This cannot be undone.") != QMessageBox.Yes:
            return
        try:
            self.convman.delete(conv_id)
            metas = self.convman.list()
            if metas:
                self._current_conv_id = metas[0].id
                payload = self.convman.load(self._current_conv_id)
                self._hydrate_from_payload(payload)
                self._refresh_conv_panel(select_id=self._current_conv_id)
            else:
                meta = self.convman.create("New conversation")
                self._current_conv_id = meta.id
                self._hydrate_from_payload({"system": "", "messages": []})
                self._refresh_conv_panel(select_id=meta.id)
        except Exception as e:
            QMessageBox.critical(self, "Conversation", f"Delete failed:\n{e}")

    # -------------------------
    # Existing functionality
    # -------------------------
    def _update_block(self):
        worker = self._stt_vad_worker
        if worker is None:
            if self._vad_block_timer.isActive():
                self._vad_block_timer.stop()
            return

        playing = False
        try:
            chip = getattr(self.chat_view, "audio_chip", None)
            playing = bool(chip and chip.is_playing())
        except Exception:
            playing = False

        blocked = self._inference_active or playing
        try:
            worker.set_blocked(blocked)
        except Exception:
            if self._vad_block_timer.isActive():
                self._vad_block_timer.stop()

    def send_message(self, message: str):
        data = self.model_selection.currentData()
        if not data:
            QMessageBox.warning(self, "No model selected", "Please pick a model.")
            return

        # === Build messages with latest system prompt ===
        system_text = self.system_prompt.toPlainText()
        try:
            self.convman.set_system(self._current_conv_id, system_text)
            payload = self.convman.load(self._current_conv_id)
            history = [m for m in payload.get("messages", []) if m.get("role") != "system"]
        except Exception as e:
            QMessageBox.critical(self, "Conversation", f"Failed to read conversation: {e}")
            history = []

        # New conversation structure: system prompt first, then history, then the new user message
        messages = [{"role": "system", "content": system_text}] + history
        messages.append({"role": "user", "content": message})

        # Persist user's message immediately
        try:
            self.convman.append_message(self._current_conv_id, "user", message)
            #self._refresh_conv_panel(select_id=self._current_conv_id)
        except Exception as e:
            print("[ChatTab] warn: could not persist user msg:", e)

        # Show the user's message immediately
        self.chat_view.add_message(message, True)
        self.input_field.setEnabled(False)

        # Pause VAD during inference (both local and remote)
        self._inference_active = True

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
            self._inference_active = True
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
        self._inference_active = False
        self._maybe_send_next_queued()

    def got_llm_response(self, result: str):
        """Handle a completed LLM call (local or remote)."""
        try:
            self.convman.append_message(self._current_conv_id, "assistant", result)
            #self._refresh_conv_panel(select_id=self._current_conv_id)
        except Exception as e:
            print("[ChatTab] warn: could not persist assistant msg:", e)

        self.chat_view.add_message(result, False)
        self.input_field.setEnabled(True)
        if self.TTS_toggle.isChecked():
            self._speak_text(result)
        self._inference_active = False
        self._maybe_send_next_queued()

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
        for m in getattr(self, "_ollama_models", []):
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

            manual = p.get("models") or []
            auto = self._remote_models.get(pid, []) or []

            seen = set()
            merged = []
            for m in manual + auto:
                if m and m not in seen:
                    seen.add(m)
                    merged.append(m)

            if not merged:
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
        # Re-apply current chip params once when the toggle changes
        self._apply_audio_chip_settings_from_qsettings()

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
        # Try to flush anything that arrived during playback
        QTimer.singleShot(50, self._maybe_send_next_queued)

    def _on_stt_mode_changed(self, idx: int):
        mode = self.stt_mode.currentText()
        self.ptt_btn.setEnabled(mode == "Push to talk")

        # Stop push worker
        if self._stt_push_worker:
            try:
                self._stt_push_worker.stop_recording()
                self._stt_push_worker.quit()
                self._stt_push_worker.wait(1500)
            except Exception:
                pass
            self._stt_push_worker = None

        if self._stt_vad_worker:
            try:
                self._stt_vad_worker.stop_vad()
                self._stt_vad_worker.quit()
                self._stt_vad_worker.wait(1500)
            except Exception:
                pass
            self._stt_vad_worker = None

        if self._vad_block_timer.isActive():
            self._vad_block_timer.stop()

        if mode == "Natural":
            self._start_vad()

    def _on_ptt_toggled(self, pressed: bool):
        if self.stt_mode.currentText() != "Push to talk":
            self.ptt_btn.setChecked(False)
            return
        if pressed:
            self._start_push_record()
            self.ptt_btn.setText("⏺️ Recording…")
        else:
            self._stop_push_record()

    def _start_push_record(self):
        self._stt_push_worker = MicRecorderWorker(sr=16000, channels=1, parent=self)
        self._stt_push_worker.recorded.connect(self._transcribe_wav)
        self._stt_push_worker.error.connect(lambda e: (print("[PTT] error:", e), self.ptt_btn.setChecked(False)))
        self._stt_push_worker.start()

    def _stop_push_record(self):
        if self._stt_push_worker:
            try:
                self._stt_push_worker.stop_recording()
                self._stt_push_worker.quit()  # safe even if not started with exec()
                self._stt_push_worker.wait(1000)
            except Exception:
                pass
            self._stt_push_worker = None
        self.ptt_btn.setText("🎙️ Talk")

    def _start_vad(self):
        if self._stt_vad_worker is not None:
            return

        sm = SettingsManager(self)
        auto = bool(sm.value("speech/vad_auto", True))
        mult = float(sm.value("speech/vad_multiplier", 3.5))
        min_floor = float(sm.value("speech/vad_min_floor", 0.020))
        manual_thresh = float(sm.value("speech/vad_rms_thresh", 0.030))
        silence_ms = int(sm.value("speech/vad_silence_ms", 500))
        min_active_ms = int(sm.value("speech/vad_min_active_ms", 220))  # optional, default same as before
        noise_floor = float(sm.value("speech/vad_noise_floor", 0.010))  # set by your calibrator

        # compute trigger
        rms_thresh = max(min_floor, noise_floor * mult) if auto else manual_thresh

        self._stt_vad_worker = MicVADWorker(
            sr=16000,
            channels=1,
            rms_thresh=rms_thresh,
            min_active_ms=min_active_ms,
            silence_ms=silence_ms,
            parent=self
        )
        self._stt_vad_worker.segment.connect(self._transcribe_wav)
        self._stt_vad_worker.error.connect(lambda e: print("[VAD] error:", e))
        self._stt_vad_worker.finished.connect(self._on_vad_finished)

        self._stt_vad_worker.start()
        self._update_block()
        self._vad_block_timer.start()

    def _on_vad_finished(self):
        self._stt_vad_worker = None
        if self._vad_block_timer.isActive():
            self._vad_block_timer.stop()

    def _transcribe_wav(self, wav_bytes: bytes):
        sm = SettingsManager(self)
        base = sm.value("speech/stt_server_url", sm.value("speech/voice_server_url", "http://127.0.0.1:8008"))
        device = "cuda"

        worker = TranscribeWorker(base, wav_bytes, device=device)
        worker.finished.connect(self._on_stt_text)
        # pool management to prevent premature destruction
        worker.finished.connect(lambda *_: self._cleanup_stt_worker(worker))
        worker.finished.connect(worker.deleteLater)
        self._stt_workers_pool.append(worker)
        worker.start()

    def _cleanup_stt_worker(self, worker):
        try:
            self._stt_workers_pool.remove(worker)
        except ValueError:
            pass

    @Slot(str, bool)
    def _on_stt_text(self, text: str, ok: bool):
        if not ok:
            print("[STT] transcription error:", text)
            return

        text = (text or "").strip()
        if not text:
            return

        mode = self.stt_mode.currentText()

        if mode == "Natural":
            # If we’re busy (model thinking) or audio playing, queue it.
            playing = False
            try:
                playing = self.chat_view.audio_chip.is_playing()
            except Exception:
                playing = False

            if self._inference_active or playing:
                self._stt_queue.append(text)
                return

            # Send immediately
            self.send_message(text)
            # Make sure the input field doesn’t accumulate junk
            try:
                self.input_field.setPlainText("")
            except Exception:
                pass

        else:
            # Push-to-talk: paste into the input, do NOT auto-send
            try:
                cur = self.input_field.toPlainText()
                new_text = (cur + (" " if cur else "") + text).strip()
                self.input_field.setPlainText(new_text)
                self.input_field.setFocus()
            except Exception:
                pass

    def _maybe_send_next_queued(self):
        # Only auto-send in Natural mode
        if self.stt_mode.currentText() != "Natural":
            self._stt_queue.clear()
            return
        if self._inference_active:
            return
        if not self._stt_queue:
            return
        next_text = self._stt_queue.pop(0)
        # Fire it off
        self.send_message(next_text)

    def _on_tts_playing_changed(self, playing: bool):
        # Keep the “block VAD during playback” promise tight
        if self._stt_vad_worker:
            self._stt_vad_worker.set_blocked(bool(playing or self._inference_active))

        # If Natural mode and we just finished playback, allow the mic again
        if (self.stt_mode.currentText() == "Natural") and (not playing):
            # small debounce lets the room settle
            QTimer.singleShot(80, self._update_block)
