import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QWidget


class LauncherWindow(QWidget):
    sig_toggle_chat = Signal()
    sig_position = Signal(int, int, int, int)  # x, y, w, h
    sig_exit = Signal()

    def __init__(self, config=None):
        super().__init__()
        self.config = config

        # Set window properties
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.NoFocus)

        # Create duck icon
        self.duck_label = QLabel(self)
        duck_path = os.path.join(os.path.dirname(__file__), "..", "assets", "icons", "duck_low_res.png")
        pixmap = QPixmap(duck_path)
        self.duck_label.setPixmap(pixmap)
        self.resize(pixmap.size())
        screen = self.screen()
        screen_rect = screen.geometry()
        py = max(screen_rect.height() - 100 - pixmap.height(), 0)
        px = max(screen_rect.width() - 50 - pixmap.width(), 0)
        self.move(px, py)

        # Setup mouse movement variables
        self._is_dragging = False
        self._was_dragged = False
        self._drag_offset = None

    def mousePressEvent(self, event):
        if (
            event.button() == Qt.LeftButton
            and event.modifiers() & Qt.ControlModifier
            and self.config.get("ctrl_click_to_exit", False)
        ):
            self.sig_exit.emit()
        elif event.button() == Qt.LeftButton:
            self._is_dragging = True
            self._drag_offset = (
                event.globalPosition().x() - self.x(),
                event.globalPosition().y() - self.y(),
            )
            # Reset was_dragged when pressing (in case of multiple clicks)
            self._was_dragged = False
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if not self._was_dragged:
            # If it wasn't being dragged, emit the signal
            self.sig_toggle_chat.emit()
        else:
            self._is_dragging = False
            self._drag_offset = None
        self.sig_position.emit(self.x(), self.y(), self.width(), self.height())
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        if self._is_dragging:
            new_x = event.globalPosition().x() - self._drag_offset[0]
            new_y = event.globalPosition().y() - self._drag_offset[1]
            self.move(new_x, new_y)
            # Set was_dragged to True since the mouse was moved
            self._was_dragged = True
            self.sig_position.emit(self.x(), self.y(), self.width(), self.height())
        super().mouseMoveEvent(event)
