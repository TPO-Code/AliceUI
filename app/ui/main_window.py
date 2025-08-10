from PySide6.QtCore import QEvent
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import QMainWindow, QMenu, QTabWidget

from app.data.app_data import app_data
from app.data.colors import UIColors
from app.ui.dialogs.options_dialog import OptionsDialog
from app.ui.tabs.chat_tab import ChatTab


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()
        self.options_dialog = None

        self.setStyleSheet(f"""
            QMainWindow{{
            background: {app_data.get('setting.theme.main_color', UIColors.main_color)};
            }}
            QTabWidget{{
            background: {app_data.get('setting.theme.main_color', UIColors.main_color)};
            }}
            """
                           )
        self.setWindowTitle("Window")
        self.setGeometry(100, 100, 800, 600)
        self.create_menu()

        # -- Setup Tabs --
        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(False)
        self.setCentralWidget(self.tabs)

        # -- Create and add Chat Tab --
        chat_tab = ChatTab()
        self.tabs.addTab(chat_tab, "Chat")

    def create_menu(self):
        menu = self.menuBar()

        # -- File menu --
        file_menu = QMenu("File", self)
        menu.addMenu(file_menu)
        # actions

        options_action = QAction("Options", self)
        exit_action = QAction("Exit", self)
        file_menu.addAction(options_action)
        file_menu.addAction(exit_action)
        # connections
        options_action.triggered.connect(self.open_options)
        exit_action.triggered.connect(self.close)

        # -- View menu --
        view_menu = QMenu("View", self)
        menu.addMenu(view_menu)
        # actions
        # connections

        # -- About menu --
        about_menu = QMenu("About", self)
        menu.addMenu(about_menu)
        # actions
        # connections

    def closeEvent(self, event: QCloseEvent):
        app_data.save_application_data()
        event.accept()

    def open_options(self):
        if not self.options_dialog:
            self.options_dialog = OptionsDialog()

        self.options_dialog.show()
        #event.accept()
        dlg.finished.connect(lambda _: self.chat_tab._apply_audio_chip_settings_from_qsettings())
        dlg.exec()

