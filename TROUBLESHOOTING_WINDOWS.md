# Windows 啟動排除指南

## 最推薦啟動方式

1. 先把 zip 完整解壓縮，不要直接在壓縮檔內執行。
2. 進入 `tw_stock_manager_mvp` 資料夾。
3. 雙擊 `start_windows_easy.bat`。
4. 若瀏覽器沒開，手動開 `http://localhost:8501`。

## 如果雙擊 bat 完全沒反應

請用這個方式看錯誤訊息：

1. 進入 `tw_stock_manager_mvp` 資料夾。
2. 在資料夾空白處按右鍵，選「在終端機中開啟」。
3. 輸入：

```bat
start_windows_easy.bat
```

或逐行輸入：

```bat
py --version
py -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

## 如果你裝的是 Python install manager 26.2

先在 Windows Terminal 執行：

```bat
py install --configure -y
py install 3.13
py --version
```

然後再執行 `start_windows_easy.bat`。

## 常見原因

- 直接在 zip 裡面點 bat，請先完整解壓縮。
- Windows 把下載檔封鎖：zip 右鍵 → 內容 → 解除封鎖。
- Python install manager 裝了，但還沒完成設定：執行 `py install --configure -y`。
- 套件還沒安裝，第一次啟動會花幾分鐘。
- 公司或防毒軟體擋住本機 Web 服務，允許 Python / Streamlit 即可。

## v5 新功能資料抓不到

「每日趨勢雷達」和「市場排行」需要網路連線。若公司網路、防火牆、VPN 或網站防爬導致抓不到資料，請稍後重試，或先使用「持股總覽」與「每日健檢」這類本機資料功能。

「市場排行」中的本益比與殖利率優先使用 TWSE OpenAPI；如果官方資料暫時抓不到，可以勾選「啟用慢速本益比/殖利率備援」，但速度會比較慢。

## v5.4：行情沒有更新或金額不對

請先確認左側「行情更新」：

1. 持股現價來源選「Yahoo 即時報價優先，失敗用匯入價（建議）」
2. 開啟「自動刷新目前頁面並重新抓價」
3. 刷新頻率先選 60 秒
4. 到「持股總覽」按「清除行情快取」再按「重新抓取行情 / 損益」

若要和 Yahoo 截圖對帳，改選「只用 Yahoo 截圖/CSV 匯入價（對帳用）」。
