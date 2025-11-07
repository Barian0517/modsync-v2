import sys
import os
import hashlib
import requests
import time
import concurrent.futures
import shutil
import zipfile
import json
import webbrowser
from urllib.parse import quote

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QTextEdit, QProgressBar, QLineEdit, QFileDialog, QMessageBox, QSplashScreen,
    QCheckBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap

version = "1.2.2"  # 更新版本

# -------------------------
# 同步執行緒
# -------------------------
class WorkerThread(QThread):
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    total_files_signal = pyqtSignal(int)
    file_progress_signal = pyqtSignal(int)

    def __init__(self, server_url, mc_version_path):
        super().__init__()
        self.server_url = server_url
        self.mc_version_path = mc_version_path
        os.makedirs(self.mc_version_path, exist_ok=True)
        self._pause_flag = False
        self._stop_flag = False
        # 新增：是否僅同步新增的 config 檔（存在則不覆蓋、不刪除）
        self.only_add_config = False

    def is_under_config(self, local_abs):
        """
        判斷一個絕對路徑是否位於名為 'config' 的目錄下（任何層級，只要 segment 為 'config' 即認定）。
        這樣可以區分真正的 config 資料夾，而不會僅以字串包含進行判斷。
        """
        parts = [p.lower() for p in os.path.normpath(local_abs).split(os.sep)]
        return 'config' in parts

    def run(self):
        self.log_signal.emit(f"開始連線伺服器: {self.server_url}/config_names?json=1")
        try:
            resp = requests.get(f"{self.server_url}/config_names?json=1", timeout=10)
            if resp.status_code != 200:
                self.log_signal.emit(f"❌ 伺服器回傳錯誤代碼: {resp.status_code}")
                return
            folder_names = resp.json()
            self.log_signal.emit(f"✅ 取得資料夾列表: {folder_names}")
        except Exception as e:
            self.log_signal.emit(f"❌ 無法連線伺服器: {e}")
            return

        max_workers = 8
        total_tasks = 0
        all_tasks = []

        for folder in folder_names:
            folder_lower = str(folder).lower()

            # 🟢 特殊規則處理（已更新）
            # 伺服器 "mods"  -> 客戶端 <mc_version_path>/mods/servermods   (嚴格同步)
            # 伺服器 "clientmods" -> 客戶端 <mc_version_path>/mods/clientmods (非嚴格)
            # 伺服器 "needsmods" -> 客戶端 <mc_version_path>/mods            (非嚴格)
            folder_lower = str(folder).lower()
            if folder_lower == "mods":
                folder_base = os.path.join(self.mc_version_path, "mods", "servermods")
                strict_sync = True
            elif folder_lower == "clientmods":
                folder_base = os.path.join(self.mc_version_path, "mods")
                strict_sync = False
            elif folder_lower == "needmods":
                folder_base = os.path.join(self.mc_version_path, "mods", "clientmods")
                strict_sync = True
            else:
                folder_base = os.path.join(self.mc_version_path, folder)
                strict_sync = False

            os.makedirs(folder_base, exist_ok=True)
            self.log_signal.emit(f"\n🔍 檢查伺服端資料夾: {folder} -> 本地: {folder_base}")

            # 如果為 config 並且啟用了 only_add_config，顯示提示
            if folder_lower == "config" and self.only_add_config:
                self.log_signal.emit("⚙ 已啟用『僅同步新增設定檔』模式，對於已存在的檔案不會覆蓋或刪除，只會補上缺失檔案。")

            # 取得伺服器該資料夾的檔案清單
            try:
                r = requests.get(f"{self.server_url}/{folder}/?json=1", timeout=10)
                if r.status_code != 200:
                    self.log_signal.emit(f"❌ 無法取得 {folder} 檔案列表: HTTP {r.status_code}")
                    continue
                server_files = r.json()
                self.log_signal.emit(f"✅ {folder} 伺服器檔案列表取得成功")
            except Exception as e:
                self.log_signal.emit(f"❌ 取得 {folder} 檔案列表失敗: {e}")
                continue

            # 比對檔案
            if strict_sync:
                tasks = self.collect_strict_tasks(server_files, folder_base)
            else:
                tasks = self.collect_download_tasks(server_files, folder_base)

            total_files = len(tasks)
            total_server = self.count_server_files(server_files)
            ratio = (total_files / total_server) if total_server else 0
            self.log_signal.emit(f"{folder}: 缺失/不同檔案比例 {ratio:.0%}")

            # ✅ 整包下載條件（缺失率達 60%，且非嚴格同步）
            if ratio >= 0.6:
                self.log_signal.emit(f"⚠ {folder}: 缺失率過高 ({ratio:.0%})，重新驗證伺服器檔案列表...")
                try:
                    # 再請求一次伺服器檔案列表，避免第一次資料異常
                    verify_resp = requests.get(f"{self.server_url}/{folder}/?json=1", timeout=10)
                    if verify_resp.status_code == 200:
                        new_server_files = verify_resp.json()
                        new_total_files = self.count_server_files(new_server_files)
                        new_tasks = self.collect_strict_tasks(new_server_files, folder_base)
                        new_ratio = (len(new_tasks) / new_total_files) if new_total_files else 0
                        self.log_signal.emit(f"🔁 重新驗證後缺失率: {new_ratio:.0%}")
                        # 若重新驗證後仍高於 50%，才進行整包
                        if new_ratio < 0.5:
                            self.log_signal.emit(f"✅ 驗證後正常，跳過整包下載。")
                            tasks = new_tasks
                            ratio = new_ratio
                        else:
                            self.log_signal.emit(f"📦 {folder}: 缺失率仍過高 ({new_ratio:.0%})，自動整包下載中...")
                            zip_url = f"{self.server_url}/{folder}?download=1"
                            self.download_and_extract_zip(zip_url, folder_base)
                            tasks = self.collect_strict_tasks(new_server_files, folder_base)
                            if tasks:
                                self.log_signal.emit(f"⚙ 整包後仍有 {len(tasks)} 個檔案需要修正")
                                for file_path in tasks:
                                    self.download_file(file_path, folder, folder_base)
                            continue
                    else:
                        self.log_signal.emit(f"⚠ 重新驗證伺服器列表失敗，HTTP {verify_resp.status_code}，改用整包下載。")
                        zip_url = f"{self.server_url}/{folder}?download=1"
                        self.download_and_extract_zip(zip_url, folder_base)
                        continue
                except Exception as e:
                    self.log_signal.emit(f"⚠ 重新驗證伺服器列表時發生錯誤: {e}，改用整包下載。")
                    zip_url = f"{self.server_url}/{folder}?download=1"
                    self.download_and_extract_zip(zip_url, folder_base)
                    continue

            if tasks:
                self.log_signal.emit(f"{folder}: 需要下載 {len(tasks)} 個檔案")
                for file_path in tasks:
                    all_tasks.append((folder, file_path, folder_base))
                    total_tasks += 1
            else:
                self.log_signal.emit(f"{folder}: 所有檔案完整")

        if total_tasks == 0 and not all_tasks:
            self.log_signal.emit("🎉 所有檔案已完整")
            return

        self.total_files_signal.emit(total_tasks)
        completed = 0

        # -------------------------
        # 執行下載並自動重新驗證
        # -------------------------
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = []
            for folder, file_path, folder_base in all_tasks:
                futures.append(executor.submit(self.download_and_verify, folder, file_path, folder_base))
            for future in concurrent.futures.as_completed(futures):
                completed += 1
                self.progress_signal.emit(completed)

    # -------------------------
    # 快速檢查檔案
    # -------------------------
    def get_md5(self, file_path):
        hash_md5 = hashlib.md5()
        try:
            with open(file_path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            return hash_md5.hexdigest()
        except Exception as e:
            self.log_signal.emit(f"❌ 計算 MD5 失敗: {file_path}, {e}")
            return None

    def count_server_files(self, server_dict):
        total = 0
        for v in server_dict.values():
            if isinstance(v, dict):
                total += self.count_server_files(v)
            else:
                total += 1
        return total

    # -------------------------
    # 快速比對下載檔案
    # -------------------------
    def collect_download_tasks(self, server_dict, local_base, rel_path=""):
        tasks = []
        futures = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            for name, value in server_dict.items():
                local_rel = f"{rel_path}/{name}" if rel_path else name
                local_abs = os.path.join(local_base, local_rel.replace("/", os.sep))
                if isinstance(value, dict):
                    os.makedirs(local_abs, exist_ok=True)
                    tasks.extend(self.collect_download_tasks(value, local_base, local_rel))
                else:
                    # 將檔案檢查交由 check_file，並在它內部處理 only_add_config 的判斷
                    futures.append(executor.submit(self.check_file, local_abs, local_rel, value))
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                if result:
                    tasks.append(result)
        return tasks

    # -------------------------
    # mods/servermods 嚴格同步
    # -------------------------
    def collect_strict_tasks(self, server_dict, local_base, rel_path=""):
        tasks = []
        server_files_set = set()
        is_config_base = os.path.basename(os.path.normpath(local_base)).lower() == 'config'

        futures = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            def process_file(name, value, rel):
                local_rel = f"{rel}/{name}" if rel else name
                local_abs = os.path.join(local_base, local_rel.replace("/", os.sep))
                if isinstance(value, dict):
                    os.makedirs(local_abs, exist_ok=True)
                    return self.collect_strict_tasks(value, local_base, local_rel)
                else:
                    server_files_set.add(local_rel)
                    local_md5 = self.get_md5(local_abs) if os.path.exists(local_abs) else None
                    if local_md5 is not None and self.only_add_config and is_config_base:
                        self.log_signal.emit(f"[跳過覆蓋] config 模式：保留本地已有檔案 {local_rel}")
                        return []
                    if local_md5 != value:
                        if os.path.exists(local_abs):
                            try:
                                os.remove(local_abs)
                            except Exception:
                                pass
                        return [local_rel]
                    return []

            for name, value in server_dict.items():
                futures.append(executor.submit(process_file, name, value, rel_path))

            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                if result:
                    tasks.extend(result)

        # 多餘檔案刪除邏輯保持不變
        ...

        # 刪除多餘檔案（若為 config 且啟用了僅新增模式，跳過刪除）
        if not (self.only_add_config and is_config_base):
            for root, dirs, files in os.walk(local_base):
                for f in files:
                    rel_path_local = os.path.relpath(os.path.join(root, f), local_base).replace("\\", "/")
                    if rel_path_local not in server_files_set:
                        self.log_signal.emit(f"[多餘檔案刪除] {rel_path_local}")
                        try:
                            os.remove(os.path.join(local_base, rel_path_local))
                        except Exception as e:
                            self.log_signal.emit(f"❌ 刪除失敗 {rel_path_local}: {e}")
        else:
            self.log_signal.emit("🛡 已啟用『僅新增設定檔』，跳過多餘檔案刪除。")
        return tasks

    def check_file(self, local_abs, local_rel, server_md5):
        # 如果本地不存在 -> 需要下載
        if not os.path.exists(local_abs):
            self.log_signal.emit(f"[檔案缺失] {local_rel}")
            return local_rel

        # 如果啟用了 only_add_config 且該檔案位於 config 下 -> 跳過覆蓋與 MD5 檢查（保留本地）
        if self.only_add_config and self.is_under_config(local_abs):
            self.log_signal.emit(f"[跳過檢查] config 模式且檔案已存在，保留本地：{local_rel}")
            return None

        local_md5 = self.get_md5(local_abs)
        if local_md5 != server_md5:
            self.log_signal.emit(f"[MD5 不同] {local_rel}")
            try:
                os.remove(local_abs)
            except Exception:
                pass
            return local_rel
        return None

    def download_file(self, file_path, folder, local_base, max_retries=3):
        url = f"{self.server_url}/{folder}/{quote(file_path)}?download=1"
        local_path = os.path.join(local_base, file_path.replace("/", os.sep))
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        for attempt in range(max_retries):
            if self._stop_flag:
                return False
            while self._pause_flag:
                time.sleep(0.3)
            try:
                self.log_signal.emit(f"⬇ 開始下載 {folder}/{file_path} (嘗試 {attempt+1})")
                r = requests.get(url, stream=True, timeout=15)
                if r.status_code not in (200, 206):
                    self.log_signal.emit(f"❌ HTTP {r.status_code} {folder}/{file_path}")
                    continue
                total_size = int(r.headers.get('Content-Length', 0))
                downloaded = 0
                with open(local_path, "wb") as f:
                    for chunk in r.iter_content(65536):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            percent = int(downloaded / total_size * 100) if total_size else 100
                            self.file_progress_signal.emit(percent)
                self.log_signal.emit(f"✅ 下載完成 {folder}/{file_path}")
                self.file_progress_signal.emit(100)
                return True
            except Exception as e:
                self.log_signal.emit(f"❌ 下載錯誤 {folder}/{file_path}: {e}")
            time.sleep(1)
        self.log_signal.emit(f"❌ 最終下載失敗 {folder}/{file_path}")
        return False

    # -------------------------
    # 下載後自動驗證
    # -------------------------
    def download_and_verify(self, folder, file_path, local_base):
        if self.download_file(file_path, folder, local_base):
            # 下載後立即重新驗證 MD5
            local_abs = os.path.join(local_base, file_path.replace("/", os.sep))
            server_md5 = None
            try:
                r = requests.get(f"{self.server_url}/{folder}/?json=1", timeout=10)
                server_dict = r.json()
                server_md5 = self.find_md5_in_dict(server_dict, file_path)
            except Exception as e:
                self.log_signal.emit(f"❌ 重新取得伺服器 MD5 失敗: {file_path}, {e}")
            if server_md5:
                local_md5 = self.get_md5(local_abs)
                if local_md5 != server_md5:
                    self.log_signal.emit(f"⚠ 下載後 MD5 仍不同，重新下載 {file_path}")
                    self.download_file(file_path, folder, local_base)
        return True

    def find_md5_in_dict(self, d, target_path, rel=""):
        for k, v in d.items():
            current_rel = f"{rel}/{k}" if rel else k
            if isinstance(v, dict):
                md5 = self.find_md5_in_dict(v, target_path, current_rel)
                if md5:
                    return md5
            elif current_rel == target_path:
                return v
        return None

    def download_and_extract_zip(self, zip_url, extract_to):
        zip_local = os.path.join(os.getcwd(), "temp.zip")
        try:
            self.log_signal.emit(f"📦 下載 ZIP: {zip_url}")
            r = requests.get(zip_url, stream=True, timeout=30)
            if r.status_code != 200:
                self.log_signal.emit(f"❌ ZIP 下載失敗 HTTP {r.status_code}")
                return
            total_size = int(r.headers.get('Content-Length', 0))
            downloaded = 0
            with open(zip_local, "wb") as f:
                for chunk in r.iter_content(65536):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        percent = int(downloaded / total_size * 100) if total_size else 100
                        self.file_progress_signal.emit(percent)
            self.log_signal.emit("🧩 下載完成，開始解壓縮 ...")
            with zipfile.ZipFile(zip_local, 'r') as zip_ref:
                file_list = zip_ref.infolist()
                for idx, member in enumerate(file_list):
                    zip_ref.extract(member, extract_to)
                    percent = int((idx+1) / len(file_list) * 100)
                    self.file_progress_signal.emit(percent)
            self.log_signal.emit("✅ 解壓完成。")
        except Exception as e:
            self.log_signal.emit(f"❌ 下載或解壓失敗: {e}")
        finally:
            if os.path.exists(zip_local):
                os.remove(zip_local)

    def pause(self):
        self._pause_flag = not self._pause_flag

# -------------------------
# 主視窗部分
# -------------------------
class MainWindow(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Minecraft 模組同步器 (Created by:幽影桜)")
        self.resize(900, 650)



        self.client_version = version
        layout = QVBoxLayout()

        self.version_label = QLabel(f"客戶端版本: {self.client_version}")
        layout.addWidget(self.version_label)

        server_layout = QHBoxLayout()
        server_layout.addWidget(QLabel("伺服器 URL:"))
        self.server_input = QLineEdit("http://modapi.barian.moe/")
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




# -------------------------
# 主程式 + Splash
# -------------------------
# -------------------------
# 主程式 + Splash + 參數處理
# -------------------------
if __name__ == "__main__":
    app = QApplication(sys.argv)

    # ✅ 解析命令列參數
    args = sys.argv[1:]

    auto_mode = "--auto" in args
    reconfig_mode = "--reconfig" in args  # 用於取消預設同步 config

    # 預設啟用 config 同步，除非加上 --reconfig
    addconf_mode = not reconfig_mode

    # ✅ 新增：處理 --dir 參數
    # ✅ 新增：處理 --dir 參數（支援含空格的路徑）
    dir_path = None
    for i, arg in enumerate(args):
        if arg == "--dir" and i + 1 < len(args):
            # 取出後面所有非參數（不以 -- 開頭）的字串組成完整路徑
            path_parts = []
            for j in range(i + 1, len(args)):
                if args[j].startswith("--"):
                    break
                path_parts.append(args[j])
            dir_path = " ".join(path_parts).strip('"')  # 移除多餘引號
            break


    base_path = getattr(sys, '_MEIPASS', os.path.abspath("."))
    splash_path = os.path.join(base_path, "img", "loading.png")
    splash_pix = QPixmap(splash_path) if os.path.exists(splash_path) else QPixmap()
    splash = QSplashScreen(splash_pix, Qt.WindowType.WindowStaysOnTopHint)
    splash.setWindowFlag(Qt.WindowType.FramelessWindowHint)
    splash.showMessage("載入中...", Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignHCenter, Qt.GlobalColor.white)
    splash.show()


    def start_main():
        window = MainWindow()

        # ✅ 預設勾選「僅同步新增設定檔」
        window.only_add_config_checkbox.setChecked(True)
        window.append_log("⚙ 預設勾選『僅同步新增設定檔』")

        # ✅ 若使用 --reconfig，取消預設勾選
        if reconfig_mode:
            window.only_add_config_checkbox.setChecked(False)
            window.append_log("⚠ 啟用參數 --reconfig：取消預設『僅同步新增設定檔』")

        # ✅ 若使用 --dir，設定預設同步路徑
        if dir_path:
            abs_dir = os.path.abspath(dir_path)
            window.path_input.setText(abs_dir)
            window.append_log(f"📁 啟用參數 --dir：同步路徑設定為 {abs_dir}")

        window.show()
        splash.finish(window)
        window.check_update()  # 確保更新提示不被 Splash 擋住

        # ✅ 若使用 --auto，自動開始同步並於完成後自動關閉
        if auto_mode:
            window.append_log("🤖 啟用參數 --auto：自動開始同步")
            window.start_sync()

            # 監聽執行緒完成後自動關閉
            def close_when_done():
                window.append_log("✅ 同步完成，自動關閉中 ...")
                QTimer.singleShot(1500, app.quit)

            def connect_auto_close():
                if window.worker:
                    window.worker.finished.connect(close_when_done)
                else:
                    QTimer.singleShot(100, connect_auto_close)

            connect_auto_close()

    QTimer.singleShot(100, start_main)
    sys.exit(app.exec())


