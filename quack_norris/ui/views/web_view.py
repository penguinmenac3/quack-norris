import PySide6.QtGui
from PySide6.QtCore import Qt
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QMainWindow
from PySide6.QtWidgets import QWidget

from quack_norris.config import Config


class WebViewWindow(QMainWindow):

    def __init__(self, config: Config, parent: QWidget):
        super().__init__()
        self.config = config
        self.launcher = parent
        self._first_move = True
        self._first_resize = True

        # Set window properties
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool)# | Qt.FramelessWindowHint)

        # Create and set up the web view as central widget
        self.web_view = QWebEngineView()
        self.setCentralWidget(self.web_view)

        # Set url for the PWA quack-norris
        if config.get("debug", False):
            self.url = config.get("url-debug", "http://localhost:5173/quack-norris/")
        else:
            self.url = config.get("url", "https://penguinmenac3.github.io/quack-norris/")
        self.web_view.setUrl(self.url)
        self.resize(600, 800)

        # Onresize and onmove update the parent position
        self.resizeEvent = self.on_resize
        self.moveEvent = self.on_move

    def on_resize(self, event):
        if isinstance(event, PySide6.QtGui.QResizeEvent):
            # Skip non-spontaneous events (caused by code)
            if not event.spontaneous():
                return
            # Skip the first resize event to avoid jumping to center of screen
            if self._first_resize:
                self._first_resize = False
                return
            self.update_launcher_position(event)

    def on_move(self, event):
        if isinstance(event, PySide6.QtGui.QMoveEvent):
            # Skip non-spontaneous events (caused by code, e.g. launcher dragging)
            if not event.spontaneous():
                return
            # Skip the first move event to avoid jumping to center of screen
            if self._first_move:
                self._first_move = False
                return
            self.update_launcher_position(event)

    def update_launcher_position(self, event):
        # Figure out in which corner the launcher is
        bbox = self.frameGeometry().getRect()
        launcher_bbox = self.launcher.frameGeometry().getRect()
        # Check if launcher is on left or right side
        left = bbox[0] + bbox[2] / 2 >= launcher_bbox[0] + launcher_bbox[2] / 2
        # Check if launcher is on top or bottom side
        top = bbox[1] + bbox[3] / 2 >= launcher_bbox[1] + launcher_bbox[3] / 2

        if left and launcher_bbox[0] > self.screen().geometry().width() / 2:
            left = False
        elif not left and launcher_bbox[0] < self.screen().geometry().width() / 2:
            left = True

        if top and launcher_bbox[1] > self.screen().geometry().height() / 2:
            top = False
        elif not top and launcher_bbox[1] < self.screen().geometry().height() / 2:
            top = True

        if left:
            x = bbox[0] - launcher_bbox[2]
        else:
            x = bbox[0] + bbox[2]
        if top:
            y = bbox[1]
        else:
            y = bbox[1] + bbox[3] - launcher_bbox[3]
        
        old_x = self.launcher.x() - self.screen().geometry().x()
        self.launcher.move(x, y)
        self.launcher._mirror_duck_if_needed(old_x)

    def align_with_launcher(self, x, y, w, h, screen_x, screen_y, screen_w, screen_h):
        p = [0, 0]
        x = x - screen_x
        y = y - screen_y
        window_bar_height = self.frameGeometry().height() - self.size().height()
        win_h = self.frameGeometry().height()
        win_w = self.size().width()
        win_h = min(win_h, max(screen_h - (y + 5), y + h - 5))
        win_w = min(win_w, max(screen_w - (x + w + 5), x - 5))

        # Calculate window position based on Launcher's position
        if x + w / 2 <= screen_w / 2 and y + h / 2 <= screen_h / 2:
            # Top-left quadrant
            p = (x + w, y + window_bar_height)
        elif x + w / 2 > screen_w / 2 and y + h / 2 <= screen_h / 2:
            # Top-right quadrant
            p = (x - win_w, y + window_bar_height)
        elif x + w / 2 <= screen_w / 2 and y + h / 2 > screen_h / 2:
            # Bottom-left quadrant
            p = (x + w, y + h - win_h + window_bar_height)
        else:
            # Bottom-right quadrant
            p = (x - win_w, y + h - win_h + window_bar_height)        
        self.setGeometry(p[0] + screen_x, p[1] + screen_y, win_w, win_h - window_bar_height)
