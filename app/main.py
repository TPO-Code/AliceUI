
import sys

from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow
from PySide6.QtCore import QCoreApplication
import app.resources_rc
QCoreApplication.setOrganizationName("TPO-Code")
QCoreApplication.setOrganizationDomain("tpo-code.dev")  # optional
QCoreApplication.setApplicationName("AliceUI")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


