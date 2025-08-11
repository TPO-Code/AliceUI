from PySide6.QtCore import Qt, QTimer, QAbstractAnimation, QPropertyAnimation, QEasingCurve, Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget, QScrollArea, QHBoxLayout, QSizePolicy
from app.data.colors import UIColors
from app.ui.widgets.AudioWaveWidget import AudioWaveWidget
from app.ui.widgets.chat_bubble_widget import UserChatBubbleWidget, AssistantChatBubbleWidget


class ChatViewWidget(QWidget):
    speak_requested = Signal(str)

    def __init__(self):
        super().__init__()
        self._debounce = {}
        self.scroll_animation = None
        self.setMinimumSize(0, 0)
        self.setWindowTitle("Chat")

        # Track whether the user is near the bottom (auto-stick mode)
        self._stick_to_bottom = True

        # Ordered-batch rendering (for hydration)
        self._ordered_active = False
        self._ordered_slots = []          # list[QWidget] slot containers in order
        self._ordered_expected = 0        # how many bubbles we expect in this batch
        self._ordered_inserted = 0        # how many have landed

        # Pending bubbles whose render signal hasn't fired yet
        self.pending_bubbles = []

        # Scroll area + chat contents
        self.chat_area = QWidget()
        self.chat_layout = QVBoxLayout()
        self.chat_layout.addStretch()
        self.chat_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.chat_area.setLayout(self.chat_layout)

        self.scroll = QScrollArea()
        self.scroll.setStyleSheet(f"""
            QScrollArea{{margin: 8px;
            border: 1px solid;
            border-color: {UIColors.highlight_color};
            border-radius: 10px;
            background: {UIColors.input_field_color};
            }}
        """)
        self.scroll.setWidgetResizable(True)
        self.scroll.setWidget(self.chat_area)

        # 👇 Watch user scroll + range changes to maintain stickiness
        sb = self.scroll.verticalScrollBar()
        sb.valueChanged.connect(self._on_scroll_value_changed)
        sb.rangeChanged.connect(self._on_scroll_range_changed)

        # TTS visualizer
        self._tts_enabled = False
        self.audio_chip = AudioWaveWidget()
        self.audio_chip.set_compact(22, show_buttons=True)
        self.audio_chip.set_colors("#8be9fd", "#1e1f29")
        self.audio_chip.setVisible(False)

        main_layout = QVBoxLayout()
        main_layout.addWidget(self.scroll)
        main_layout.addWidget(self.audio_chip)  # chip sits under chat, above input (input lives in ChatTab)
        self.setLayout(main_layout)

    # ---------------------------
    # Public API (live messages)
    # ---------------------------
    def add_message(self, text: str, is_user: bool):
        """
        Live mode: append one bubble; actual insertion waits until the bubble finishes rendering.
        """
        # Update sticky flag based on current position
        sb = self.scroll.verticalScrollBar()
        self._stick_to_bottom = (sb.maximum() - sb.value()) <= 5

        bubble = UserChatBubbleWidget(text) if is_user else AssistantChatBubbleWidget(text)
        self.pending_bubbles.append(bubble)

        # When the webview finishes, place at the end (legacy path)
        bubble.rendered.connect(self._add_and_size_bubble)

    # ---------------------------
    # Ordered batch API (hydrate)
    # ---------------------------
    def begin_ordered_batch(self, count: int):
        """
        Prepare 'count' empty rows (slot containers) in order. Each slot gets populated
        later when its bubble finishes rendering.
        """
        self._ordered_active = True
        self._ordered_slots = []
        self._ordered_expected = max(0, int(count))
        self._ordered_inserted = 0

        # Clear any existing rows first
        self._clear_all_rows()

        # Create 'count' empty slot containers
        for _ in range(self._ordered_expected):
            container = QWidget()
            container_layout = QHBoxLayout(container)
            container_layout.setContentsMargins(10, 5, 10, 5)
            container.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            # insert before the final stretch
            self.chat_layout.insertWidget(self.chat_layout.count() - 1, container)
            self._ordered_slots.append(container)

        # In hydration we generally want to end at the bottom
        self._stick_to_bottom = True

    def add_message_ordered(self, text: str, is_user: bool, index: int):
        """
        Queue a bubble for a pre-created slot at 'index'. We still wait for the bubble to render
        to get correct size, but it will always land in the right row.
        """
        if not self._ordered_active:
            # Fallback to live mode
            return self.add_message(text, is_user)

        if index < 0 or index >= len(self._ordered_slots):
            # Guard – bad index; place at end as a fallback
            return self.add_message(text, is_user)

        bubble = UserChatBubbleWidget(text) if is_user else AssistantChatBubbleWidget(text)
        self.pending_bubbles.append(bubble)

        # IMPORTANT: rendered emits (QWidget bubble, bool is_user) — accept BOTH
        bubble.rendered.connect(
            lambda _bubble, _is_user, b=bubble, iu=is_user, idx=index:
            self._place_bubble_in_slot(b, iu, idx)
        )

    def end_ordered_batch(self):
        """
        End ordered mode. (Bubbles may still be rendering; this just releases the flag.)
        """
        self._ordered_active = False
        # A gentle nudge to bottom after Qt processes some paints
        if self._stick_to_bottom:
            QTimer.singleShot(0, self._jump_to_bottom)

    # ---------------------------
    # Internal helpers
    # ---------------------------
    def _clear_all_rows(self):
        """Remove all rows (containers) and leave one trailing stretch."""
        try:
            self.pending_bubbles.clear()
        except Exception:
            pass
        layout = self.chat_layout
        # remove everything
        for i in reversed(range(layout.count())):
            item = layout.itemAt(i)
            if item and item.widget():
                w = item.widget()
                layout.removeWidget(w)
                w.deleteLater()
            else:
                layout.removeItem(item)
        # re-add trailing stretch
        layout.addStretch()

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

    # Legacy path: place at the end when a bubble finishes (live mode)
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

        if not is_user:
            viewer = getattr(bubble, "llm_text", None)
            if viewer:
                viewer.set_speak_visible(self._tts_enabled)
                viewer.speak_requested.connect(self._on_bubble_speak_clicked)

        # Connect sticky scroll to geometry changes (don’t re-run width sizing here)
        viewer = getattr(bubble, "user_message", None) or getattr(bubble, "llm_text", None)
        if viewer:
            viewer.geometry_changed.connect(self._maybe_stick_after_geometry)

        self._trigger_bubble_width_adjustment(bubble)

        # If we were already at bottom, snap after insertion
        if self._stick_to_bottom:
            QTimer.singleShot(0, self._jump_to_bottom)

        # Remove from pending
        if bubble in self.pending_bubbles:
            self.pending_bubbles.remove(bubble)

    # Ordered path: place bubble in its pre-created slot row
    def _place_bubble_in_slot(self, bubble, is_user: bool, index: int):
        if index < 0 or index >= len(self._ordered_slots):
            # If something went sideways, fallback to end-append
            return self._add_and_size_bubble(bubble, is_user)

        container = self._ordered_slots[index]
        layout = container.layout()  # QHBoxLayout

        # Clean the slot (paranoia, should be empty)
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if is_user:
            layout.addStretch(1)
            layout.addWidget(bubble, 0, Qt.AlignRight)
        else:
            layout.addWidget(bubble, 0, Qt.AlignLeft)
            layout.addStretch(1)

        if not is_user:
            viewer = getattr(bubble, "llm_text", None)
            if viewer:
                viewer.set_speak_visible(self._tts_enabled)
                viewer.speak_requested.connect(self._on_bubble_speak_clicked)

        viewer = getattr(bubble, "user_message", None) or getattr(bubble, "llm_text", None)
        if viewer:
            viewer.geometry_changed.connect(self._maybe_stick_after_geometry)

        self._trigger_bubble_width_adjustment(bubble)

        # Maintain stickiness across many inserts
        if self._stick_to_bottom:
            QTimer.singleShot(0, self._jump_to_bottom)

        # Remove from pending
        if bubble in self.pending_bubbles:
            self.pending_bubbles.remove(bubble)

        # Track completion; on last, nudge to bottom
        self._ordered_inserted += 1
        if self._ordered_active and self._ordered_inserted >= self._ordered_expected and self._stick_to_bottom:
            QTimer.singleShot(0, self._jump_to_bottom)

    def _maybe_stick_after_geometry(self):
        if self._stick_to_bottom:
            QTimer.singleShot(0, self._jump_to_bottom)

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
        # Update live rows (legacy)
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

    def _on_bubble_speak_clicked(self, markdown_text: str):
        # Bubble asks to (re)generate speech; let ChatTab handle TTS
        self.speak_requested.emit(markdown_text or "")

    def set_tts_enabled(self, enabled: bool):
        self._tts_enabled = bool(enabled)
        # Chip visibility
        self.audio_chip.setVisible(self._tts_enabled)
        # Toggle Speak button on existing assistant bubbles
        for i in range(self.chat_layout.count() - 1):
            item = self.chat_layout.itemAt(i)
            if not item or not item.widget():
                continue
            container = item.widget()
            bubble = container.findChild(AssistantChatBubbleWidget)
            if bubble:
                viewer = getattr(bubble, "llm_text", None)
                if viewer:
                    viewer.set_speak_visible(self._tts_enabled)
