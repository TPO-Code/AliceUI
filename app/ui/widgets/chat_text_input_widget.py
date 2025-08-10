from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QTextEdit


class ChatTextInputWidget(QTextEdit):
    send_message = Signal(str)

    def keyPressEvent(self, event):

        if event.key() == Qt.Key.Key_Return and event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            text = self.toPlainText()
            if text:
                self.send_message.emit(text)
                self.clear()
            event.accept()
        else:
            super().keyPressEvent(event)