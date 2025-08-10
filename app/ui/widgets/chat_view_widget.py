from PySide6.QtCore import Qt, QTimer, QAbstractAnimation, QPropertyAnimation, QEasingCurve
from PySide6.QtWidgets import QVBoxLayout, QWidget, QScrollArea, QHBoxLayout, QSizePolicy
from app.data.colors import UIColors
from app.data.app_data import app_data
from app.ui.widgets.chat_bubble_widget import UserChatBubbleWidget, AssistantChatBubbleWidget


class ChatViewWidget(QWidget):

    def __init__(self):
        super().__init__()
        self._debounce = {}
        self.scroll_animation = None
        self.setMinimumSize(0, 0)
        self.setWindowTitle("Chat")

        # Track whether the user is near the bottom (auto-stick mode)
        self._stick_to_bottom = True

        self.pending_bubbles = []
        self.chat_area = QWidget()
        self.chat_layout = QVBoxLayout()
        self.chat_layout.addStretch()
        self.chat_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.chat_area.setLayout(self.chat_layout)

        self.scroll = QScrollArea()
        self.scroll.setStyleSheet(f"""
            QScrollArea{{margin: 8px;
            border: 1px solid;
            border-color: {app_data.get('setting.theme.highlight_color', UIColors.highlight_color)};
            border-radius: 10px;
            background: {app_data.get('setting.theme.input_field_color', UIColors.input_field_color)};
            }}
        """)
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.chat_area)

        # 👇 Watch user scroll + range changes to maintain stickiness
        sb = self.scroll.verticalScrollBar()
        sb.valueChanged.connect(self._on_scroll_value_changed)
        sb.rangeChanged.connect(self._on_scroll_range_changed)

        main_layout = QVBoxLayout()
        main_layout.addWidget(self.scroll)
        self.setLayout(main_layout)

    def _on_scroll_value_changed(self, value):
        # Consider "at bottom" if within a few px
        sb = self.scroll.verticalScrollBar()
        self._stick_to_bottom = (sb.maximum() - value) <= 5

    def _on_scroll_range_changed(self, _min, _max):
        # If we were at bottom before the range changed, snap to the new max
        if self._stick_to_bottom:
            QTimer.singleShot(0, self._jump_to_bottom)

    def _jump_to_bottom(self):
        # Immediate snap beats animations when content keeps growing
        sb = self.scroll.verticalScrollBar()
        sb.setValue(sb.maximum())

    def add_message(self, text: str, is_user: bool):
        # Update sticky flag based on current position
        sb = self.scroll.verticalScrollBar()
        self._stick_to_bottom = (sb.maximum() - sb.value()) <= 5

        bubble = UserChatBubbleWidget(text) if is_user else AssistantChatBubbleWidget(text)

        self.pending_bubbles.append(bubble)
        bubble.rendered.connect(self._add_and_size_bubble)

    def _add_and_size_bubble(self, bubble, is_user):
        container = QWidget()
        container_layout = QHBoxLayout(container)
        container_layout.setContentsMargins(10, 5, 10, 5)

        if is_user:
            container_layout.addStretch(1)
            container_layout.addWidget(bubble, 0, Qt.AlignRight)
        else:
            container_layout.addWidget(bubble, 0, Qt.AlignLeft)
            container_layout.addStretch(1)

        container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, container)

        # Connect both width-adjust & sticky scroll to bubble geometry changes
        viewer = getattr(bubble, "user_message", None) or getattr(bubble, "llm_text", None)
        if viewer:
            # Only maintain sticky scroll on geometry changes; don't re-run width sizing here
            viewer.geometry_changed.connect(self._maybe_stick_after_geometry)

        self._trigger_bubble_width_adjustment(bubble)

        # If we were already at bottom, snap after insertion
        if self._stick_to_bottom:
            QTimer.singleShot(0, self._jump_to_bottom)

        if bubble in self.pending_bubbles:
            self.pending_bubbles.remove(bubble)

    def _maybe_stick_after_geometry(self):
        if self._stick_to_bottom:
            QTimer.singleShot(0, self._jump_to_bottom)

    def _on_bubble_geometry_changed(self, bubble):
        if getattr(bubble, "_sizing", False):
            return
        t = self._debounce.get(bubble)
        if t:
            t.stop()
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda: (self._trigger_bubble_width_adjustment(bubble),
                                       self._stick_to_bottom and QTimer.singleShot(0, self._jump_to_bottom)))
        timer.start(40)  # 40–80ms is plenty
        self._debounce[bubble] = timer

    def _trigger_bubble_width_adjustment(self, bubble):
        if getattr(bubble, "_sizing", False):
            return
        viewport_width = self.scroll.viewport().width() or 800
        side_margins = 20
        max_width = max(120, int(viewport_width * 0.95) - side_margins)
        if hasattr(bubble, 'adjust_width'):
            bubble.adjust_width(max_width)

    # Keep animation method for manual calls if you want a pretty scroll,
    # but we no longer rely on it for auto-stick behavior.
    def on_scroll_animation_finished(self):
        self.scroll_animation = None

    def scroll_to_bottom(self):
        if self.scroll_animation and self.scroll_animation.state() == QAbstractAnimation.State.Running:
            return
        target_value = self.scroll.verticalScrollBar().maximum()
        if self.scroll.verticalScrollBar().value() == target_value:
            return
        self.scroll_animation = QPropertyAnimation(self.scroll.verticalScrollBar(), b"value")
        self.scroll_animation.setDuration(400)
        self.scroll_animation.setStartValue(self.scroll.verticalScrollBar().value())
        self.scroll_animation.setEndValue(target_value)
        self.scroll_animation.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self.scroll_animation.finished.connect(self.on_scroll_animation_finished)
        self.scroll_animation.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(50, self._update_all_bubble_widths)

    def _update_all_bubble_widths(self):
        for i in range(self.chat_layout.count() - 1):
            item = self.chat_layout.itemAt(i)
            if item and item.widget():
                container = item.widget()
                bubble = container.findChild(UserChatBubbleWidget) or container.findChild(AssistantChatBubbleWidget)
                if bubble:
                    self._trigger_bubble_width_adjustment(bubble)
        # Stay stuck after a resize if we were at bottom
        if self._stick_to_bottom:
            QTimer.singleShot(0, self._jump_to_bottom)