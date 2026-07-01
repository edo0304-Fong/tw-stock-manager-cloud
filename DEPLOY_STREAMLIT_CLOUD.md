# Streamlit Cloud 部署教學（個人雲端版）

## 重要提醒

不要把自己的 Gmail 密碼、Gmail 應用程式密碼、API key 寫進 GitHub。請使用 Streamlit Cloud 的 Secrets。
若 GitHub repo 是公開的，也不要把真實持股 CSV 放進 repo；部署後在 App 內用「CSV 匯入」。

## 1. 建立 GitHub Repo

1. 到 GitHub 新增 repository，例如 `tw-stock-manager-cloud`。
2. 建議先設為 **Private**。
3. 上傳本資料夾內所有檔案。
4. 確認 GitHub repo 根目錄有：
   - `app.py`
   - `requirements.txt`
   - `modules/`
   - `.streamlit/config.toml`

## 2. 設定 Streamlit Cloud

1. 登入 Streamlit Cloud。
2. 點 **Create app / New app**。
3. 選你的 GitHub repo。
4. Main file path 填：`app.py`。
5. App URL 可自訂，例如 `tw-stock-manager`。
6. 部署前或部署後進入 **Settings → Secrets**。

## 3. Secrets 範例

至少建議先設定登入密碼：

```toml
APP_PASSWORD = "請改成你的密碼"
```

如果要 Gmail 到價提醒，再加入：

```toml
GMAIL_USER = "your_email@gmail.com"
GMAIL_APP_PASSWORD = "你的 Gmail 應用程式密碼"
ALERT_TO_EMAIL = "your_email@gmail.com"
```

## 4. 部署後使用

1. 用手機開 Streamlit 給你的網址。
2. 輸入 `APP_PASSWORD` 登入。
3. 到「CSV 匯入」上傳你的持股 CSV。
4. 到「持股總覽」檢查市值與損益。
5. 到「提醒設定」設定到價提醒。

## 5. 關於資料保存

目前 v6 Cloud Ready 仍是個人 MVP：資料會寫在 Streamlit 執行環境的 `data/` CSV 檔。
這對個人試用可行，但雲端服務重啟、重新部署或休眠後，資料可能需要重新匯入。

比較穩的下一步是把資料改存：

- Google Sheets：最簡單，適合個人用。
- Supabase PostgreSQL：比較正式，適合未來多人或長期使用。

## 6. 手機使用建議

手機版建議先用：

- 每日健檢
- 每日趨勢雷達
- 市場排行
- 持股總覽
- 新聞與討論

CSV 匯入、交易紀錄大量修改，仍建議在電腦操作。
