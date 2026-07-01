# 台股持股管理系統 v6 Cloud Ready

這是個人雲端準備版，適合部署到 Streamlit Cloud，讓手機用網址開啟。

## 功能

- 持股 CSV 匯入
- 持股總覽與行情更新
- 買進 / 賣出記帳
- 個股技術分析
- 每日持股健檢
- 每日趨勢雷達
- 市場排行與 ETF 專區
- 個股新聞與討論
- Gmail 價格提醒
- 單人密碼保護
- 手機版面初步優化

## 本機執行

Windows：雙擊 `start_windows_easy.bat`

或：

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Streamlit Cloud 部署

請看：`DEPLOY_STREAMLIT_CLOUD.md`

## 資安提醒

- 不要把 `.streamlit/secrets.toml` 上傳 GitHub。
- 不要把 Gmail 密碼、API key 寫進程式碼。
- 公開 GitHub repo 不要放真實持股資料。
