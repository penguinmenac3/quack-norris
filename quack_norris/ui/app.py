import os
import sys
from typing import Any, Callable

from PySide6.QtCore import QPoint
from PySide6.QtGui import QAction, QCursor, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from quack_norris.ui.views.chat_view import ChatWindow
from quack_norris.ui.views.launcher import LauncherWindow


def main(config: dict[str, Any]):
    app = QApplication()
    app.setApplicationName("quack-norris-ui")
    app.setApplicationDisplayName("Quack Norris")

    duck_path = os.path.join(os.path.dirname(__file__), "assets", "icons", "duck_low_res.png")
    config_duck_path = config.get("launcher_icon", duck_path)
    if os.path.exists(config_duck_path):
        duck_path = config_duck_path

    # Initialize global state
    launcher = LauncherWindow(config, duck_path)
    launcher.show()
    chat_window = ChatWindow(config)
    chat_window.hide()

    # Connect launcher and chat window
    launcher.sig_toggle_chat.connect(
        lambda: chat_window.show() if not chat_window.isVisible() else chat_window.hide()
    )
    launcher.sig_position.connect(lambda *args: chat_window.align_with_launcher(*args))
    launcher.sig_exit.connect(lambda: sys.exit(0))

    # Run the app
    def on_hide():
        if chat_window.isVisible():
            chat_window.hide()
        if launcher.isVisible():
            launcher.hide()
        else:
            launcher.show()

    def on_reset():
        launcher.reset_position()

    setup_system_tray(app, on_hide, on_reset, duck_path)
    sys.exit(app.exec())


def setup_system_tray(app: QApplication, on_hide: Callable, on_reset: Callable, duck_path: str):
    # Set application icon for system tray (use one of your existing icons)
    icon = QIcon(duck_path)

    # Create system tray
    tray_icon = QSystemTrayIcon(icon, app)
    tray_icon.setToolTip("Quack Norris")
    tray_menu = QMenu()

    # Add actions to the menu
    hide_action = QAction("Show/Hide", app)
    hide_action.triggered.connect(on_hide)
    tray_menu.addAction(hide_action)
    reset_action = QAction("Reset Pos.", app)
    reset_action.triggered.connect(on_reset)
    tray_menu.addAction(reset_action)

    exit_action = QAction("Exit", app)
    exit_action.triggered.connect(lambda: sys.exit(0))
    tray_menu.addAction(exit_action)

    # Set up the system tray
    tray_icon.setContextMenu(tray_menu)
    tray_icon.show()

    def tray_icon_activated(reason):
        if reason == QSystemTrayIcon.ActivationReason.Context:
            pos = QPoint(QCursor.pos())
            pos.setY(pos.y() - tray_menu.height())
            tray_menu.exec_(pos)

    tray_icon.activated.connect(tray_icon_activated)
