# 小黑的永恆插件管理器

替《魔獸世界：永恆》安裝、更新整合插件，保留可合併的繁中與本機修改。

從 [最新版本](https://github.com/littleblackmann/wow-forever-addon-updater/releases/latest) 下載
`XiaoHeiForeverUpdater-v1.1.3.zip`（或後續新版 ZIP），解壓到桌面等可寫入的資料夾，開啟 exe。
不需要另外安裝 Python 或 Git。

1. 按「選擇資料夾」，選裡面有 `_forever_` 的 `World of Warcraft` 資料夾。
2. 畫面會顯示插件目的地：`World of Warcraft\_forever_\Interface\AddOns`。
3. 關閉遊戲，再按「一鍵更新遊戲插件」；缺少的整合插件會自動補裝。

兩種更新分別處理：

- **一鍵更新遊戲插件**：同步插件清單、繁中和總入口，再從作者正式來源下載遊戲插件。
- **更新管理器介面（UI）**：只有管理器程式有新版才會啟用，下載驗證後自動重新開啟。

整合清單放在 `catalog` 發行版，管理器介面使用一般版本發行版；新增插件不必重發介面程式。
GitHub 斷線時沿用上次驗證成功的清單。插件下載與查版仍需要網路。

請保留管理器旁的 `settings.json`、`baselines`／`clients`、`online` 資料夾，
分別保存選定位置、原版 ZIP 與舊翻譯快照，以供下次合併。
使用者角色／帳號的 WTF 設定不在分享包內。

已排除 RestedXP、AmobiCompanion、Forever Quest Pins；目前使用 Questie 與 QuestieDB。
Shortest Path Forever 的 ForeverCore 依賴會一併安裝。
v1.1.1修正管理器更新後的自動重開；從v1.1.0第一次升級若沒自動開啟，手動再點exe即可，遊戲插件不需要重裝。
遇到衝突、無適用版本、依賴缺少或驗證失敗時，管理器會顯示原因並保留現況。

整合中的第三方插件與繁中檔案保留原作者授權，來源見插件清單；管理器從作者發行頁下載原版。
維護與發布步驟見 [發布說明](發布說明.md)。

重新解壓管理器、或接手已裝插件的遊戲時，v1.1.2會從作者來源補取與本機現有版本一致的舊版原版ZIP，驗證後再保留修改升級。找不到可信舊版或驗證失敗會保留現況，不把本機檔案當原版。

v1.1.3為GitHub版本資料加上5分鐘快取；達到API額度上限時遵守重試時間，改讀同一作者的官方發布頁，取得下載來源、精確大小與SHA256後照常驗證。release-cache只保存公開發行資料與冷卻時間，不包含帳密或金鑰，不需登入。
