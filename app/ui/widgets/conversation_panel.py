# app/ui/widgets/conversation_panel.py
from __future__ import annotations
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLineEdit, QMessageBox, QLabel
)

from app.core.conversation_manager import ConversationMeta

class ConversationPanel(QWidget):
    new_requested = Signal()
    rename_requested = Signal(str)      # conv_id
    delete_requested = Signal(str)      # conv_id
    selected_changed = Signal(str)      # conv_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items_by_id = {}
        self.list = QListWidget()
        self.list.itemSelectionChanged.connect(self._emit_selection)

        header = QLabel("Conversations")
        header.setStyleSheet("font-weight:600;")

        btn_row = QHBoxLayout()
        self.btn_new = QPushButton("➕ New")
        self.btn_ren = QPushButton("✏️ Rename")
        self.btn_del = QPushButton("🗑️ Delete")
        for b in (self.btn_new, self.btn_ren, self.btn_del):
            b.setCursor(Qt.PointingHandCursor)
        self.btn_new.clicked.connect(self.new_requested.emit)
        self.btn_ren.clicked.connect(self._rename_clicked)
        self.btn_del.clicked.connect(self._delete_clicked)

        btn_row.addWidget(self.btn_new)
        btn_row.addWidget(self.btn_ren)
        btn_row.addWidget(self.btn_del)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8,8,8,8)
        layout.setSpacing(6)
        layout.addWidget(header)
        layout.addLayout(btn_row)
        layout.addWidget(self.list, 1)

        self.setMinimumWidth(220)

    # ------- API -------
    def populate(self, metas: list[ConversationMeta], current_id: str | None):
        self.list.clear()
        self._items_by_id.clear()
        for m in metas:
            txt = f"{m.title}"
            if m.is_new:
                txt += "  (new)"
            it = QListWidgetItem(txt)
            it.setData(Qt.UserRole, m.id)
            self.list.addItem(it)
            self._items_by_id[m.id] = it
        if current_id and current_id in self._items_by_id:
            self.list.setCurrentItem(self._items_by_id[current_id])
        elif self.list.count():
            self.list.setCurrentRow(0)

    def current_id(self) -> str | None:
        it = self.list.currentItem()
        return it.data(Qt.UserRole) if it else None

    # ------- Internals -------
    def _emit_selection(self):
        cid = self.current_id()
        if cid:
            self.selected_changed.emit(cid)

    def _rename_clicked(self):
        cid = self.current_id()
        if cid:
            self.rename_requested.emit(cid)

    def _delete_clicked(self):
        cid = self.current_id()
        if cid:
            self.delete_requested.emit(cid)
