from __future__ import annotations

import os
import time
from io import StringIO
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from PIL import Image

from modules.storage import (
    load_portfolio, save_portfolio, load_alerts, save_alerts,
    normalize_portfolio_import, merge_portfolio,
    load_trades, save_trades, normalize_trade_import, apply_trade_to_portfolio,
)
from modules.market_data import enrich_portfolio_with_quotes, fetch_history
from modules.indicators import add_indicators, latest_signal
from modules.yahoo_screenshot_parser import ocr_image, parse_ocr_text
from modules.alerts import evaluate_alerts, stamp_trigger
from modules.emailer import send_email, build_alert_email
from modules.news_discussions import (
    fetch_google_news, fetch_discussions, sentiment_summary, search_links
)
from modules.daily_insights import build_portfolio_diagnosis
from modules.market_screener import build_daily_trend_radar, build_market_screener, top_rankings, top_etf_rankings

st.set_page_config(page_title="台股持股管理系統 MVP", layout="wide", page_icon="📈")


# --- Streamlit Cloud 單人密碼保護 ---
def _get_secret_value(name: str, default: str = "") -> str:
    try:
        value = st.secrets.get(name, default)
        return str(value) if value is not None else default
    except Exception:
        return os.getenv(name, default)


def require_login() -> None:
    """Simple single-user password gate for personal cloud deployment."""
    app_password = _get_secret_value("APP_PASSWORD", "")
    if not app_password:
        return
    if st.session_state.get("auth_ok"):
        return
    st.markdown("""
    <style>
    .login-card {max-width: 440px; margin: 12vh auto 0 auto; padding: 1.5rem; border-radius: 22px; border: 1px solid #e5e7eb; box-shadow: 0 12px 36px rgba(15,23,42,.08); background: #fff;}
    .login-title {font-size: 1.6rem; font-weight: 800; margin-bottom: .35rem;}
    .login-sub {color: #667085; margin-bottom: 1rem;}
    </style>
    <div class="login-card">
      <div class="login-title">📈 台股持股管理</div>
      <div class="login-sub">請輸入個人雲端版登入密碼</div>
    </div>
    """, unsafe_allow_html=True)
    password = st.text_input("登入密碼", type="password", label_visibility="collapsed", placeholder="請輸入登入密碼")
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        clicked = st.button("登入", use_container_width=True)
    if clicked:
        if password == app_password:
            st.session_state["auth_ok"] = True
            st.rerun()
        else:
            st.error("密碼錯誤，請再試一次。")
    st.stop()


require_login()

st.markdown(
    """
    <style>
    .main .block-container {padding-top: 1.2rem; padding-bottom: 2rem;}
    .hero {
        padding: 1.2rem 1.4rem;
        border-radius: 22px;
        background: linear-gradient(135deg, rgba(24,119,242,0.10), rgba(0,184,148,0.10));
        border: 1px solid rgba(120,140,170,0.20);
        margin-bottom: 1rem;
    }
    .hero h1 {margin: 0; font-size: 2.05rem;}
    .hero p {margin: .35rem 0 0 0; color: #667085; font-size: 1rem;}
    .pretty-card {
        padding: 1rem 1rem;
        border-radius: 18px;
        border: 1px solid rgba(120,140,170,0.20);
        background: rgba(255,255,255,0.72);
        box-shadow: 0 8px 26px rgba(30,41,59,0.06);
        margin-bottom: .75rem;
    }
    .card-title {font-size: 1.02rem; font-weight: 700; margin-bottom: .25rem;}
    .card-meta {font-size: .86rem; color: #667085; margin-bottom: .4rem;}
    .pill {
        display: inline-block; padding: .16rem .55rem; border-radius: 999px;
        font-size: .78rem; font-weight: 700; margin-right: .3rem;
        background: #eef2ff; color: #344054;
    }
    .pill-pos {background: #ecfdf3; color: #027a48;}
    .pill-neg {background: #fef3f2; color: #b42318;}
    .pill-neu {background: #f2f4f7; color: #475467;}
    .muted {color: #667085;}
    div[data-testid="stMetricValue"] {font-weight: 800;}

    @media (max-width: 768px) {
        .main .block-container {padding-left: .65rem; padding-right: .65rem; padding-top: .6rem;}
        .hero {padding: .85rem .95rem; border-radius: 16px;}
        .hero h1 {font-size: 1.35rem; line-height: 1.25;}
        .hero p {font-size: .88rem;}
        .pretty-card {padding: .85rem; border-radius: 14px;}
        div[data-testid="stMetric"] {padding: .55rem .35rem;}
        div[data-testid="stMetricValue"] {font-size: 1.15rem;}
        [data-testid="stSidebar"] {min-width: 275px;}
        .stDataFrame {font-size: .82rem;}
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="hero">
        <h1>📈 台股持股管理系統 MVP</h1>
        <p>CSV 匯入｜Yahoo 股市截圖匯入｜買賣記帳｜技術分析｜個股新聞與討論｜Gmail 價格提醒</p>
    </div>
    """,
    unsafe_allow_html=True,
)

PAGE_OPTIONS = [
    "持股總覽", "CSV 匯入", "買賣記帳", "Yahoo 截圖匯入", "個股技術分析",
    "每日健檢", "每日趨勢雷達", "市場排行", "新聞與討論", "提醒設定"
]
page = st.sidebar.radio("功能", PAGE_OPTIONS)

st.sidebar.markdown("---")
st.sidebar.subheader("行情更新")
quote_source_label = st.sidebar.selectbox(
    "持股現價來源",
    [
        "Yahoo 即時報價優先，失敗用匯入價（建議）",
        "只用 Yahoo 截圖/CSV 匯入價（對帳用）",
        "只用線上報價（失敗時仍避免歸零）",
    ],
    index=0,
)
QUOTE_SOURCE_MAP = {
    "Yahoo 即時報價優先，失敗用匯入價（建議）": "mixed",
    "只用 Yahoo 截圖/CSV 匯入價（對帳用）": "snapshot",
    "只用線上報價（失敗時仍避免歸零）": "yahoo",
}
quote_source = QUOTE_SOURCE_MAP[quote_source_label]
auto_refresh = st.sidebar.toggle("自動刷新目前頁面並重新抓價", value=False)
refresh_seconds = st.sidebar.selectbox("刷新頻率", [30, 60, 180, 300, 600], index=1, format_func=lambda x: f"{x//60} 分鐘" if x >= 60 else f"{x} 秒")
if auto_refresh:
    st.markdown(f"<meta http-equiv='refresh' content='{int(refresh_seconds)}'>", unsafe_allow_html=True)
    st.sidebar.success(f"已啟用，每 {refresh_seconds//60 if refresh_seconds>=60 else refresh_seconds} {'分鐘' if refresh_seconds>=60 else '秒'}重新抓價。")
st.sidebar.info("此為個人版 MVP。線上報價可能有延遲或抓不到；正式交易仍以券商 App / Yahoo 股市畫面為準。")


def money_fmt(x):
    try:
        return f"{float(x):,.0f}"
    except Exception:
        return "-"


def pct_fmt(x):
    try:
        return f"{float(x):.2f}%"
    except Exception:
        return "-"



def number_fmt(x, digits: int = 0, suffix: str = ""):
    try:
        if pd.isna(x):
            return "-"
        return f"{float(x):,.{digits}f}{suffix}"
    except Exception:
        return "-"


def compact_price_fmt(x):
    try:
        if pd.isna(x):
            return "-"
        v = float(x)
        if abs(v) >= 1000:
            return f"{v:,.0f}"
        return f"{v:,.2f}".rstrip("0").rstrip(".")
    except Exception:
        return "-"


