import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap, QTransform
from PySide6.QtWidgets import QLabel, QWidget


class LauncherWindow(QWidget):
    sig_toggle_chat = Signal()
    sig_position = Signal(int, int, int, int, int, int, int, int)  # x, y, w, h, screen_x, screen_y, screen_w, screen_h
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
        old_x = self.x()
        self.move(px, py)
        self._mirror_duck_if_needed(old_x)

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
        screen = self.screen().geometry()
        self.sig_position.emit(
            self.x(), self.y(), self.width(), self.height(), screen.x(), screen.y(), screen.width(), screen.height()
        )
        super().mouseReleaseEvent(event)

    def mouseMoveEvent(self, event):
        if self._is_dragging:
            new_x = event.globalPosition().x() - self._drag_offset[0]
            new_y = event.globalPosition().y() - self._drag_offset[1]
            old_x = self.x() - self.screen().geometry().x()
            self.move(new_x, new_y)
            self.resize(self.duck_label.pixmap().size())
            self._mirror_duck_if_needed(old_x)
            # Set was_dragged to True since the mouse was moved
            self._was_dragged = True
            screen = self.screen().geometry()
            self.sig_position.emit(
                self.x(), self.y(), self.width(), self.height(), screen.x(), screen.y(), screen.width(), screen.height()
            )
        super().mouseMoveEvent(event)

    def _mirror_duck_if_needed(self, old_x):
        screen = self.screen().geometry()
        screen_w = screen.width()
        w = self.width()
        new_x = self.x() - screen.x()
        if (new_x + w / 2 > screen_w / 2 and old_x + w / 2 <= screen_w / 2) or (
            new_x + w / 2 <= screen_w / 2 and old_x + w / 2 > screen_w / 2
        ):
            flip_scale = -1.0
        else:
            flip_scale = 1.0
        transform = QTransform(flip_scale, 0, 0, 1, 0, 0)
        self.duck_label.setPixmap(self.duck_label.pixmap().transformed(transform))
