import os
import sys
import uuid
import shutil
import json
import subprocess
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, 
    QHBoxLayout, QLabel, QPushButton, QProgressBar, QComboBox, 
    QLineEdit, QCheckBox, QFrame, QStackedWidget, QListWidget, 
    QFileDialog, QInputDialog, QMessageBox
)
from PyQt6.QtCore import QThread, pyqtSignal, Qt
import minecraft_launcher_lib

desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
GAME_DIR = os.path.join(desktop_path, "PHICLIENTV2")
MODPACKS_DIR = os.path.join(GAME_DIR, "modpacks")
MODS_DIR = os.path.join(GAME_DIR, "mods")
CONFIG_FILE = os.path.join(GAME_DIR, "client_config.json")

os.makedirs(GAME_DIR, exist_ok=True)
os.makedirs(MODPACKS_DIR, exist_ok=True)
os.makedirs(MODS_DIR, exist_ok=True)

DEFAULT_PACK = os.path.join(MODPACKS_DIR, "Default Pack")
os.makedirs(DEFAULT_PACK, exist_ok=True)

# Preserve existing mods inside GAME_DIR/mods into Default Pack on startup
def sync_existing_mods_to_default():
    if os.path.exists(MODS_DIR):
        for item in os.listdir(MODS_DIR):
            if item.endswith(".jar"):
                src = os.path.join(MODS_DIR, item)
                dst = os.path.join(DEFAULT_PACK, item)
                if not os.path.exists(dst):
                    try:
                        shutil.copy2(src, dst)
                    except Exception:
                        pass

sync_existing_mods_to_default()

def get_real_release_versions():
    """Fetch official release versions dynamically, with installed/offline fallbacks."""
    real_versions = []
    
    # 1. Fetch remote release versions from Mojang API
    try:
        remote_list = minecraft_launcher_lib.utils.get_version_list()
        for v in remote_list:
            if v.get("type") == "release":
                real_versions.append(v["id"])
    except Exception:
        pass

    # 2. Add locally installed versions
    try:
        installed = minecraft_launcher_lib.utils.get_installed_versions(GAME_DIR)
        for iv in installed:
            if iv["id"] not in real_versions:
                real_versions.append(iv["id"])
    except Exception:
        pass

    # 3. Fallback list if offline or API fails
    if not real_versions:
        real_versions = [
            "1.21.4", "1.21.3", "1.21.1", "1.20.4", "1.20.1", 
            "1.19.4", "1.18.2", "1.16.5", "1.12.2", "1.8.9"
        ]

    return real_versions


