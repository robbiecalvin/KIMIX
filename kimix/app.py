from pathlib import Path
import sys
from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QHBoxLayout, QMainWindow, QPushButton, QStackedWidget, QVBoxLayout, QWidget, QApplication

from .editor import AudioEditor
from .player import KIMIXNowPlaying, KIMIXPlayer, SystemCheckDialog, _system_check_rows


class KIMIXWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("KIMIX")
        self.resize(1380, 820)
        icon_path = Path(__file__).resolve().parent.parent / "Kimix.png"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        root = QWidget()
        root.setObjectName("kimixRoot")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        mode_bar = QHBoxLayout()
        self.now_mode_btn = QPushButton("Now Playing")
        self.playlist_mode_btn = QPushButton("Playlist")
        self.editor_mode_btn = QPushButton("Editor")
        self.now_mode_btn.clicked.connect(lambda: self.switch_mode(0))
        self.playlist_mode_btn.clicked.connect(lambda: self.switch_mode(1))
        self.editor_mode_btn.clicked.connect(lambda: self.switch_mode(2))
        mode_bar.addWidget(self.now_mode_btn)
        mode_bar.addWidget(self.playlist_mode_btn)
        mode_bar.addWidget(self.editor_mode_btn)
        mode_bar.addStretch(1)
        self.system_check_btn = QPushButton("System Check")
        self.system_check_btn.clicked.connect(self.open_system_check)
        mode_bar.addWidget(self.system_check_btn)
        layout.addLayout(mode_bar)

        self.stack = QStackedWidget()
        self.playlist_view = KIMIXPlayer()
        self.now_view = KIMIXNowPlaying(self.playlist_view)
        self.editor_view = AudioEditor()
        self.stack.addWidget(self.now_view)
        self.stack.addWidget(self.playlist_view)
        self.stack.addWidget(self.editor_view)
        layout.addWidget(self.stack, 1)

        self.setStyleSheet(
            """
            QWidget#kimixRoot { background: #040a18; }
            QStackedWidget { background: #040a18; border: 1px solid rgba(84,117,255,0.22); border-radius: 10px; }
            QPushButton {
                border: 1px solid rgba(233,236,255,0.22);
                border-radius: 10px;
                padding: 8px 12px;
                background: #0a1430;
                color: #e9ecff;
                font-weight: 700;
            }
            """
        )
        self.switch_mode(0)
        self._show_startup_checks_if_needed()

    def open_system_check(self):
        dialog = SystemCheckDialog(self)
        dialog.exec_()

    def _show_startup_checks_if_needed(self):
        checks = _system_check_rows()
        failed = [name for name, ok, _ in checks if not ok]
        if failed:
            QTimer.singleShot(250, self.open_system_check)

    def switch_mode(self, index: int):
        self.stack.setCurrentIndex(index)
        active = "rgba(84,117,255,0.36)"
        idle = "#101727"
        self.now_mode_btn.setStyleSheet(f"background:{active if index == 0 else idle};")
        self.playlist_mode_btn.setStyleSheet(f"background:{active if index == 1 else idle};")
        self.editor_mode_btn.setStyleSheet(f"background:{active if index == 2 else idle};")
        if index != 2:
            self.editor_view.stop_playback()

    def closeEvent(self, event):
        self.playlist_view.stop()
        self.editor_view.stop_playback()
        self.editor_view._save_projects_to_disk()
        event.accept()


def main():
    app = QApplication(sys.argv)
    icon_candidates = [Path(__file__).resolve().parent.parent / "Kimix.png", Path(__file__).resolve().parent.parent / "KIMIX.png"]
    for icon_path in icon_candidates:
        if icon_path.exists():
            app.setWindowIcon(QIcon(str(icon_path)))
            break
    window = KIMIXWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
