import os
import sys
import uuid
import subprocess
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, 
    QLabel, QPushButton, QProgressBar, QComboBox, QLineEdit, QCheckBox
)
from PyQt6.QtCore import QThread, pyqtSignal, Qt
import minecraft_launcher_lib

desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
GAME_DIR = os.path.join(desktop_path, "PHICLIENTV2")

MODS_DIR = os.path.join(GAME_DIR, "mods")
os.makedirs(MODS_DIR, exist_ok=True)


class LaunchWorker(QThread):
    status_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(list)
    error_signal = pyqtSignal(str)

    def __init__(self, username, version, use_fabric):
        super().__init__()
        self.username = username
        self.version = version
        self.use_fabric = use_fabric
        self.current_progress = 0
        self.max_progress = 0

    def set_status(self, status: str):
        self.status_signal.emit(status)

    def set_progress(self, progress: int):
        self.current_progress = progress
        if self.max_progress > 0:
            percent = int((progress / self.max_progress) * 100)
            self.progress_signal.emit(min(percent, 100))

    def set_max_progress(self, max_val: int):
        self.max_progress = max_val

    def run(self):
        try:
            callback = {
                "setStatus": self.set_status,
                "setProgress": self.set_progress,
                "setMaxProgress": self.set_max_progress
            }

            # 1. Install base Vanilla version
            self.status_signal.emit(f"Downloading Vanilla {self.version}...")
            minecraft_launcher_lib.install.install_minecraft_version(
                self.version, GAME_DIR, callback=callback
            )

            target_version = self.version

            # 2. Install Fabric Loader
            if self.use_fabric:
                self.status_signal.emit(f"Installing Fabric Loader for {self.version}...")
                self.progress_signal.emit(25)
                
                minecraft_launcher_lib.fabric.install_fabric(
                    self.version, GAME_DIR, callback=callback
                )
                
                # Fetch installed version IDs using utils
                installed_versions = minecraft_launcher_lib.utils.get_installed_versions(GAME_DIR)
                fabric_versions = [v['id'] for v in installed_versions if 'fabric' in v['id'].lower() and self.version in v['id']]
                
                if fabric_versions:
                    target_version = fabric_versions[0]
                else:
                    # Fallback to any installed fabric profile
                    any_fabric = [v['id'] for v in installed_versions if 'fabric' in v['id'].lower()]
                    target_version = any_fabric[0] if any_fabric else self.version

            # 3. Generate offline UUID
            player_uuid = str(uuid.uuid3(uuid.NAMESPACE_DNS, f"OfflinePlayer:{self.username}"))

            options = {
                "username": self.username,
                "uuid": player_uuid,
                "token": "0"
            }

            self.status_signal.emit("Building game launch command...")
            command = minecraft_launcher_lib.command.get_minecraft_command(
                target_version, GAME_DIR, options
            )

            self.finished_signal.emit(command)

        except Exception as e:
            self.error_signal.emit(str(e))


class LauncherWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PHI CLIENT V2")
        self.resize(460, 380)

        self.setStyleSheet("""
            QMainWindow { background-color: #0f172a; }
            QLabel { color: #f8fafc; font-family: sans-serif; font-size: 13px; }
            QLineEdit, QComboBox { 
                background-color: #1e293b; color: #ffffff; 
                border: 1px solid #334155; padding: 10px; border-radius: 6px; font-size: 14px;
            }
            QCheckBox { color: #38bdf8; font-size: 14px; font-weight: bold; }
            QPushButton { 
                background-color: #2563eb; color: white; font-weight: bold; 
                padding: 12px; border-radius: 6px; font-size: 14px;
            }
            QPushButton:hover { background-color: #3b82f6; }
            QPushButton:disabled { background-color: #475569; color: #94a3b8; }
            QProgressBar {
                border: 1px solid #334155; border-radius: 6px; text-align: center;
                background-color: #1e293b; color: #ffffff;
            }
            QProgressBar::chunk { background-color: #3b82f6; border-radius: 5px; }
        """)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setSpacing(12)

        title = QLabel("PHI CLIENT V2")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #60a5fa;")
        layout.addWidget(title)

        layout.addWidget(QLabel("Account Username:"))
        self.username_input = QLineEdit()
        self.username_input.setText("Player1")
        layout.addWidget(self.username_input)

        layout.addWidget(QLabel("Select Version:"))
        self.version_box = QComboBox()
        self.version_box.addItems(["1.21.11", "1.21.1", "1.20.1"])
        layout.addWidget(self.version_box)

        self.fabric_checkbox = QCheckBox("Enable Fabric Loader (Modded)")
        self.fabric_checkbox.setChecked(True)
        layout.addWidget(self.fabric_checkbox)

        self.status_label = QLabel("Mods location: PHICLIENTV2/mods")
        self.status_label.setStyleSheet("color: #94a3b8; font-size: 12px;")
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.play_btn = QPushButton("PLAY MINECRAFT")
        self.play_btn.clicked.connect(self.start_launch)
        layout.addWidget(self.play_btn)

    def start_launch(self):
        username = self.username_input.text().strip() or "Player1"
        version = self.version_box.currentText()
        use_fabric = self.fabric_checkbox.isChecked()

        self.play_btn.setEnabled(False)
        self.username_input.setEnabled(False)
        self.version_box.setEnabled(False)
        self.fabric_checkbox.setEnabled(False)

        self.worker = LaunchWorker(username, version, use_fabric)
        self.worker.status_signal.connect(self.status_label.setText)
        self.worker.progress_signal.connect(self.progress_bar.setValue)
        self.worker.finished_signal.connect(self.on_launch_ready)
        self.worker.error_signal.connect(self.on_error)
        self.worker.start()

    def on_launch_ready(self, command):
        self.status_label.setText("Launching game window...")
        self.progress_bar.setValue(100)
        
        subprocess.Popen(command)

        self.play_btn.setEnabled(True)
        self.username_input.setEnabled(True)
        self.version_box.setEnabled(True)
        self.fabric_checkbox.setEnabled(True)

    def on_error(self, err_msg):
        self.status_label.setText(f"Error: {err_msg}")
        self.play_btn.setEnabled(True)
        self.username_input.setEnabled(True)
        self.version_box.setEnabled(True)
        self.fabric_checkbox.setEnabled(True)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = LauncherWindow()
    window.show()
    sys.exit(app.exec())