class LaunchWorker(QThread):
    status_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(list)
    error_signal = pyqtSignal(str)

    def __init__(self, username, version, use_fabric, active_modpack_path):
        super().__init__()
        self.username = username
        self.version = version
        self.use_fabric = use_fabric
        self.active_modpack_path = active_modpack_path
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

            # Prepare target mods directory
            if os.path.exists(MODS_DIR):
                if os.path.islink(MODS_DIR):
                    os.unlink(MODS_DIR)
                elif os.path.isdir(MODS_DIR):
                    shutil.rmtree(MODS_DIR)

            # Link or copy active modpack contents into mods folder
            try:
                os.symlink(self.active_modpack_path, MODS_DIR, target_is_directory=True)
            except Exception:
                os.makedirs(MODS_DIR, exist_ok=True)
                if os.path.exists(self.active_modpack_path):
                    for item in os.listdir(self.active_modpack_path):
                        s = os.path.join(self.active_modpack_path, item)
                        d = os.path.join(MODS_DIR, item)
                        if os.path.isfile(s) and (s.endswith(".jar") or s.endswith(".jar.disabled")):
                            shutil.copy2(s, d)

            self.status_signal.emit(f"Downloading Vanilla {self.version}...")
            minecraft_launcher_lib.install.install_minecraft_version(
                self.version, GAME_DIR, callback=callback
            )

            target_version = self.version

            if self.use_fabric:
                self.status_signal.emit(f"Installing Fabric Loader for {self.version}...")
                self.progress_signal.emit(25)
                
                try:
                    minecraft_launcher_lib.fabric.install_fabric(
                        self.version, GAME_DIR, callback=callback
                    )
                except Exception as e:
                    self.status_signal.emit(f"Fabric note: {str(e)}")
                
                installed_versions = minecraft_launcher_lib.utils.get_installed_versions(GAME_DIR)
                fabric_versions = [
                    v['id'] for v in installed_versions 
                    if 'fabric' in v['id'].lower() and self.version in v['id']
                ]
                
                if fabric_versions:
                    target_version = fabric_versions[0]
                else:
                    any_fabric = [v['id'] for v in installed_versions if 'fabric' in v['id'].lower()]
                    target_version = any_fabric[0] if any_fabric else self.version

            player_uuid = str(uuid.uuid3(uuid.NAMESPACE_DNS, f"OfflinePlayer:{self.username}"))

            options = {
                "username": self.username,
                "uuid": player_uuid,
                "token": "0",
                "gameDir": GAME_DIR
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
        self.setWindowTitle("PHI CLIENT V3 - Ultimate Edition")
        self.resize(960, 620)
        self.setMinimumSize(880, 560)

        self.load_config()

        self.setStyleSheet("""
            QMainWindow { background-color: #040406; }
            QWidget { color: #ffffff; font-family: 'Segoe UI', sans-serif; }
            
            QFrame#sidebar { background-color: #08080c; border-right: 1px solid #14141e; }
            QFrame#card { background-color: #0d0d14; border: 1px solid #1a1a26; border-radius: 12px; }
            QFrame#header_card { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0f0f18, stop:1 #08080d); border: 1px solid #1f1f30; border-radius: 12px; }
            
            QLineEdit, QComboBox { 
                background-color: #06060a; color: #ffffff; 
                border: 1px solid #202030; padding: 10px 12px; border-radius: 8px; font-size: 13px;
            }
            QLineEdit:focus, QComboBox:focus { border: 1px solid #00f0ff; }
            QComboBox::drop-down { border: none; }
            
            QCheckBox { color: #8a8a9e; font-size: 13px; font-weight: bold; spacing: 8px; }
            QCheckBox::indicator { width: 18px; height: 18px; border-radius: 4px; border: 1px solid #222230; background: #06060a; }
            QCheckBox::indicator:checked { background: #00f0ff; border: 1px solid #00f0ff; }
            
            QPushButton#nav_btn { 
                background-color: transparent; color: #7a7a8c; font-weight: 700; 
                font-size: 13px; text-align: left; padding: 12px 18px; border: none; border-radius: 8px;
            }
            QPushButton#nav_btn:hover { background-color: #10101a; color: #ffffff; }
            QPushButton#nav_btn[active="true"] { background-color: #141422; color: #00f0ff; border-left: 4px solid #00f0ff; }
            
            QPushButton#action_btn { 
                background-color: #12121c; color: #ffffff; font-weight: 700; 
                padding: 10px 16px; border-radius: 8px; border: 1px solid #222234; font-size: 12px;
            }
            QPushButton#action_btn:hover { background-color: #1c1c2e; border-color: #00f0ff; color: #00f0ff; }
            
            QPushButton#accent_btn { 
                background-color: #00f0ff; color: #000000; font-weight: 800; 
                padding: 10px 16px; border-radius: 8px; border: none; font-size: 12px;
            }
            QPushButton#accent_btn:hover { background-color: #33f3ff; }
            
            QPushButton#play_btn { 
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00f0ff, stop:1 #0077ff); 
                color: #000000; font-weight: 900; font-size: 16px; letter-spacing: 1px; padding: 16px; border-radius: 10px; border: none;
            }
            QPushButton#play_btn:hover { 
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #33f3ff, stop:1 #338eff); 
            }
            QPushButton#play_btn:disabled { background: #12121c; color: #4a4a60; }
            
            QProgressBar { 
                border: 1px solid #181824; border-radius: 6px; text-align: center; 
                background-color: #06060a; color: #8a8a9e; font-size: 11px;
            }
            QProgressBar::chunk { background-color: #00f0ff; border-radius: 5px; }
            
            QListWidget { background-color: #06060a; border: 1px solid #181824; border-radius: 8px; color: #ffffff; padding: 8px; }
            QListWidget::item { padding: 12px; border-radius: 8px; margin-bottom: 4px; background: #0d0d14; border: 1px solid #141420; }
            QListWidget::item:selected { background-color: #141424; color: #00f0ff; border: 1px solid #00f0ff; }
        """)

        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(240)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(18, 24, 18, 24)
        sidebar_layout.setSpacing(8)

        logo_box = QVBoxLayout()
        logo_box.setSpacing(2)
        logo_title = QLabel("PHI CLIENT")
        logo_title.setStyleSheet("font-size: 24px; font-weight: 900; color: #00f0ff; letter-spacing: 2px;")
        
        badge = QLabel("V3 ULTIMATE OFFLINE")
        badge.setStyleSheet("color: #8a8a9e; font-size: 9px; font-weight: 800; background: #10101a; padding: 4px 8px; border-radius: 4px; border: 1px solid #1c1c2b;")
        badge.setFixedWidth(130)

        logo_box.addWidget(logo_title)
        logo_box.addWidget(badge)
        sidebar_layout.addLayout(logo_box)
        sidebar_layout.addSpacing(25)

        self.btn_nav_home = QPushButton("  🎮  LAUNCHER")
        self.btn_nav_home.setObjectName("nav_btn")
        self.btn_nav_home.setProperty("active", "true")
        self.btn_nav_home.clicked.connect(lambda: self.switch_page(0))

        self.btn_nav_modpacks = QPushButton("  📦  MODPACKS")
        self.btn_nav_modpacks.setObjectName("nav_btn")
        self.btn_nav_modpacks.clicked.connect(lambda: self.switch_page(1))

        self.btn_nav_mods = QPushButton("  🧩  MODS MANAGER")
        self.btn_nav_mods.setObjectName("nav_btn")
        self.btn_nav_mods.clicked.connect(lambda: self.switch_page(2))

        self.btn_nav_toggles = QPushButton("  ⚡  CLIENT MODS")
        self.btn_nav_toggles.setObjectName("nav_btn")
        self.btn_nav_toggles.clicked.connect(lambda: self.switch_page(3))

        sidebar_layout.addWidget(self.btn_nav_home)
        sidebar_layout.addWidget(self.btn_nav_modpacks)
        sidebar_layout.addWidget(self.btn_nav_mods)
        sidebar_layout.addWidget(self.btn_nav_toggles)
        sidebar_layout.addStretch()

        self.btn_open_folder = QPushButton("📁 OPEN CLIENT FOLDER")
        self.btn_open_folder.setObjectName("action_btn")
        self.btn_open_folder.clicked.connect(self.open_game_folder)
        sidebar_layout.addWidget(self.btn_open_folder)

        content_area = QWidget()
        content_layout = QVBoxLayout(content_area)
        content_layout.setContentsMargins(28, 24, 28, 24)

        self.pages = QStackedWidget()

        page_home = QWidget()
        home_layout = QVBoxLayout(page_home)
        home_layout.setSpacing(16)

        header_card = QFrame()
        header_card.setObjectName("header_card")
        header_layout = QHBoxLayout(header_card)
        header_layout.setContentsMargins(20, 16, 20, 16)
        
        h_info = QVBoxLayout()
        h_info.setSpacing(2)
        h_title = QLabel("ACTIVE MODPACK")
        h_title.setStyleSheet("font-size: 10px; font-weight: 800; color: #00f0ff; letter-spacing: 1px;")
        self.active_pack_display = QLabel(self.active_modpack)
        self.active_pack_display.setStyleSheet("font-size: 18px; font-weight: 900; color: #ffffff;")
        h_info.addWidget(h_title)
        h_info.addWidget(self.active_pack_display)

        header_layout.addLayout(h_info)
        header_layout.addStretch()

        btn_switch_pack = QPushButton("CHANGE PACK")
        btn_switch_pack.setObjectName("action_btn")
        btn_switch_pack.clicked.connect(lambda: self.switch_page(1))
        header_layout.addWidget(btn_switch_pack)

        home_layout.addWidget(header_card)

        profile_card = QFrame()
        profile_card.setObjectName("card")
        profile_layout = QVBoxLayout(profile_card)
        profile_layout.setContentsMargins(20, 20, 20, 20)
        profile_layout.setSpacing(14)

        p_title = QLabel("GAME LAUNCH CONFIGURATION")
        p_title.setStyleSheet("font-size: 13px; font-weight: 800; color: #00f0ff; letter-spacing: 1px;")
        
        user_box = QVBoxLayout()
        user_box.setSpacing(6)
        user_box.addWidget(QLabel("Player Username"))
        self.username_input = QLineEdit()
        self.username_input.setText(self.config.get("username", "Player1"))
        user_box.addWidget(self.username_input)

        ver_box = QVBoxLayout()
        ver_box.setSpacing(6)
        ver_box.addWidget(QLabel("Select Release Version"))
        self.version_box = QComboBox()
        
        # Populate with real release versions
        version_list = get_real_release_versions()
        self.version_box.addItems(version_list)
        
        saved_ver = self.config.get("version", "1.21.1")
        if saved_ver in version_list:
            self.version_box.setCurrentText(saved_ver)

        ver_box.addWidget(self.version_box)

        profile_layout.addWidget(p_title)
        profile_layout.addLayout(user_box)
        profile_layout.addLayout(ver_box)

        self.fabric_checkbox = QCheckBox("Enable Fabric Mod Loader")
        self.fabric_checkbox.setChecked(self.config.get("use_fabric", True))
        profile_layout.addWidget(self.fabric_checkbox)

        home_layout.addWidget(profile_card)
        home_layout.addStretch()

        page_modpacks = QWidget()
        modpacks_layout = QVBoxLayout(page_modpacks)
        modpacks_layout.setSpacing(14)

        mp_title = QLabel("MODPACK MANAGER")
        mp_title.setStyleSheet("font-size: 15px; font-weight: 800; color: #00f0ff; letter-spacing: 1px;")
        modpacks_layout.addWidget(mp_title)

        self.modpack_list_widget = QListWidget()
        modpacks_layout.addWidget(self.modpack_list_widget)

        mp_btn_box = QHBoxLayout()
        self.btn_create_pack = QPushButton("➕ Create Modpack")
        self.btn_create_pack.setObjectName("accent_btn")
        self.btn_create_pack.clicked.connect(self.create_modpack)

        self.btn_select_pack = QPushButton("✅ Set Active Pack")
        self.btn_select_pack.setObjectName("action_btn")
        self.btn_select_pack.clicked.connect(self.set_active_modpack)

        self.btn_del_pack = QPushButton("🗑️ Delete Pack")
        self.btn_del_pack.setObjectName("action_btn")
        self.btn_del_pack.clicked.connect(self.delete_modpack)

        mp_btn_box.addWidget(self.btn_create_pack)
        mp_btn_box.addWidget(self.btn_select_pack)
        mp_btn_box.addWidget(self.btn_del_pack)
        modpacks_layout.addLayout(mp_btn_box)

        page_mods = QWidget()
        mods_layout = QVBoxLayout(page_mods)
        mods_layout.setSpacing(14)

        m_header_box = QHBoxLayout()
        self.m_title = QLabel(f"MODS IN: {self.active_modpack}")
        self.m_title.setStyleSheet("font-size: 15px; font-weight: 800; color: #00f0ff; letter-spacing: 1px;")
        m_header_box.addWidget(self.m_title)
        m_header_box.addStretch()
        
        mods_layout.addLayout(m_header_box)

        self.mod_list_widget = QListWidget()
        mods_layout.addWidget(self.mod_list_widget)

        mod_btn_box = QHBoxLayout()
        self.btn_add_mod = QPushButton("➕ Add .JAR Mod")
        self.btn_add_mod.setObjectName("accent_btn")
        self.btn_add_mod.clicked.connect(self.add_mod_file)

        self.btn_del_mod = QPushButton("🗑️ Remove Selected")
        self.btn_del_mod.setObjectName("action_btn")
        self.btn_del_mod.clicked.connect(self.delete_mod_file)

        self.btn_ref_mod = QPushButton("🔄 Refresh")
        self.btn_ref_mod.setObjectName("action_btn")
        self.btn_ref_mod.clicked.connect(self.refresh_mods_list)

        mod_btn_box.addWidget(self.btn_add_mod)
        mod_btn_box.addWidget(self.btn_del_mod)
        mod_btn_box.addWidget(self.btn_ref_mod)
        mods_layout.addLayout(mod_btn_box)

        page_toggles = QWidget()
        toggles_layout = QVBoxLayout(page_toggles)
        toggles_layout.setSpacing(14)

        t_title = QLabel("BUILT-IN CLIENT MODS & HUDS")
        t_title.setStyleSheet("font-size: 15px; font-weight: 800; color: #00f0ff; letter-spacing: 1px;")
        toggles_layout.addWidget(t_title)

        toggles_card = QFrame()
        toggles_card.setObjectName("card")
        toggles_card_layout = QVBoxLayout(toggles_card)
        toggles_card_layout.setContentsMargins(20, 20, 20, 20)
        toggles_card_layout.setSpacing(14)

        client_mods = [
            ("CPS Display HUD", True),
            ("FPS Boost & Optimization", True),
            ("Keystrokes Overlay", True),
            ("Toggle Sprint", True),
            ("Armor Status HUD", False),
            ("Direction Compass HUD", False),
            ("Motion Blur Shaders", True),
            ("Item Physics 3D", True)
        ]

        for mod_name, default_val in client_mods:
            chk = QCheckBox(mod_name)
            chk.setChecked(default_val)
            toggles_card_layout.addWidget(chk)

        toggles_layout.addWidget(toggles_card)
        toggles_layout.addStretch()

        self.pages.addWidget(page_home)
        self.pages.addWidget(page_modpacks)
        self.pages.addWidget(page_mods)
        self.pages.addWidget(page_toggles)

        content_layout.addWidget(self.pages)

        footer_box = QVBoxLayout()
        footer_box.setSpacing(8)

        self.status_label = QLabel("Ready to launch offline")
        self.status_label.setStyleSheet("color: #8a8a9e; font-size: 12px;")

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(12)

        self.play_btn = QPushButton("LAUNCH OFFLINE GAME")
        self.play_btn.setObjectName("play_btn")
        self.play_btn.clicked.connect(self.start_launch)

        footer_box.addWidget(self.status_label)
        footer_box.addWidget(self.progress_bar)
        footer_box.addWidget(self.play_btn)

        content_layout.addLayout(footer_box)

        main_layout.addWidget(sidebar)
        main_layout.addWidget(content_area)

        central_widget = QWidget()
        central_widget.setLayout(main_layout)
        self.setCentralWidget(central_widget)

        self.refresh_modpacks_list()
        self.refresh_mods_list()

    def load_config(self):
        self.config = {}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    self.config = json.load(f)
            except Exception:
                pass
        self.active_modpack = self.config.get("active_modpack", "Default Pack")
        pack_path = os.path.join(MODPACKS_DIR, self.active_modpack)
        if not os.path.exists(pack_path):
            self.active_modpack = "Default Pack"
            os.makedirs(DEFAULT_PACK, exist_ok=True)

    def save_config(self):
        self.config["username"] = self.username_input.text().strip() or "Player1"
        self.config["version"] = self.version_box.currentText()
        self.config["use_fabric"] = self.fabric_checkbox.isChecked()
        self.config["active_modpack"] = self.active_modpack
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(self.config, f, indent=4)
        except Exception:
            pass

    def switch_page(self, index):
        self.pages.setCurrentIndex(index)
        buttons = [self.btn_nav_home, self.btn_nav_modpacks, self.btn_nav_mods, self.btn_nav_toggles]
        for i, btn in enumerate(buttons):
            btn.setProperty("active", "true" if i == index else "false")
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def open_game_folder(self):
        if sys.platform == "win32":
            os.startfile(GAME_DIR)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", GAME_DIR])
        else:
            subprocess.Popen(["xdg-open", GAME_DIR])

    def refresh_modpacks_list(self):
        self.modpack_list_widget.clear()
        if os.path.exists(MODPACKS_DIR):
            folders = [f for f in os.listdir(MODPACKS_DIR) if os.path.isdir(os.path.join(MODPACKS_DIR, f))]
            for folder in folders:
                display_name = f"📦 {folder} (ACTIVE)" if folder == self.active_modpack else f"📦 {folder}"
                self.modpack_list_widget.addItem(display_name)

    def create_modpack(self):
        name, ok = QInputDialog.getText(self, "New Modpack", "Enter Modpack Name:")
        if ok and name.strip():
            clean_name = name.strip()
            new_path = os.path.join(MODPACKS_DIR, clean_name)
            if not os.path.exists(new_path):
                os.makedirs(new_path, exist_ok=True)
                self.active_modpack = clean_name
                self.active_pack_display.setText(clean_name)
                self.m_title.setText(f"MODS IN: {clean_name}")
                self.save_config()
                self.refresh_modpacks_list()
                self.refresh_mods_list()

    def set_active_modpack(self):
        selected = self.modpack_list_widget.currentItem()
        if not selected:
            return
        raw_name = selected.text().replace("📦 ", "").replace(" (ACTIVE)", "").strip()
        self.active_modpack = raw_name
        self.active_pack_display.setText(raw_name)
        self.m_title.setText(f"MODS IN: {raw_name}")
        self.save_config()
        self.refresh_modpacks_list()
        self.refresh_mods_list()

    def delete_modpack(self):
        selected = self.modpack_list_widget.currentItem()
        if not selected:
            return
        raw_name = selected.text().replace("📦 ", "").replace(" (ACTIVE)", "").strip()
        if raw_name == "Default Pack":
            QMessageBox.warning(self, "Warning", "Cannot delete the Default Pack!")
            return
        
        target_dir = os.path.join(MODPACKS_DIR, raw_name)
        if os.path.exists(target_dir):
            shutil.rmtree(target_dir)
            if self.active_modpack == raw_name:
                self.active_modpack = "Default Pack"
                self.active_pack_display.setText("Default Pack")
                self.m_title.setText("MODS IN: Default Pack")
            self.save_config()
            self.refresh_modpacks_list()
            self.refresh_mods_list()

    def refresh_mods_list(self):
        self.mod_list_widget.clear()
        active_dir = os.path.join(MODPACKS_DIR, self.active_modpack)
        os.makedirs(active_dir, exist_ok=True)
        files = [f for f in os.listdir(active_dir) if f.endswith(".jar")]
        if files:
            self.mod_list_widget.addItems(files)
        else:
            self.mod_list_widget.addItem("No .jar mods in this modpack.")

    def add_mod_file(self):
        active_dir = os.path.join(MODPACKS_DIR, self.active_modpack)
        files, _ = QFileDialog.getOpenFileNames(
            self, "Select Mod (.jar)", "", "Minecraft Mods (*.jar)"
        )
        for f in files:
            shutil.copy(f, os.path.join(active_dir, os.path.basename(f)))
        self.refresh_mods_list()

    def delete_mod_file(self):
        selected = self.mod_list_widget.currentItem()
        if not selected or selected.text() == "No .jar mods in this modpack.":
            return
        
        active_dir = os.path.join(MODPACKS_DIR, self.active_modpack)
        file_path = os.path.join(active_dir, selected.text())
        if os.path.exists(file_path):
            os.remove(file_path)
            self.refresh_mods_list()

    def start_launch(self):
        self.save_config()
        username = self.username_input.text().strip() or "Player1"
        version = self.version_box.currentText()
        use_fabric = self.fabric_checkbox.isChecked()
        active_pack_path = os.path.join(MODPACKS_DIR, self.active_modpack)

        self.play_btn.setEnabled(False)
        self.username_input.setEnabled(False)
        self.version_box.setEnabled(False)
        self.fabric_checkbox.setEnabled(False)

        self.worker = LaunchWorker(username, version, use_fabric, active_pack_path)
        self.worker.status_signal.connect(self.status_label.setText)
        self.worker.progress_signal.connect(self.progress_bar.setValue)
        self.worker.finished_signal.connect(self.on_launch_ready)
        self.worker.error_signal.connect(self.on_error)
        self.worker.start()

    def on_launch_ready(self, command):
        self.status_label.setText("Game window opening...")
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