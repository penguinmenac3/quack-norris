from typing import Any
import urllib.parse

from PySide6.QtCore import Qt
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QMainWindow


class ChatWindow(QMainWindow):

    def __init__(self, config: dict[str, Any]):
        super().__init__()
        self.config = config

        # Set window properties
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)

        # Create and set up the web view as central widget
        self.web_view = QWebEngineView()
        self.setCentralWidget(self.web_view)

        # Set url for the PWA quack-norris
        host = config.get("host", "")
        port = config.get("port", "")
        token = config.get("token", "")
        query = ""
        if host != "" or port != "" or token != "":
            query = "#" + urllib.parse.urlencode(dict(host=host, port=port, token=token))
        if config["debug"]:
            # If debugging, use local url, so we can show the vite server content
            self.web_view.setUrl("http://localhost:5173/quack-norris/{query}".format(query=query))
        else:
            default_url = "https://penguinmenac3.github.io/quack-norris/{query}"  # PLACEHOLDER
            self.web_view.setUrl(config.get("chat_url", default_url).format(query=query))

    def align_with_launcher(self, x, y, w, h, screen_x, screen_y, screen_w, screen_h):
        win_h = min(screen_h / 2 + h / 2, 800)
        win_w = min(screen_w / 2 - w / 2, 600)
        p = [0, 0]
        x = x - screen_x
        y = y - screen_y

        # Calculate window position based on Launcher's position
        if x + w / 2 <= screen_w / 2 and y + h / 2 <= screen_h / 2:
            # Top-left quadrant
            p = (x + w, y)
        elif x + w / 2 > screen_w / 2 and y + h / 2 <= screen_h / 2:
            # Top-right quadrant
            p = (x - win_w, y)
        elif x + w / 2 <= screen_w / 2 and y + h / 2 > screen_h / 2:
            # Bottom-left quadrant
            p = (x + w, y + h - win_h)
        else:
            # Bottom-right quadrant
            p = (x - win_w, y + h - win_h)
        self.setGeometry(p[0] + screen_x, p[1] + screen_y, win_w, win_h)