def display_format_map(df: pd.DataFrame) -> dict:
    """Format tables with thousands separators without changing the stored CSV data."""
    if not isinstance(df, pd.DataFrame) or df.empty:
        return {}
    fmt = {}
    for col in df.columns:
        if not pd.api.types.is_numeric_dtype(df[col]):
            continue
        name = str(col)
        if any(k in name for k in ["股數", "持有股數", "交易筆數", "檔數", "排名", "新聞數", "討論數"]):
            fmt[col] = "{:,.0f}"
        elif any(k in name for k in ["率", "%", "RSI", "技術分數", "分數", "信心", "本益比", "股價淨值比", "殖利率", "PER", "PBR", "距", "倍率", "漲跌"]):
            fmt[col] = "{:,.2f}"
        elif any(k in name for k in ["成本", "現價", "價格", "成交價", "股價", "收盤價", "開盤價", "最高", "最低", "目前使用現價", "匯入截圖價"]):
            fmt[col] = "{:,.2f}"
        elif any(k in name for k in ["金額", "市值", "損益", "手續費", "證交稅", "總額", "買進", "賣出", "價值", "成交量", "volume", "Volume"]):
            fmt[col] = "{:,.0f}"
        else:
            fmt[col] = "{:,.2f}"
    return fmt


def show_table(df, *args, **kwargs):
    """st.dataframe wrapper: show numbers with comma separators in all non-editable tables."""
    try:
        if isinstance(df, pd.DataFrame):
            fmt = display_format_map(df)
            if fmt:
                return st.dataframe(df.style.format(fmt, na_rep="-"), *args, **kwargs)
        return st.dataframe(df, *args, **kwargs)
    except Exception:
        # If Streamlit Styler/Arrow has any issue, fall back to original dataframe.
        return st.dataframe(df, *args, **kwargs)


def _portfolio_signature(df: pd.DataFrame) -> str:
    if df is None or df.empty:
        return ""
    cols = [c for c in ["symbol", "market", "shares", "avg_cost", "last_price"] if c in df.columns]
    return df[cols].to_json(orient="records", force_ascii=False)


def get_portfolio_quotes(portfolio: pd.DataFrame, force: bool = False) -> pd.DataFrame:
    """Use a TTL-aware cache. v5.3 修正：自動刷新時會真的重新抓價，而不是只刷新網頁。"""
    if portfolio is None or portfolio.empty:
        return pd.DataFrame()
    sig = _portfolio_signature(portfolio) + f"|source={quote_source}"
    now = time.time()
    last_at = st.session_state.get("portfolio_quotes_at", 0)
    cache_missing = "portfolio_quotes" not in st.session_state
    sig_changed = st.session_state.get("portfolio_quotes_sig") != sig
    stale = (now - float(last_at or 0)) >= int(refresh_seconds)
    if force or cache_missing or sig_changed or (auto_refresh and stale):
        with st.spinner("正在重新抓取持股行情..."):
            st.session_state["portfolio_quotes"] = enrich_portfolio_with_quotes(portfolio, quote_source=quote_source)
            st.session_state["portfolio_quotes_at"] = now
            st.session_state["portfolio_quotes_sig"] = sig
    return st.session_state["portfolio_quotes"]


def clear_quote_cache() -> None:
    for k in ["portfolio_quotes", "portfolio_quotes_at", "portfolio_quotes_sig"]:
        st.session_state.pop(k, None)


def sentiment_class(sentiment: str) -> str:
    if sentiment == "偏多":
        return "pill pill-pos"
    if sentiment == "偏空":
        return "pill pill-neg"
    return "pill pill-neu"


