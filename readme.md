# 關於此項目
此程序受chyuaner的python-minecraft-mods-sync啟發
用於解決模組服務器玩家 
再加入服務器時 偶爾會因為服務器修改模組 導致模組不同步無法加入的問題

此程序重寫並還原了該項目原有的大部分功能 並增加了資料夾同步模式 與多重模組資料夾同步 並依靠mod_set完成模組分類與子資料夾載入

# 已實現功能
mods資料夾同步

mods及子資料夾同步

對於mods內資料夾套用不同的同步規則(可多不可少/不可多不可少)

mods資料夾外 位於版本資料夾下的資料夾同步(如:config/kubejs等)

對於部分資料夾(如kubejs/config)在比對時 會檢查檔案md5 確保檔案內容完全一致 

(其中的config為可選 預設啟用 將跳過已存在的同名檔)





# 如何編譯此程序:
`pyinstaller --noconsole --onefile --icon="img/v8dev-frrsi-001.ico" --add-data "img/loading.png;img" main.py`

# 啟動參數相關
--reconf 程序啟動時 取消勾選"僅同步新增設定檔功能"

--auto 程序啟動後 自動開始同步 並於同步完成後 自動關閉程序

--dir "path" 程序啟動時 自動修改預設同步位置 

範例:
`.\main.exe --dir "C:\Users\user\Desktop\PCL 正式版 2.10.0\.minecraft\versions\1.20.1-Forge_47.4.10"`











# git相關

初始化版本庫	`git init`	在當前資料夾建立新的 Git 儲存庫

檢查狀態	`git status`	顯示修改、暫存、未追蹤的檔案

加入檔案到暫存區	`git add 檔名`	加入單一檔案

加入全部變更	`git add .`	加入所有檔案變更

提交變更	`git commit -m "提交訊息"`	建立新的版本

修改上一筆提交訊息	`git commit --amend -m "新訊息"`	覆蓋上一次 commit 訊息
