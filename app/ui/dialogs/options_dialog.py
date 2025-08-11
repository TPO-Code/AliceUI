# app/ui/dialogs/options_dialog.py
from PySide6.QtWidgets import QDialog, QVBoxLayout, QTabWidget, QWidget
from PySide6.QtCore import QByteArray

from app.core.settings_manager import SettingsManager
from app.ui.dialogs.auth_settings_tab import AuthTabWidget
from app.ui.dialogs.speech_settings_tab import SpeechSettingsTabWidget


class OptionsDialog(QDialog):
    """
    Thin shell: hosts tabs and persists window geometry only.
    Each tab handles its own live persistence via SettingsManager.
    """
    def __init__(self):
        super().__init__()
        self.settings = SettingsManager(self)

        layout = QVBoxLayout(self)
        self.tab_widget = QTabWidget()
        layout.addWidget(self.tab_widget)

        # Tabs
        self._create_auth_tab()
        self._create_tool_server_tab()
        self._create_speech_tab()

        self._load_geometry()

    # ---- tabs ----
    def _create_auth_tab(self):
        self.auth_tab = AuthTabWidget(self.settings, self)
        self.tab_widget.addTab(self.auth_tab, "Auth")

    def _create_tool_server_tab(self):
        tool_server_tab = QWidget()
        self.tab_widget.addTab(tool_server_tab, "Tool server")

    def _create_speech_tab(self):
        self.speech_tab = SpeechSettingsTabWidget(self)
        self.tab_widget.addTab(self.speech_tab, "Speech")

    # ---- geometry only ----
    def _load_geometry(self):
        geo: QByteArray = self.settings.value("dialogs/options/geometry", QByteArray(), type=QByteArray)
        if not geo.isEmpty():
            self.restoreGeometry(geo)

    def _save_geometry(self):
        self.settings.setValue("dialogs/options/geometry", self.saveGeometry())
        self.settings.sync()

    # Persist on close
    def accept(self):
        self._save_geometry()
        super().accept()

    def reject(self):
        self._save_geometry()
        super().reject()

    def closeEvent(self, e):
        self._save_geometry()
        super().closeEvent(e)
