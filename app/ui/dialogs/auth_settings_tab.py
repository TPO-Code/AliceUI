from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout, QGroupBox, QHBoxLayout, QComboBox, QLabel, QLineEdit, QPushButton, \
    QListWidget, QTableWidget, QAbstractItemView, QHeaderView, QListWidgetItem, QMessageBox, QTableWidgetItem, QWidget, \
    QCheckBox

from app.api.llm_api import GetRemoteModelsWorker
from app.core.settings_manager import SettingsManager


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