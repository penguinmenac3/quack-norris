import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QMainWindow,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

# from quack_norris.ui.models.message import Message
from quack_norris.ui.models.chat_state import ChatState


class ChatWindow(QMainWindow):
    def __init__(self, config: any):
        super().__init__()
        self.config = config
        self.chat_state = ChatState()
        self.current_chat_id = None
        self.setup_ui()

        # Set window properties
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)

    def setup_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)

        # Messages area
        self.messages_area = QTextEdit()
        self.messages_area.setReadOnly(True)
        layout.addWidget(self.messages_area)

        # Input area
        input_layout = QHBoxLayout()

        # File attachment button
        self.file_button = QPushButton("📁")
        self.file_button.clicked.connect(self.handle_file_upload)
        input_layout.addWidget(self.file_button)

        # Message input
        self.message_input = QTextEdit()
        self.message_input.setMaximumHeight(50)
        input_layout.addWidget(self.message_input)

        # Send button
        send_button = QPushButton("Send 🦢")
        send_button.clicked.connect(lambda: self.send_message())
        input_layout.addWidget(send_button)

        layout.addLayout(input_layout)

        # Audio controls
        self.audio_button = QPushButton("🎤 Audio")
        self.audio_button.clicked.connect(self.toggle_audio_mode)
        input_layout.addWidget(self.audio_button)

        # Model dropdown
        self.model_dropdown = QComboBox()
        models = ["quack-norris", "llama3.2:7b"]
        self.model_dropdown.addItems(models)
        self.model_dropdown.currentTextChanged.connect(self.handle_model_change)
        layout.addWidget(self.model_dropdown)

    def handle_file_upload(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Attach File", "", "All Files (*.*)")
        if file_path:
            # Handle file upload logic here
            pass

    def send_message(self):
        message = self.message_input.toPlainText()
        if not message.strip():
            return

        # Add to messages_area
        self.messages_area.append(f">> {message}\n")

        # Clear input
        self.message_input.clear()

    def toggle_audio_mode(self):
        pass  # Implement audio transcription and TTS functionality

    def handle_model_change(self, model_name):
        pass  # Handle model switching logic

    def show_message(self, message: str):
        self.messages_area.append(message)

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

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
            super().dragEnterEvent(event)

    def dropEvent(self, event):
        for url in event.urls():
            file_path = url.path()
            if os.path.isfile(file_path):
                self.handle_file_upload(file_path)
        super().dropEvent(event)
