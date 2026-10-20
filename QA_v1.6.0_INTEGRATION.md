# v1.6.0 Integration QA / 修正紀錄

日期：2026-10-20（Asia/Taipei）

## 範圍與環境界線
- 整合分支：`prepare-v1.6.0-integration`，自正式版 main 的 `837aa67` 建立。
- 不修改 main、v1.3.0-test、Railway production/staging、線上資料庫或 Bucket。
- 此分支尚未部署，且尚未取得使用者部署許可。
- 整合提交 `4dc5c2f`：以 main 為父提交導入 16 個測試站新增／修改檔案；保留正式版其餘檔案。

## 確認的問題與修正
1. **版本預設值過舊**：測試站 server.py 的 `APP_VERSION` 預設為 v1.4.0，內頁也寫 v1.4.0 測試版。
   - 在整合分支調整預設版本 v1.6.0、頁面標籤為「正式發布準備版 v1.6.0」。Railway APP_VERSION 的真實值無法透過目前連線讀取；上線前仍須校對。
2. **整站還原中途失敗的附件殘留風險**：原 `restore_backup.py` 先寫入新附件 key，再切換資料庫；發生例外時新物件可能孤立。
   - `02b9140`：記錄成功寫入的新 key，還原例外時反向刪除新 key；不動原有 key。Bucket 刪除若再次失敗，會留下日誌，仍需人工檢查與回收策略。
   - `efe30fa`：新增 `test_failed_restore_reclaims_staged_local_attachments`，檢查資料庫切換前失敗時本機附件不殘留。
3. **尚未驗證的 ZIP 非預期項目與極端情境**：原程式已檢查路徑、檔案數、解壓上限、SHA-256、資料庫結構與外鍵。尚未執行各項壓縮封存故障注入測試，未視為已修正或測試通過。

## 檢查狀態
- 已完成：GitHub tree/blob 比對；整合分支 HEAD 相對 main ahead 1/behind 0（首次整合提交時）；修改後程式碼重新讀取與人工核對縮排、例外清理流程；權限 staging 閘門程式碼確認。
- 未完成：在本地或 CI 真正執行 `python -m unittest` 與 Node.js .cjs 測試；附件及資料庫端對端還原；Railway APP_VERSION 的實際值確認。
- 原因：目前工具的容器無法連線下載 GitHub 專案，連接器沒有提供遠端測試執行功能；不可宣稱已通過自動化測試。

## 下一步（部署前）
1. 於允許執行測試的隔離環境跑 Python/Node 回歸套件，修復失敗項目。
2. 驗證 Bucket 上傳中斷、刪除失敗、安全副本空間不足及還原交易失敗。
3. 檢查預覽/下載、一般使用者與管理員權限、備份/還原的端對端流程。
4. 經使用者明確同意後，才部署整合分支至 Railway 測試站；正式站須另行取得許可。

## 2026-10-20 CI 實測追蹤
- 初次 GitHub Actions [39451894600](https://github.com/anselliu-1/XLeRobot/actions/runs/39451894600)：Python 成功；Node.js 回歸測試失敗，`test_approved_ui.cjs` 仍預期 ISO `T` 分隔符，但新日期選擇器回傳空白分隔的 24 小時時間。
- 修正提交 `5f8011e`：更新測試預期為 `2026-10-20 13:00`，不改動既有已確認的日期 UI 行為。
- 第二次執行 [39452216109](https://github.com/anselliu-1/XLeRobot/actions/runs/39452216109)：日期測試成功，下一個失敗為 `test_review_ui.cjs` 仍預期超額附件會立即被忽略；新版 UI 是保留待送列表、標紅錯誤並禁止送出。
- 修正提交 `ac8b55a`：更新附件測試，明確驗證 50MB 上限、20 個檔案限制及手動移除後復原。
- 最新執行 [39452355550](https://github.com/anselliu-1/XLeRobot/actions/runs/39452355550)：**Python tests 成功、Node tests 成功**，包括 Python compileall、unittest discover、JavaScript node --check 及 .cjs 回歸檢查。
- 以上為隔離環境 CI 成果，尚不代表 Railway 測試站端對端、雲端 Bucket 清理或瀏覽器實測驗收通過。CI 驗證期間**沒有 Railway 部署、沒有合併 main**。

## 待使用者授權的下一步
可以提出將整合分支部署至 **Railway 測試站** 進行整體驗收的申請。執行前須核對測試站 Volume、Bucket、環境變數以及現有資料備份，確認是否替換當前測試部署。**本紀錄不代表部署許可。**

## 2026-10-21 測試站 13/13 驗收與正式站發布前檢查

使用者已於測試網站實際驗收並確認所有 13 項通過，包含：
- 基本檢查（3/3）：網站正常開啟、頁尾版本顯示 v1.6.0、原有資料完整。
- 重點功能（7/7）：分工時程、進度回報、附件上傳、附件預覽與下載、附件限制與錯誤提示、管理員與一般組員權限、Discord 通知。
- 部署安全驗收（3/3）：完整備份下載、還原預覽與取消、手機或平板版面。

版本修正：已在 Railway XLeRobot-Staging 的 APP_VERSION 指定 v1.6.0，部署 `13ad0596-dc68-47f7-86d2-5421f776f320` 顯示 SUCCESS，使用者確認頁尾 v1.6.0。此次為測試站專屬變更。

唯讀發布前確認：
- `main...prepare-v1.6.0-integration`：ahead 8、behind 0；19 個有差異的路徑。整合分支未合併至 main。
- 測試站 GitHub 來源 `prepare-v1.6.0-integration`；正式站 GitHub 來源 `main`，正式站最後部署 SUCCESS。
- Staging Volume ID `b5f00858-e2f0-4173-92f7-845cb4bf4343`；production Volume ID `9a51a0ee-74eb-49df-9bed-9eb51c6045e3`；兩者分離，皆掛載 /data。
- 正式站變數名稱清單沒有 APP_VERSION；必須核對 `main` 的 server.py 預設版本及正式發布策略。Railway OAuth 無法讀取 Bucket 變數實際值，不能單憑變數名稱確認儲存桶完全隔離。
- 使用者完成的是「還原預覽與取消」，**不等於實際套用整站還原成功**。雲端 Bucket 故障注入測試未完成。

尚待正式發布授權之前：正式站完整備份 ZIP 的可用性、正式 Bucket 的備份/還原策略、部署後版本資訊與健康檢查方案、確認不會將測試站資料複製進正式站。

**限制：未取得正式站部署、合併 main 或發佈 GitHub Release 的許可，以上均不得執行。**
