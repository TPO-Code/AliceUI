from __future__ import annotations
import json
from typing import List, Dict, Any
from PySide6.QtCore import QObject, Signal, QSettings

ORG = "TPO-Code"
APP = "AliceUI"

class SettingsManager(QObject):
    providers_changed = Signal(list)  # list[dict]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._s = QSettings(ORG, APP)

    # ---- Providers ----
    def get_providers(self) -> List[Dict[str, Any]]:
        raw = self._s.value("ai/providers", "")
        if not raw:
            return []
        try:
            return json.loads(raw)
        except Exception:
            return []

    def save_providers(self, providers: List[Dict[str, Any]]) -> None:
        self._s.setValue("ai/providers", json.dumps(providers))
        self.providers_changed.emit(providers)

    def get_provider(self, provider_id: str) -> dict | None:
        """
        Retrieve a single provider dictionary by its 'id'.
        Returns None if not found.
        """
        for p in self.get_providers():
            if p.get("id") == provider_id:
                return p
        return None

    # ---- Passthroughs so callers can use this like QSettings ----
    def value(self, key: str, default=None, type=None):
        if type is None:
            return self._s.value(key, default)
        return self._s.value(key, default, type=type)

    def setValue(self, key: str, value):
        self._s.setValue(key, value)

    def sync(self):
        self._s.sync()
