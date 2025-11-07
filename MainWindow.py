import sys
import os
import requests
import json
import webbrowser

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QTextEdit, QProgressBar, QLineEdit, QFileDialog, QMessageBox, QSplashScreen,
    QCheckBox
)

from WorkerThread import WorkerThread

# -------------------------
# 主視窗部分
# -------------------------

class MainWindow(QWidget):
    def __init__(self, version, serverUrl):

        super().__init__()

        self.setWindowTitle("Minecraft 模組同步器 (Created by:幽影桜)")
        self.resize(900, 650)



        self.client_version = version
        layout = QVBoxLayout()

        self.version_label = QLabel(f"客戶端版本: {self.client_version}")
        layout.addWidget(self.version_label)

        server_layout = QHBoxLayout()
        server_layout.addWidget(QLabel("伺服器 URL:"))
        self.server_input = QLineEdit(serverUrl)
        server_layout.addWidget(self.server_input)
        layout.addLayout(server_layout)

        path_layout = QHBoxLayout()
        path_layout.addWidget(QLabel("Minecraft 版本資料夾:"))
        exe_dir = os.path.dirname(sys.executable)
        self.path_input = QLineEdit(exe_dir)
        path_layout.addWidget(self.path_input)
        browse_btn = QPushButton("瀏覽")
        browse_btn.clicked.connect(self.choose_folder)
        path_layout.addWidget(browse_btn)
        layout.addLayout(path_layout)

        # 新增：僅同步新增設定檔的選項（不改變其他功能）
        self.only_add_config_checkbox = QCheckBox("僅同步新增設定檔 (config)")
        self.only_add_config_checkbox.setToolTip("啟用後：若本地已存在同名 config 檔案，將不會覆蓋或刪除該檔案，只會下載伺服器上本地缺少的檔案。")
        layout.addWidget(self.only_add_config_checkbox)

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        layout.addWidget(self.log_area)

        layout.addWidget(QLabel("整體進度"))
        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)

        layout.addWidget(QLabel("單檔進度"))
        self.file_progress_bar = QProgressBar()
        layout.addWidget(self.file_progress_bar)

        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("開始同步")
        self.start_btn.clicked.connect(self.start_sync)
        btn_layout.addWidget(self.start_btn)

        self.pause_btn = QPushButton("暫停")
        self.pause_btn.clicked.connect(self.pause_resume)
        btn_layout.addWidget(self.pause_btn)

        self.clear_btn = QPushButton("清空訊息")
        self.clear_btn.clicked.connect(lambda: self.log_area.clear())
        btn_layout.addWidget(self.clear_btn)

        layout.addLayout(btn_layout)
        self.setLayout(layout)

        self.worker = None

    def choose_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "選擇 Minecraft 版本資料夾", os.getcwd())
        if folder:
            self.path_input.setText(folder)
            mods_servermods = os.path.join(folder, "mods", "servermods")
            mods_clientmods = os.path.join(folder, "mods", "clientmods")
            # 確保兩個目錄都存在（servermods 為伺服器 mods 嚴格同步目的地；clientmods 為伺服器 clientmods 的對應）
            os.makedirs(mods_servermods, exist_ok=True)
            os.makedirs(mods_clientmods, exist_ok=True)
            QMessageBox.information(
                self, "提示",
                f"已選擇版本資料夾：\n{folder}\n\n"
                f"同步規則：\n"
                f"• mods (伺服器) → {mods_servermods} (嚴格同步，且不可多也不可少)\n"
                f"• clientmods (伺服器) → {mods_clientmods}\n"
                f"• needsmods (伺服器) → {os.path.join(folder, 'mods')}\n"
                f"• 其他資料夾 → {folder}/<foldername>/"
            )


    def start_sync(self):
        self.start_btn.setEnabled(False)
        mc_version_path = self.path_input.text().strip()
        if not mc_version_path:
            QMessageBox.warning(self, "錯誤", "請先選擇 Minecraft 版本資料夾。")
            self.start_btn.setEnabled(True)
            return
        self.worker = WorkerThread(self.server_input.text().strip(), mc_version_path)
        # 傳遞僅新增設定檔選項（不改動其他行為）
        self.worker.only_add_config = self.only_add_config_checkbox.isChecked()

        self.worker.log_signal.connect(self.append_log)
        self.worker.progress_signal.connect(self.update_progress)
        self.worker.total_files_signal.connect(self.set_total_files)
        self.worker.file_progress_signal.connect(self.update_file_progress)
        self.worker.finished.connect(lambda: self.start_btn.setEnabled(True))
        self.worker.start()

    def pause_resume(self):
        if self.worker:
            self.worker.pause()
            if self.worker._pause_flag:
                self.pause_btn.setText("繼續")
                self.append_log("⏸ 已暫停下載")
            else:
                self.pause_btn.setText("暫停")
                self.append_log("▶ 已繼續下載")

    def append_log(self, text):
        self.log_area.append(text)
        self.log_area.verticalScrollBar().setValue(self.log_area.verticalScrollBar().maximum())

    def update_progress(self, value):
        self.progress_bar.setValue(value)

    def set_total_files(self, total):
        self.progress_bar.setMaximum(total)

    def update_file_progress(self, value):
        self.file_progress_bar.setValue(value)

    def check_update(self):
        try:
            version_url = f"{self.server_input.text().strip()}/clientupdate/version.txt"
            r = requests.get(version_url, timeout=10)
            if r.status_code != 200:
                self.append_log("⚠ 無法取得最新版本號")
                return
            version_info = json.loads(r.text)
            latest_version = version_info.get("version", "0.0.0")
            note_text = version_info.get("note", "")
            if latest_version != self.client_version:
                self.append_log(f"🔔 發現新版本: {latest_version} (目前: {self.client_version})")
                msg = QMessageBox(self)
                msg.setWindowTitle("更新提示")
                msg.setText(f"有新版本可用: {latest_version}\n\n更新內容:\n{note_text}")
                msg.setIcon(QMessageBox.Icon.Information)
                msg.setStandardButtons(QMessageBox.StandardButton.Ok)
                msg.buttonClicked.connect(lambda _: webbrowser.open(f"{self.server_input.text().strip()}/clientupdate"))
                msg.show()  # 非阻塞
            else:
                self.append_log("✅ 已是最新版本")
        except Exception as e:
            self.append_log(f"❌ 檢查更新失敗: {e}")