def render_item_card(row: dict, kind: str = "news") -> None:
    title = str(row.get("title", ""))
    url = str(row.get("url", ""))
    source = str(row.get("source", ""))
    published = str(row.get("published", ""))
    sentiment = str(row.get("sentiment", "中性"))
    summary = str(row.get("summary", ""))
    engagement = str(row.get("engagement", ""))
    meta_parts = [p for p in [source, published, f"互動：{engagement}" if engagement and engagement != "nan" else ""] if p]
    title_html = f'<a href="{url}" target="_blank">{title}</a>' if url else title
    meta_html = " ｜ ".join(meta_parts)
    st.markdown(
        f"""
        <div class="pretty-card">
            <div class="card-title">{title_html}</div>
            <div class="card-meta">{meta_html}</div>
            <span class="{sentiment_class(sentiment)}">{sentiment}</span>
            <span class="pill">{kind}</span>
            <div class="muted" style="margin-top:.55rem;">{summary}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


if page == "持股總覽":
    st.header("持股總覽")
    portfolio = load_portfolio()

    with st.expander("手動新增 / 修改持股", expanded=False):
        edited = st.data_editor(
            portfolio,
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "symbol": "股票代號",
                "name": "股票名稱",
                "market": st.column_config.SelectboxColumn("市場", options=["TW", "TWO"]),
                "shares": st.column_config.NumberColumn("股數", min_value=0, step=1),
                "avg_cost": st.column_config.NumberColumn("平均成本", min_value=0.0, step=0.01),
                "note": "備註",
            },
        )
        if st.button("儲存持股"):
            save_portfolio(edited)
            clear_quote_cache()
            st.success("已儲存持股。")
            st.rerun()

    if portfolio.empty:
        st.warning("目前沒有持股資料。請先到『CSV 匯入』或『Yahoo 截圖匯入』匯入。")
    else:
        c_update, c_clear = st.columns([1, 1])
        force_update = c_update.button("重新抓取行情 / 損益", type="primary")
        if c_clear.button("清除行情快取"):
            clear_quote_cache()
            st.success("已清除快取，下一次會重新抓價。")
            st.rerun()

        qdf = get_portfolio_quotes(portfolio, force=force_update)
        total_cost = qdf["cost"].sum()
        total_value = qdf["market_value"].sum()
        total_pnl = qdf["unrealized_pnl"].sum()
        total_pnl_pct = total_pnl / total_cost * 100 if total_cost else 0

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("總成本", money_fmt(total_cost))
        c2.metric("總市值", money_fmt(total_value))
        c3.metric("未實現損益", money_fmt(total_pnl), pct_fmt(total_pnl_pct))
        c4.metric("持股檔數", len(qdf))

        display_cols = [
            "symbol", "name", "shares", "avg_cost", "current_price", "change_pct",
            "cost", "market_value", "unrealized_pnl", "unrealized_pnl_pct",
            "quote_source", "quote_time", "note"
        ]
        display = qdf[[c for c in display_cols if c in qdf.columns]].copy()
        display.columns = ["代號", "名稱", "股數", "成本", "現價", "今日漲跌%", "成本總額", "市值", "未實現損益", "報酬率%", "報價來源", "報價時間", "備註"][:len(display.columns)]
        show_table(display, use_container_width=True, hide_index=True)

        with st.expander("報價診斷 / 為什麼金額可能與 Yahoo 股市不同"):
            st.write("v5.3 已修正自動刷新：啟用後會依你設定的秒數重新抓價，不再只刷新頁面。")
            st.write("如果線上報價抓不到，系統會改用你 CSV / 截圖匯入時的股價，避免市值與損益被算成 0 或錯得太離譜。")
            diag_cols = [c for c in ["symbol", "name", "yahoo_symbol", "current_price", "last_price", "quote_source", "quote_time", "quote_error"] if c in qdf.columns]
            if diag_cols:
                diag = qdf[diag_cols].copy()
                diag.columns = ["代號", "名稱", "Yahoo代號", "目前使用現價", "匯入截圖價", "來源", "時間", "錯誤訊息"][:len(diag.columns)]
                show_table(diag, use_container_width=True, hide_index=True)

        st.download_button(
            "下載目前持股 CSV",
            data=qdf.to_csv(index=False).encode("utf-8-sig"),
            file_name="portfolio_with_quotes.csv",
            mime="text/csv",
        )



elif page == "CSV 匯入":
    st.header("CSV 匯入")
    st.write("可匯入我幫你整理的 Yahoo 股市持股 CSV，也支援本系統下載出的 portfolio CSV。")

    st.info("手機 Android 若看到 CSV 反灰，通常是檔案選擇器的 MIME 類型判斷問題。本版已改成接受所有檔案；只要內容是 CSV 即可匯入。")
    uploaded_csv = st.file_uploader("上傳持股 CSV（手機版已放寬檔案類型）", type=None, key="portfolio_csv_uploader")
    st.caption("支援欄位：股票代號/股票名稱/持有股數/持股成本均價，或 symbol/name/shares/avg_cost。股票代號可含 .TW 或 .TWO。")

    csv_text = st.text_area(
        "或直接貼上 CSV 內容",
        height=160,
        placeholder="股票名稱,股票代號,持有股數,持股成本均價\n台積電,2330.TW,100,1890\n鴻海,2317.TW,2000,139.25",
    )

    simple_text = st.text_area(
        "手機備援：直接貼簡易格式（不用逗號也可以）",
        height=120,
        placeholder="2330 台積電 100 1890\n2317 鴻海 2000 139.25\n00631L 元大台灣50正2 16000 26.98",
    )

    def read_uploaded_csv_safely(uploaded_file):
        """Read CSV uploaded from Android/Chrome/GDrive robustly.

        Android sometimes reports CSV files with a generic MIME type, and
        pandas' direct read from UploadedFile may try UTF-8 only.  We therefore
        read raw bytes first, try common Taiwan/Excel encodings, then parse from
        decoded text.  This prevents UnicodeDecodeError from crashing the app.
        """
        from io import StringIO

        data = uploaded_file.getvalue()
        if not data:
            raise ValueError("上傳的檔案是空的。")

        # Remove UTF-16/Excel null bytes if present, but keep a copy for decoding.
        candidates = []
        for enc in ["utf-8-sig", "utf-8", "cp950", "big5", "big5hkscs", "utf-16", "utf-16le", "utf-16be", "latin1"]:
            try:
                text = data.decode(enc)
                text = text.replace("\x00", "").strip()
                if text:
                    candidates.append((enc, text))
            except UnicodeDecodeError:
                continue
            except Exception:
                continue

        # Final safe fallback: never throw a UnicodeDecodeError to Streamlit.
        if not candidates:
            text = data.decode("utf-8", errors="replace").replace("\x00", "").strip()
            candidates.append(("utf-8-replace", text))

        last_error = None
        for enc, text in candidates:
            try:
                df = pd.read_csv(StringIO(text), engine="python")
                if len(df.columns) >= 2:
                    st.caption(f"CSV 已用 {enc} 編碼讀取。")
                    return df
            except Exception as exc:
                last_error = exc

        # Extremely defensive fallback for simple comma-separated rows.
        # This helps when Android/Excel adds odd metadata or pandas cannot infer columns.
        text = candidates[0][1]
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if len(lines) >= 2 and "," in lines[0]:
            header = [h.strip() for h in lines[0].split(",")]
            rows = []
            for ln in lines[1:]:
                parts = [x.strip() for x in ln.split(",")]
                if len(parts) < len(header):
                    parts += [""] * (len(header) - len(parts))
                rows.append(dict(zip(header, parts[:len(header)])))
            return pd.DataFrame(rows)

        raise ValueError(f"CSV 讀取失敗，請改用『直接貼上 CSV 內容』。最後錯誤：{last_error}")

    def parse_simple_portfolio_text(text: str) -> pd.DataFrame:
        rows = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.replace(",", " ").split()
            if len(parts) < 4:
                continue
            symbol = parts[0].strip()
            # 最後兩欄視為股數、成本，中間合併為名稱。
            shares = parts[-2]
            avg_cost = parts[-1]
            name = "".join(parts[1:-2])
            rows.append({
                "股票代號": symbol,
                "股票名稱": name,
                "持有股數": shares,
                "持股成本均價": avg_cost,
            })
        return pd.DataFrame(rows)

    raw_df = None
    if uploaded_csv is not None:
        try:
            raw_df = read_uploaded_csv_safely(uploaded_csv)
        except Exception as exc:
            st.error(f"CSV 讀取失敗：{exc}")
    elif csv_text.strip():
        from io import StringIO
        try:
            raw_df = pd.read_csv(StringIO(csv_text))
        except Exception as exc:
            st.error(f"貼上內容讀取失敗：{exc}")
    elif simple_text.strip():
        try:
            raw_df = parse_simple_portfolio_text(simple_text)
        except Exception as exc:
            st.error(f"簡易格式讀取失敗：{exc}")

    if isinstance(raw_df, pd.DataFrame):
        st.subheader("原始 CSV 預覽")
        show_table(raw_df.head(30), use_container_width=True, hide_index=True)
        parsed = normalize_portfolio_import(raw_df)
        st.subheader("轉換後持股欄位")
        edited = st.data_editor(
            parsed,
            num_rows="dynamic",
            use_container_width=True,
            key="csv_import_editor",
            column_config={
                "symbol": "股票代號",
                "name": "股票名稱",
                "market": st.column_config.SelectboxColumn("市場", options=["TW", "TWO"]),
                "shares": st.column_config.NumberColumn("股數", min_value=0, step=1),
                "avg_cost": st.column_config.NumberColumn("平均成本", min_value=0.0, step=0.01),
                "note": "備註",
            },
        )

        mode_label = st.radio(
            "匯入方式",
            ["更新同代號／新增不存在股票（建議）", "完全取代目前持股", "同代號加總股數並加權平均成本"],
            horizontal=False,
        )
        mode_map = {
            "更新同代號／新增不存在股票（建議）": "update",
            "完全取代目前持股": "replace",
            "同代號加總股數並加權平均成本": "append",
        }
        if st.button("確認匯入 CSV 持股"):
            current = load_portfolio()
            merged = merge_portfolio(current, edited, mode=mode_map[mode_label])
            save_portfolio(merged)
            clear_quote_cache()
            st.success(f"已匯入 {len(edited)} 筆，現在持股共 {len(merged)} 檔。")
            show_table(merged, use_container_width=True, hide_index=True)

    st.markdown("---")
    st.subheader("下載 CSV 範本")
    template = pd.DataFrame([
        {"股票名稱": "台積電", "股票代號": "2330.TW", "持有股數": 100, "持股成本均價": 1890.0},
        {"股票名稱": "鴻海", "股票代號": "2317.TW", "持有股數": 2000, "持股成本均價": 139.25},
    ])
    st.download_button(
        "下載持股匯入範本 CSV",
        data=template.to_csv(index=False).encode("utf-8-sig"),
        file_name="portfolio_import_template.csv",
        mime="text/csv",
    )


elif page == "買賣記帳":
    st.header("買進 / 賣出記帳")
    st.write("這裡是手動交易日記。新增買進會更新股數與平均成本；新增賣出會扣股數並計算已實現損益。")

    portfolio = load_portfolio()
    trades = load_trades()

    st.subheader("新增一筆交易")
    with st.form("trade_form", clear_on_submit=False):
        c1, c2, c3, c4 = st.columns(4)
        trade_date = c1.date_input("交易日期")
        side_label = c2.selectbox("交易類型", ["買進", "賣出"])
        side = "BUY" if side_label == "買進" else "SELL"
        symbol_options = [f"{r.symbol} {r.name}" for r in portfolio.itertuples()] if not portfolio.empty else []
        use_existing = c3.checkbox("從現有持股選擇", value=bool(symbol_options))
        market = c4.selectbox("市場", ["TW", "TWO"])

        if use_existing and symbol_options:
            selected_stock = st.selectbox("選擇股票", symbol_options)
            symbol = selected_stock.split()[0]
            matched = portfolio[portfolio["symbol"].astype(str) == symbol]
            default_name = matched["name"].iloc[0] if not matched.empty else ""
            market = matched["market"].iloc[0] if not matched.empty else market
            name = st.text_input("股票名稱", value=default_name)
        else:
            c5, c6 = st.columns(2)
            symbol = c5.text_input("股票代號", value="2330")
            name = c6.text_input("股票名稱", value="台積電")

        c7, c8, c9 = st.columns(3)
        shares = c7.number_input("股數", min_value=0.0, step=100.0, value=1000.0)
        price = c8.number_input("成交價", min_value=0.0, step=0.01, value=0.0)
        fee_rate = c9.number_input("手續費率", min_value=0.0, value=0.001425, step=0.000001, format="%.6f")

        c10, c11, c12 = st.columns(3)
        tax_rate_default = 0.003 if side == "SELL" else 0.0
        tax_rate = c10.number_input("證交稅率", min_value=0.0, value=tax_rate_default, step=0.0001, format="%.4f")
        fee = c11.number_input("手續費", min_value=0.0, value=round(shares * price * fee_rate, 0), step=1.0)
        tax = c12.number_input("證交稅", min_value=0.0, value=round(shares * price * tax_rate, 0), step=1.0)
        note = st.text_input("備註", value="")

        submitted = st.form_submit_button("儲存交易並更新持股")

    if submitted:
        trade = {
            "date": str(trade_date), "type": side, "symbol": symbol, "name": name, "market": market,
            "shares": shares, "price": price, "fee": fee, "tax": tax,
            "total_amount": shares * price + fee + tax if side == "BUY" else shares * price - fee - tax,
            "realized_pnl": 0.0, "note": note,
        }
        new_portfolio, realized, msg = apply_trade_to_portfolio(portfolio, trade)
        if msg.startswith("股數") or msg.startswith("找不到") or msg.startswith("賣出股數") or msg.startswith("交易類型"):
            st.error(msg)
        else:
            trade["realized_pnl"] = realized
            trades = pd.concat([trades, pd.DataFrame([trade])], ignore_index=True)
            save_trades(trades)
            save_portfolio(new_portfolio)
            st.session_state.pop("portfolio_quotes", None)
            st.success(msg)
            if side == "SELL":
                st.info(f"本筆估算已實現損益：{realized:,.0f} 元")

    st.subheader("交易紀錄")
    edited_trades = st.data_editor(
        trades,
        num_rows="dynamic",
        use_container_width=True,
        key="trades_editor",
        column_config={
            "date": "日期",
            "type": st.column_config.SelectboxColumn("類型", options=["BUY", "SELL"]),
            "symbol": "股票代號",
            "name": "股票名稱",
            "market": st.column_config.SelectboxColumn("市場", options=["TW", "TWO"]),
            "shares": st.column_config.NumberColumn("股數", min_value=0.0, step=1.0),
            "price": st.column_config.NumberColumn("成交價", min_value=0.0, step=0.01),
            "fee": st.column_config.NumberColumn("手續費", min_value=0.0, step=1.0),
            "tax": st.column_config.NumberColumn("證交稅", min_value=0.0, step=1.0),
            "total_amount": st.column_config.NumberColumn("交易金額", step=1.0),
            "realized_pnl": st.column_config.NumberColumn("已實現損益", step=1.0),
            "note": "備註",
        },
    )
    col_save, col_dl = st.columns(2)
    with col_save:
        if st.button("只儲存交易紀錄表格"):
            save_trades(edited_trades)
            st.success("交易紀錄已儲存。注意：直接編輯表格不會自動重算持股。")
    with col_dl:
        st.download_button(
            "下載交易紀錄 CSV",
            data=edited_trades.to_csv(index=False).encode("utf-8-sig"),
            file_name="trades.csv",
            mime="text/csv",
        )

    if not edited_trades.empty:
        realized_total = pd.to_numeric(edited_trades["realized_pnl"], errors="coerce").fillna(0).sum()
        buy_total = edited_trades.loc[edited_trades["type"].astype(str).str.upper() == "BUY", "total_amount"].sum()
        sell_total = edited_trades.loc[edited_trades["type"].astype(str).str.upper() == "SELL", "total_amount"].sum()
        c1, c2, c3 = st.columns(3)
        c1.metric("買進金額累計", f"{buy_total:,.0f}")
        c2.metric("賣出金額累計", f"{sell_total:,.0f}")
        c3.metric("已實現損益累計", f"{realized_total:,.0f}")

    st.markdown("---")
    st.subheader("交易紀錄 CSV 匯入")
    trade_csv = st.file_uploader("上傳交易紀錄 CSV", type=["csv"], key="trade_csv_uploader")
    if trade_csv is not None:
        try:
            raw_trade = pd.read_csv(trade_csv)
            parsed_trade = normalize_trade_import(raw_trade)
            show_table(parsed_trade, use_container_width=True, hide_index=True)
            if st.button("匯入交易紀錄 CSV（只加入記帳，不自動改持股）"):
                merged_trades = pd.concat([load_trades(), parsed_trade], ignore_index=True)
                save_trades(merged_trades)
                st.success(f"已匯入 {len(parsed_trade)} 筆交易紀錄。")
        except Exception as exc:
            st.error(f"交易 CSV 讀取失敗：{exc}")

elif page == "Yahoo 截圖匯入":
    st.header("Yahoo 股市截圖匯入 / 手動匯入")
    st.write("如果 OCR 失敗，請直接用下面的『手動表格匯入』，先把系統用起來。手機截圖 OCR 需要另外安裝 Tesseract 主程式與繁體中文字庫，並不是只裝 Python 套件就會成功。")

    tab1, tab2, tab3 = st.tabs(["手動表格匯入（最穩）", "貼上 OCR 文字", "上傳截圖 OCR（選用）"])

    with tab1:
        st.subheader("手動表格匯入")
        st.caption("每行一檔，格式：股票代號 股票名稱 股數 平均成本。也支援用逗號或 Tab 分隔。")
        example_text = "2330 台積電 1000 980\n2317 鴻海 2000 190\n00631L 元大台灣50正2 3000 210.5"
        manual_text = st.text_area(
            "貼上或輸入持股",
            value=st.session_state.get("manual_import_text", example_text),
            height=180,
            key="manual_import_text_area",
        )
        if st.button("解析手動表格", key="parse_manual"):
            parsed = parse_ocr_text(manual_text)
            st.session_state["parsed_holdings"] = parsed

        st.markdown("也可以直接在表格新增/修改：")
        empty_df = pd.DataFrame([
            {"symbol": "2330", "name": "台積電", "market": "TW", "shares": 1000, "avg_cost": 980.0, "note": "手動匯入", "confidence": 1.0},
            {"symbol": "2317", "name": "鴻海", "market": "TW", "shares": 2000, "avg_cost": 190.0, "note": "手動匯入", "confidence": 1.0},
        ])
        direct_df = st.data_editor(
            st.session_state.get("direct_manual_df", empty_df),
            num_rows="dynamic",
            use_container_width=True,
            key="direct_manual_editor",
            column_config={
                "symbol": "股票代號",
                "name": "股票名稱",
                "market": st.column_config.SelectboxColumn("市場", options=["TW", "TWO"]),
                "shares": st.column_config.NumberColumn("股數", min_value=0, step=1),
                "avg_cost": st.column_config.NumberColumn("平均成本", min_value=0.0, step=0.01),
                "note": "備註",
                "confidence": st.column_config.ProgressColumn("信心", min_value=0.0, max_value=1.0),
            },
        )
        if st.button("直接匯入上方表格", key="import_direct_manual"):
            st.session_state["parsed_holdings"] = direct_df

    with tab2:
        st.subheader("貼上 OCR 文字")
        text_value = st.text_area(
            "OCR 文字 / 手動貼上 Yahoo 股市畫面文字",
            value=st.session_state.get("ocr_text", ""),
            height=240,
            placeholder="例如：2330 台積電 持股 1000 股 成本 1000 ...",
            key="ocr_text_area",
        )
        if st.button("解析 OCR 文字", key="parse_ocr_text_button"):
            parsed = parse_ocr_text(text_value)
            st.session_state["parsed_holdings"] = parsed

    with tab3:
        st.subheader("上傳截圖 OCR")
        st.info("這個功能依賴你電腦本機的 Tesseract OCR。若辨識失敗，建議先用『手動表格匯入』，或把截圖傳給 ChatGPT，我可以幫你看 Yahoo 版面並修解析規則。")
        uploaded = st.file_uploader("上傳截圖", type=["png", "jpg", "jpeg", "webp"])
        if uploaded is not None:
            image = Image.open(uploaded)
            st.image(image, caption="已上傳截圖", use_container_width=True)
            if st.button("嘗試 OCR 辨識", key="ocr_image_button"):
                try:
                    with st.spinner("OCR 辨識中..."):
                        ocr_text = ocr_image(image)
                    st.session_state["ocr_text"] = ocr_text
                    parsed = parse_ocr_text(ocr_text)
                    st.session_state["parsed_holdings"] = parsed
                    st.success("OCR 完成，請檢查下方文字與解析結果。")
                    st.text_area("OCR 原始文字", value=ocr_text, height=220)
                except RuntimeError as exc:
                    st.warning(str(exc))
                    st.markdown("你可以暫時改用第一個分頁『手動表格匯入』，格式例如：`2330 台積電 1000 980`。")

    parsed_df = st.session_state.get("parsed_holdings")
    if isinstance(parsed_df, pd.DataFrame) and not parsed_df.empty:
        st.subheader("匯入前確認")
        edited = st.data_editor(
            parsed_df,
            num_rows="dynamic",
            use_container_width=True,
            key="parsed_holdings_editor",
            column_config={
                "symbol": "股票代號",
                "name": "股票名稱",
                "market": st.column_config.SelectboxColumn("市場", options=["TW", "TWO"]),
                "shares": st.column_config.NumberColumn("股數", min_value=0, step=1),
                "avg_cost": st.column_config.NumberColumn("平均成本", min_value=0.0, step=0.01),
                "note": "備註",
                "confidence": st.column_config.ProgressColumn("辨識信心", min_value=0.0, max_value=1.0),
            },
        )
        if st.button("確認匯入持股"):
            portfolio = load_portfolio()
            to_import = edited[["symbol", "name", "market", "shares", "avg_cost", "note"]].copy()
            merged = pd.concat([portfolio, to_import], ignore_index=True)
            merged = merged.drop_duplicates(subset=["symbol"], keep="last")
            save_portfolio(merged)
            clear_quote_cache()
            st.success("已匯入持股。請到『持股總覽』查看。")
            st.session_state.pop("portfolio_quotes", None)
    elif isinstance(parsed_df, pd.DataFrame) and parsed_df.empty:
        st.warning("沒有解析到股票代號。請改用手動表格格式，例如：2330 台積電 1000 980。")


elif page == "個股技術分析":
    st.header("個股技術分析")
    portfolio = load_portfolio()
    symbols = []
    if not portfolio.empty:
        symbols = [f"{r.symbol} {r.name}" for r in portfolio.itertuples()]

    default_symbol = symbols[0] if symbols else "2330 台積電"
    selected = st.selectbox("選擇持股", options=symbols or [default_symbol])
    symbol = selected.split()[0]
    row = portfolio[portfolio["symbol"].astype(str) == symbol]
    market = row["market"].iloc[0] if not row.empty else "TW"

    period = st.selectbox("歷史期間", ["6mo", "1y", "2y", "5y"], index=1)
    hist = fetch_history(symbol, market, period=period, interval="1d")
    if hist.empty:
        st.error("抓不到歷史行情。請確認股票代號或市場 TW/TWO 是否正確。")
    else:
        ind = add_indicators(hist)
        signal = latest_signal(hist)
        c1, c2, c3 = st.columns(3)
        c1.metric("技術分數", f"{signal['score']}/100")
        c2.metric("最新收盤/現價", f"{ind['Close'].iloc[-1]:.2f}")
        c3.write("**判斷：** " + signal["summary"])

        st.write("**技術訊號**")
        for s in signal["signals"]:
            st.write("- " + s)

        fig = go.Figure()
        fig.add_trace(go.Candlestick(
            x=ind["Date"],
            open=ind["Open"],
            high=ind["High"],
            low=ind["Low"],
            close=ind["Close"],
            name="K線",
        ))
        for ma in ["MA5", "MA20", "MA60"]:
            if ma in ind.columns:
                fig.add_trace(go.Scatter(x=ind["Date"], y=ind[ma], mode="lines", name=ma))
        fig.update_layout(height=560, xaxis_rangeslider_visible=False, title=f"{selected} K線與均線")
        st.plotly_chart(fig, use_container_width=True)

        c1, c2 = st.columns(2)
        with c1:
            fig_rsi = go.Figure()
            fig_rsi.add_trace(go.Scatter(x=ind["Date"], y=ind["RSI14"], mode="lines", name="RSI14"))
            fig_rsi.add_hline(y=70, line_dash="dash")
            fig_rsi.add_hline(y=30, line_dash="dash")
            fig_rsi.update_layout(height=300, title="RSI")
            st.plotly_chart(fig_rsi, use_container_width=True)
        with c2:
            fig_macd = go.Figure()
            fig_macd.add_trace(go.Scatter(x=ind["Date"], y=ind["MACD"], mode="lines", name="MACD"))
            fig_macd.add_trace(go.Scatter(x=ind["Date"], y=ind["MACD_SIGNAL"], mode="lines", name="Signal"))
            fig_macd.add_trace(go.Bar(x=ind["Date"], y=ind["MACD_HIST"], name="Hist"))
            fig_macd.update_layout(height=300, title="MACD")
            st.plotly_chart(fig_macd, use_container_width=True)

        latest_cols = ["Date", "Close", "MA5", "MA10", "MA20", "MA60", "RSI14", "K", "D", "MACD", "MACD_SIGNAL", "BB_UPPER", "BB_LOWER"]
        st.subheader("最新技術數據")
        show_table(ind[latest_cols].tail(10), use_container_width=True, hide_index=True)


elif page == "新聞與討論":
    st.header("個股新聞與討論")
    st.caption("每檔股票抓最近 10 則新聞與 10 則討論。新聞以 Google News RSS 為主；討論區採 PTT Stock、Dcard 理財與搜尋索引作為 MVP 資料源。")

    portfolio = load_portfolio()
    if portfolio.empty:
        st.warning("目前沒有持股資料。請先到『CSV 匯入』或『Yahoo 截圖匯入』建立持股。")
    else:
        symbols = [f"{r.symbol} {r.name}" for r in portfolio.itertuples()]
        c1, c2, c3 = st.columns([2, 1, 1])
        selected = c1.selectbox("選擇股票", options=symbols)
        limit = c2.number_input("每類顯示則數", min_value=3, max_value=20, value=10, step=1)
        refresh = c3.button("重新抓取", use_container_width=True)

        symbol = selected.split()[0]
        row = portfolio[portfolio["symbol"].astype(str) == symbol]
        name = row["name"].iloc[0] if not row.empty else selected.replace(symbol, "").strip()

        @st.cache_data(ttl=900, show_spinner=False)
        def _cached_news(sym: str, nm: str, lim: int):
            return fetch_google_news(sym, nm, limit=lim)

        @st.cache_data(ttl=900, show_spinner=False)
        def _cached_discussions(sym: str, nm: str, lim: int):
            return fetch_discussions(sym, nm, limit=lim)

        if refresh:
            _cached_news.clear()
            _cached_discussions.clear()

        with st.spinner(f"正在整理 {name}({symbol}) 的新聞與討論..."):
            news_df = _cached_news(symbol, name, int(limit))
            disc_df = _cached_discussions(symbol, name, int(limit))

        ns = sentiment_summary(news_df)
        ds = sentiment_summary(disc_df)
        total_pos = ns["偏多"] + ds["偏多"]
        total_neu = ns["中性"] + ds["中性"]
        total_neg = ns["偏空"] + ds["偏空"]
        if total_pos > total_neg and total_pos >= total_neu:
            overall = "偏多"
        elif total_neg > total_pos and total_neg >= total_neu:
            overall = "偏空"
        elif (total_pos + total_neu + total_neg) == 0:
            overall = "資料不足"
        else:
            overall = "中性"

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("新聞則數", len(news_df))
        m2.metric("討論則數", len(disc_df))
        m3.metric("偏多/偏空", f"{total_pos}/{total_neg}")
        m4.metric("綜合情緒", overall)

        tab_news, tab_disc, tab_sent, tab_links = st.tabs(["新聞 10 則", "討論 10 則", "情緒摘要", "搜尋連結"])
        with tab_news:
            if news_df.empty:
                st.info("目前抓不到新聞。可能是網路、RSS 暫時無回應，或該股近期新聞較少。")
            else:
                for _, r in news_df.iterrows():
                    render_item_card(r.to_dict(), kind="新聞")
                st.download_button(
                    "下載新聞 CSV",
                    data=news_df.to_csv(index=False).encode("utf-8-sig"),
                    file_name=f"{symbol}_{name}_news.csv",
                    mime="text/csv",
                )

        with tab_disc:
            if disc_df.empty:
                st.info("目前抓不到討論區結果。可到『搜尋連結』直接開 PTT、Dcard、Mobile01 搜尋。")
            else:
                for _, r in disc_df.iterrows():
                    render_item_card(r.to_dict(), kind="討論")
                st.download_button(
                    "下載討論 CSV",
                    data=disc_df.to_csv(index=False).encode("utf-8-sig"),
                    file_name=f"{symbol}_{name}_discussions.csv",
                    mime="text/csv",
                )

        with tab_sent:
            st.subheader(f"{name}({symbol}) 市場情緒摘要")
            sent_df = pd.DataFrame([
                {"來源": "新聞", "偏多": ns["偏多"], "中性": ns["中性"], "偏空": ns["偏空"], "綜合": ns["overall"]},
                {"來源": "討論區", "偏多": ds["偏多"], "中性": ds["中性"], "偏空": ds["偏空"], "綜合": ds["overall"]},
                {"來源": "合計", "偏多": total_pos, "中性": total_neu, "偏空": total_neg, "綜合": overall},
            ])
            show_table(sent_df, use_container_width=True, hide_index=True)
            if overall == "偏多":
                st.success("目前標題與討論語氣偏多。仍建議搭配技術面、法人籌碼與營收資料確認，不宜只看討論熱度追價。")
            elif overall == "偏空":
                st.warning("目前標題與討論語氣偏空。建議檢查是否有基本面轉弱、法人連賣或跌破重要均線。")
            elif overall == "中性":
                st.info("目前情緒偏中性，資訊分歧或樣本不足，建議回到個股技術分析與基本面判斷。")
            else:
                st.info("資料不足，請使用搜尋連結手動確認。")

            combined = pd.concat([
                news_df.assign(類型="新聞") if not news_df.empty else pd.DataFrame(),
                disc_df.assign(類型="討論") if not disc_df.empty else pd.DataFrame(),
            ], ignore_index=True)
            if not combined.empty:
                st.subheader("全部結果表格")
                cols = [c for c in ["類型", "source", "title", "published", "engagement", "sentiment", "url"] if c in combined.columns]
                show_table(combined[cols], use_container_width=True, hide_index=True)

        with tab_links:
            st.write("若自動抓取失敗，這些連結可以直接開啟搜尋：")
            links = search_links(symbol, name)
            for label, url in links.items():
                st.markdown(f"- [{label}]({url})")

        st.markdown("---")
        st.subheader("快速掃描我的持股")
        st.caption("這個功能會對前幾檔持股抓取標題數與情緒，第一次使用可能較慢。")
        scan_count = st.slider("掃描持股檔數", min_value=3, max_value=min(15, len(portfolio)), value=min(8, len(portfolio)))
        if st.button("掃描我的持股新聞/討論熱度"):
            rows = []
            progress = st.progress(0)
            sample = portfolio.head(scan_count)
            for idx, (_, r) in enumerate(sample.iterrows(), start=1):
                sym = str(r["symbol"])
                nm = str(r["name"])
                ndf = _cached_news(sym, nm, 10)
                ddf = _cached_discussions(sym, nm, 10)
                summary_n = sentiment_summary(ndf)
                summary_d = sentiment_summary(ddf)
                rows.append({
                    "代號": sym,
                    "名稱": nm,
                    "新聞數": len(ndf),
                    "討論數": len(ddf),
                    "偏多": summary_n["偏多"] + summary_d["偏多"],
                    "中性": summary_n["中性"] + summary_d["中性"],
                    "偏空": summary_n["偏空"] + summary_d["偏空"],
                })
                progress.progress(idx / len(sample))
            heat_df = pd.DataFrame(rows)
            st.session_state["news_discussion_heat"] = heat_df

        heat = st.session_state.get("news_discussion_heat")
        if isinstance(heat, pd.DataFrame) and not heat.empty:
            show_table(heat, use_container_width=True, hide_index=True)
            st.download_button(
                "下載持股新聞討論熱度 CSV",
                data=heat.to_csv(index=False).encode("utf-8-sig"),
                file_name="portfolio_news_discussion_heat.csv",
                mime="text/csv",
            )


elif page == "提醒設定":
    st.header("Gmail 價格與技術提醒")
    alerts_df = load_alerts()

    st.subheader("提醒條件")
    st.caption("rule_type 支援：price、ma20_cross_down、ma20_cross_up、rsi。price/rsi 需要 operator 與 threshold。")
    edited_alerts = st.data_editor(
        alerts_df,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "symbol": "股票代號",
            "name": "名稱",
            "rule_type": st.column_config.SelectboxColumn("規則", options=["price", "ma20_cross_down", "ma20_cross_up", "rsi"]),
            "operator": st.column_config.SelectboxColumn("比較", options=[">=", ">", "<=", "<", "==", ""]),
            "threshold": st.column_config.NumberColumn("門檻", step=0.01),
            "enabled": "啟用",
            "last_triggered_at": "上次觸發",
            "note": "備註",
        },
    )
    if st.button("儲存提醒條件"):
        save_alerts(edited_alerts)
        st.success("已儲存提醒條件。")
        st.rerun()

    st.subheader("Gmail 設定")
    with st.expander("填寫 Gmail SMTP 設定", expanded=False):
        smtp_user = st.text_input("Gmail 地址", value=os.getenv("GMAIL_SMTP_USER", ""))
        app_password = st.text_input("Gmail 應用程式密碼", value=os.getenv("GMAIL_APP_PASSWORD", ""), type="password")
        recipient = st.text_input("收件者", value=os.getenv("ALERT_RECIPIENT", smtp_user))
        st.caption("建議使用 Gmail 應用程式密碼，不要使用 Gmail 登入密碼。")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("檢查提醒條件"):
            with st.spinner("正在檢查提醒條件..."):
                results = evaluate_alerts(load_alerts())
            st.session_state["alert_results"] = results

    with col2:
        if st.button("寄送測試 Email"):
            try:
                send_email(
                    "台股管理系統測試信",
                    "這是一封測試信。如果你收到，代表 Gmail 提醒設定成功。",
                    to_email=recipient,
                    smtp_user=smtp_user,
                    app_password=app_password,
                )
                st.success("測試信已寄出。")
            except Exception as exc:
                st.error(f"寄信失敗：{exc}")

    results = st.session_state.get("alert_results")
    if results:
        st.subheader("檢查結果")
        res_df = pd.DataFrame(results)
        show_table(res_df, use_container_width=True, hide_index=True)
        triggered = [r for r in results if r.get("triggered")]
        if triggered:
            st.warning(f"有 {len(triggered)} 則提醒觸發。")
            if st.button("寄出觸發提醒 Email"):
                try:
                    subject, body = build_alert_email(triggered)
                    send_email(subject, body, to_email=recipient, smtp_user=smtp_user, app_password=app_password)
                    alerts = load_alerts()
                    for item in triggered:
                        alerts = stamp_trigger(alerts, item.get("symbol"), item.get("rule_type"))
                    save_alerts(alerts)
                    st.success("已寄出提醒 Email。")
                except Exception as exc:
                    st.error(f"寄信失敗：{exc}")
        else:
            st.info("目前沒有提醒條件觸發。")


elif page == "每日健檢":
    st.header("每日持股健檢")
    st.caption("這一頁不做制式逐檔摘要，而是把持股分成：創高強勢、應減碼/停損、仍有潛力、短線過熱等實際決策清單。")
    portfolio = load_portfolio()
    if portfolio.empty:
        st.warning("目前沒有持股資料。請先匯入持股。")
    else:
        c1, c2, c3 = st.columns([1, 1, 2])
        with c1:
            run_check = st.button("產生今日健檢", use_container_width=True)
        with c2:
            clear_check = st.button("重新分析", use_container_width=True)
        with c3:
            st.info("若開啟左側自動刷新，本頁會定時重新載入，但健檢仍建議手動按一次，避免頻繁抓資料。")
        if clear_check:
            st.session_state.pop("portfolio_diagnosis_df", None)
            st.session_state.pop("portfolio_diagnosis_text", None)
        if run_check or "portfolio_diagnosis_df" not in st.session_state:
            with st.spinner("正在分析你的持股：新高、均線、RSI、量能、成本損益..."):
                diag_df, diag_text = build_portfolio_diagnosis(portfolio)
            st.session_state["portfolio_diagnosis_df"] = diag_df
            st.session_state["portfolio_diagnosis_text"] = diag_text

        diag_df = st.session_state.get("portfolio_diagnosis_df")
        diag_text = st.session_state.get("portfolio_diagnosis_text", "")
        if isinstance(diag_df, pd.DataFrame) and not diag_df.empty:
            total = len(diag_df)
            high_risk = int((diag_df["風險"] == "高").sum()) if "風險" in diag_df.columns else 0
            new_high_count = int(diag_df["標籤"].astype(str).str.contains("新高", na=False).sum()) if "標籤" in diag_df.columns else 0
            potential_count = int((diag_df["技術分數"] >= 70).sum()) if "技術分數" in diag_df.columns else 0
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("持股檔數", total)
            m2.metric("高風險觀察", high_risk)
            m3.metric("創高/近新高", new_high_count)
            m4.metric("技術分數≥70", potential_count)

            st.markdown(diag_text)
            st.markdown("---")

            tab1, tab2, tab3, tab4, tab5 = st.tabs(["應處理", "仍有潛力", "創高強勢", "短線過熱", "完整表格"])
            with tab1:
                sell_df = diag_df[(diag_df["風險"] == "高") | (diag_df["動作"].astype(str).str.contains("賣出|減碼|停損", na=False))].copy()
                if sell_df.empty:
                    st.success("目前沒有很明確的賣出/停損名單。")
                else:
                    show_table(sell_df[["代號", "名稱", "現價", "成本", "報酬率%", "技術分數", "動作", "原因", "風險"]], use_container_width=True, hide_index=True)
            with tab2:
                pot_df = diag_df[(diag_df["技術分數"] >= 60) & ~(diag_df["動作"].astype(str).str.contains("賣出|減碼|停損", na=False))].sort_values("技術分數", ascending=False)
                if pot_df.empty:
                    st.info("今天沒有很明確的潛力名單。")
                else:
                    show_table(pot_df[["代號", "名稱", "現價", "報酬率%", "技術分數", "動作", "原因", "成交量倍率"]], use_container_width=True, hide_index=True)
            with tab3:
                nh_df = diag_df[diag_df["標籤"].astype(str).str.contains("新高", na=False)].sort_values("技術分數", ascending=False)
                if nh_df.empty:
                    st.info("目前沒有創高/近新高持股。")
                else:
                    show_table(nh_df[["代號", "名稱", "現價", "距52週高點%", "RSI", "技術分數", "動作", "原因"]], use_container_width=True, hide_index=True)
            with tab4:
                hot_df = diag_df[diag_df["標籤"].astype(str).str.contains("過熱", na=False)].sort_values("RSI", ascending=False)
                if hot_df.empty:
                    st.success("目前沒有明顯 RSI 過熱持股。")
                else:
                    show_table(hot_df[["代號", "名稱", "現價", "報酬率%", "RSI", "距20MA%", "動作", "原因"]], use_container_width=True, hide_index=True)
            with tab5:
                show_table(diag_df, use_container_width=True, hide_index=True)
                st.download_button(
                    "下載今日健檢 CSV",
                    data=diag_df.to_csv(index=False).encode("utf-8-sig"),
                    file_name="daily_portfolio_diagnosis.csv",
                    mime="text/csv",
                )
        else:
            st.warning("尚未產生健檢或資料不足。")


elif page == "每日趨勢雷達":
    st.header("每日網路個股趨勢雷達")
    st.caption("每天彙整 Google News、PTT/Dcard 等可取得的標題與討論，歸納 10 支值得注意的個股/ETF。這是趨勢雷達，不是買進清單。")
    portfolio = load_portfolio()

    c1, c2, c3 = st.columns([1, 1, 2])
    scan_my_holdings = c1.checkbox("優先掃描我的持股", value=True)
    limit = c2.number_input("注意名單數量", min_value=5, max_value=20, value=10, step=1)
    c3.info("第一次掃描會較慢，因為會抓新聞、討論與部分技術資料。")

    @st.cache_data(ttl=900, show_spinner=False)
    def _cached_trend_radar(portfolio_csv: str, scan: bool, lim: int):
        pf = pd.read_json(StringIO(portfolio_csv)) if portfolio_csv else pd.DataFrame()
        return build_daily_trend_radar(pf, scan_my_holdings_first=scan, limit=lim)

    portfolio_json = portfolio.to_json(orient="records", force_ascii=False) if not portfolio.empty else ""
    if st.button("重新彙總今日趨勢", use_container_width=True):
        _cached_trend_radar.clear()

    with st.spinner("正在彙總市場新聞與討論..."):
        radar_df, raw_feed = _cached_trend_radar(portfolio_json, scan_my_holdings, int(limit))

    if radar_df.empty:
        st.warning("目前抓不到足夠的市場趨勢資料。可能是網路、RSS 或討論區暫時無法連線。")
    else:
        m1, m2, m3 = st.columns(3)
        m1.metric("注意個股/ETF", len(radar_df))
        m2.metric("偏多項目", int((radar_df["情緒"] == "偏多").sum()) if "情緒" in radar_df.columns else 0)
        m3.metric("偏空項目", int((radar_df["情緒"] == "偏空").sum()) if "情緒" in radar_df.columns else 0)

        for _, r in radar_df.iterrows():
            sentiment = str(r.get("情緒", "中性"))
            klass = sentiment_class(sentiment)
            url = str(r.get("第一連結", ""))
            link_html = f'<a href="{url}" target="_blank">開啟代表新聞/討論</a>' if url else ""
            st.markdown(
                f"""
                <div class="pretty-card">
                    <div class="card-title">#{int(r.get('排名', 0))} {r.get('名稱','')}({r.get('代號','')})</div>
                    <div class="card-meta">分數 {r.get('分數','-')} ｜ 新聞 {r.get('新聞數',0)} ｜ 討論 {r.get('討論數',0)} ｜ 技術分數 {r.get('技術分數',0)} ｜ {link_html}</div>
                    <span class="{klass}">{sentiment}</span>
                    <span class="pill">{r.get('注意理由','')}</span>
                    <div class="muted" style="margin-top:.55rem; white-space:pre-line;">{r.get('代表標題','')}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

        st.subheader("趨勢雷達表格")
        show_table(radar_df, use_container_width=True, hide_index=True)
        st.download_button(
            "下載每日趨勢雷達 CSV",
            data=radar_df.to_csv(index=False).encode("utf-8-sig"),
            file_name="daily_trend_radar.csv",
            mime="text/csv",
        )

    with st.expander("市場新聞原始標題"):
        if isinstance(raw_feed, pd.DataFrame) and not raw_feed.empty:
            show_table(raw_feed, use_container_width=True, hide_index=True)
        else:
            st.info("沒有原始標題資料。")


elif page == "市場排行":
    st.header("市場排行 / 選股條件 / ETF專區")
    st.caption("股票與 ETF 分開看：本益比排行只套用股票；ETF 另外提供漲跌、成交量、殖利率、量能、52週新高與類型排行。")
    portfolio = load_portfolio()

    c1, c2, c3 = st.columns(3)
    include_common = c1.checkbox("包含內建常用台股/ETF池", value=True)
    fetch_info = c2.checkbox("啟用慢速本益比/殖利率備援", value=False, help="官方資料抓不到時，改用 Yahoo Finance 逐檔查詢；速度會慢很多。ETF 殖利率可能會較不完整。")
    if c3.button("重新抓取排行榜", use_container_width=True):
        st.cache_data.clear()

    @st.cache_data(ttl=300, show_spinner=False)
    def _cached_screener(portfolio_csv: str, include_common_flag: bool, fetch_info_flag: bool):
        pf = pd.read_json(StringIO(portfolio_csv)) if portfolio_csv else pd.DataFrame()
        return build_market_screener(pf, include_common=include_common_flag, fetch_yahoo_info=fetch_info_flag)

    def render_rankings(rankings: dict, prefix: str):
        if not rankings:
            st.info("目前沒有可顯示的排行榜。")
            return
        tabs = st.tabs(list(rankings.keys()))
        for tab, (title, rdf) in zip(tabs, rankings.items()):
            with tab:
                st.subheader(title)
                show_table(rdf, use_container_width=True, hide_index=True)
                st.download_button(
                    f"下載{title} CSV",
                    data=rdf.to_csv(index=False).encode("utf-8-sig"),
                    file_name=f"{title}.csv",
                    mime="text/csv",
                    key=f"download_{prefix}_{title}",
                )

    portfolio_json = portfolio.to_json(orient="records", force_ascii=False) if not portfolio.empty else ""
    with st.spinner("正在更新市場排行與 ETF 專區..."):
        market_df, meta = _cached_screener(portfolio_json, include_common, fetch_info)

    st.info(f"更新時間：{meta.get('updated_at','-')}｜資料來源：{meta.get('source_notes','-')}")
    if market_df.empty:
        st.warning("目前沒有抓到市場資料。請稍後重試，或確認網路連線。")
    else:
        if "security_type" in market_df.columns:
            stock_df = market_df[market_df["security_type"] != "ETF"].copy()
            etf_df = market_df[market_df["security_type"] == "ETF"].copy()
        else:
            stock_df = market_df.copy()
            etf_df = pd.DataFrame()

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("全資料檔數", len(market_df))
        m2.metric("股票檔數", len(stock_df))
        m3.metric("ETF檔數", len(etf_df))
        if not etf_df.empty and "etf_category" in etf_df.columns:
            m4.metric("ETF類型", etf_df["etf_category"].replace("", pd.NA).dropna().nunique())
        else:
            m4.metric("ETF類型", 0)

        main_tabs = st.tabs(["全部排行", "股票排行", "ETF專區", "完整資料"])
        with main_tabs[0]:
            st.subheader("全部排行")
            st.caption("漲跌幅、殖利率與量能可混合股票/ETF；本益比最低會自動排除 ETF。")
            render_rankings(top_rankings(market_df), "all")

        with main_tabs[1]:
            st.subheader("股票排行")
            st.caption("適合看低本益比、低股價淨值比、殖利率與強弱勢股票。ETF 不會混入本益比排行。")
            render_rankings(top_rankings(stock_df), "stock")

        with main_tabs[2]:
            st.subheader("ETF專區")
            st.caption("ETF 不看本益比；這裡改看漲跌幅、成交量、殖利率、量能放大、接近52週高點與類型排行。槓桿/反向 ETF 會獨立分出。")
            if etf_df.empty:
                st.warning("目前沒有抓到 ETF 資料。請勾選『包含內建常用台股/ETF池』後重抓。")
            else:
                if "etf_category" in etf_df.columns:
                    st.markdown("#### ETF 類型分布")
                    cat_count = etf_df["etf_category"].replace("", "其他ETF").value_counts().reset_index()
                    cat_count.columns = ["ETF類型", "檔數"]
                    show_table(cat_count, use_container_width=True, hide_index=True)
                render_rankings(top_etf_rankings(etf_df), "etf")
                with st.expander("查看完整 ETF 清單"):
                    show_table(etf_df, use_container_width=True, hide_index=True)
                    st.download_button(
                        "下載完整 ETF 清單 CSV",
                        data=etf_df.to_csv(index=False).encode("utf-8-sig"),
                        file_name="ETF完整清單.csv",
                        mime="text/csv",
                        key="download_etf_all",
                    )

        with main_tabs[3]:
            st.subheader("完整股票 / ETF 資料池")
            show_table(market_df, use_container_width=True, hide_index=True)
            st.download_button(
                "下載完整市場資料 CSV",
                data=market_df.to_csv(index=False).encode("utf-8-sig"),
                file_name="market_screener_full.csv",
                mime="text/csv",
                key="download_market_full",
            )

        st.markdown("---")
        st.subheader("我建議加看的條件")
        st.markdown(
            """
            - **ETF 專區**：把 0050、00631L、00878、00919、00929、00981A、00990A 這類 ETF 從股票本益比排行中分離，避免混淆。
            - **高股息 ETF 殖利率**：適合看現金流，但仍要看填息能力、成分股與配息來源。
            - **槓桿 / 反向 ETF**：只適合獨立看趨勢與風險，不適合拿殖利率或本益比比較。
            - **量能放大前十**：比單純漲幅更早看到資金進場。
            - **接近52週新高**：強勢股/ETF 值得追蹤，但追高要搭配停損線。
            """
        )

