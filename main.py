import sys
import os

from MainWindow import MainWindow

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QTextEdit, QProgressBar, QLineEdit, QFileDialog, QMessageBox, QSplashScreen,
    QCheckBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap

# -------------------------
# 主程式 + Splash
# -------------------------
# -------------------------
# 主程式 + Splash + 參數處理
# -------------------------

serverUrl = "http://modapi.barian.moe/"
# serverUrl = "https://mc-api.yuaner.tw/"
version = "1.2.2"  # 更新版本
localPath = ""

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
        window = MainWindow(version, serverUrl)

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


