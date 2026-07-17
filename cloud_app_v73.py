from __future__ import annotations

import os
import re
import time
import csv
import zipfile
from io import BytesIO, StringIO
from pathlib import Path
import xml.etree.ElementTree as ET
from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st
import yfinance as yf

st.set_page_config(page_title="全球持股管理系統 v7", page_icon="📈", layout="wide")
APP_VERSION = "v7.3-global-persist-edit-trades"

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
GLOBAL_PORTFOLIO_PATH = DATA_DIR / "global_portfolio.csv"
TRANSACTION_PATH = DATA_DIR / "transactions.csv"

PORTFOLIO_COLUMNS = [
    "symbol", "name", "market", "asset_type", "currency", "shares", "avg_cost", "last_price", "note", "updated_at"
]

TRADE_COLUMNS = [
    "trade_date", "market", "symbol", "name", "side", "shares", "price", "fee", "tax",
    "currency", "amount", "realized_pnl", "note", "created_at"
]

KNOWN_TWO = {"5289", "4966", "3260", "8299", "3294"}
ETF_HINTS = ["ETF", "高股息", "台灣50", "正2", "反1", "主動", "科技優息", "精選高息", "增長", "加權"]

# -------------------------
# Login
# -------------------------
def _get_secret_value(name: str, default: str = "") -> str:
    try:
        v = st.secrets.get(name, default)
        return str(v) if v is not None else default
    except Exception:
        return os.getenv(name, default)


def require_login() -> None:
    pwd = _get_secret_value("APP_PASSWORD", "")
    if not pwd:
        return
    if st.session_state.get("auth_ok"):
        return
    st.markdown("""
    <div class="login-card">
      <h1>📈 全球持股管理</h1>
      <p>請輸入個人雲端版登入密碼</p>
    </div>
    """, unsafe_allow_html=True)
    password = st.text_input("登入密碼", type="password", placeholder="請輸入登入密碼", label_visibility="collapsed")
    if st.button("登入", use_container_width=True):
        if password == pwd:
            st.session_state["auth_ok"] = True
            st.rerun()
        else:
            st.error("密碼錯誤。")
    st.stop()

# -------------------------
# CSS
# -------------------------
st.markdown("""
<style>
.main .block-container {padding-top: 1rem; padding-bottom: 2rem;}
.hero {padding: 1.1rem 1.25rem; border-radius: 22px; background: linear-gradient(135deg, rgba(59,130,246,.10), rgba(16,185,129,.10)); border: 1px solid rgba(148,163,184,.35); margin-bottom: 1rem;}
.hero h1 {font-size: 2rem; margin:0 0 .3rem 0;}
.hero p {color:#667085; margin:0;}
.card {padding: .9rem; border-radius: 16px; border: 1px solid #e5e7eb; background: #fff; box-shadow: 0 6px 20px rgba(15,23,42,.05); margin-bottom: .75rem;}
.card-title {font-weight:800; font-size:1rem; margin-bottom:.25rem;}
.muted {color:#667085;}
.badge {display:inline-block; padding:.12rem .5rem; border-radius:999px; font-size:.76rem; font-weight:700; background:#f2f4f7; color:#475467; margin-right:.25rem;}
.badge-tw {background:#eff6ff; color:#175cd3;}
.badge-us {background:#ecfdf3; color:#027a48;}
.badge-hk {background:#fff7ed; color:#c2410c;}
.badge-etf {background:#f5f3ff; color:#6d28d9;}
.pnl-pos {color:#d92d20; font-weight:800;}
.pnl-neg {color:#039855; font-weight:800;}
.small {font-size:.85rem;}
.mobile-card {padding:.85rem; border-radius:16px; border:1px solid #e5e7eb; background:#fff; margin:.55rem 0;}
.mobile-row {display:flex; justify-content:space-between; gap:10px; font-size:.92rem; margin:.18rem 0;}
.mobile-row b {font-weight:800;}
@media (max-width: 768px) {
  .main .block-container {padding-left:.55rem; padding-right:.55rem; padding-top:.55rem;}
  .hero {padding:.9rem; border-radius:16px;}
  .hero h1 {font-size:1.35rem; line-height:1.25;}
  .hero p {font-size:.82rem;}
  div[data-testid="stMetricValue"] {font-size:1.2rem;}
  [data-testid="stSidebar"] {min-width:280px;}
  .stDataFrame {font-size:.80rem;}
}
</style>
""", unsafe_allow_html=True)

require_login()

st.markdown("""
<div class="hero">
  <h1>📈 全球持股管理系統 v7</h1>
  <p>台股個股｜台股 ETF｜美股｜港股｜桌機表格｜手機卡片｜全球配置統計</p>
</div>
""", unsafe_allow_html=True)

# -------------------------
# Helpers
# -------------------------
def now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def safe_float(v, default=0.0) -> float:
    try:
        if v is None or pd.isna(v):
            return default
        s = str(v).replace(",", "").replace("股", "").replace("TWD", "").replace("USD", "").replace("HKD", "").strip()
        if s == "" or s.lower() == "nan":
            return default
        return float(s)
    except Exception:
        return default


def fmt_num(x, d=0, suffix="") -> str:
    try:
        if x is None or pd.isna(x):
            return "-"
        return f"{float(x):,.{d}f}{suffix}"
    except Exception:
        return "-"


def fmt_price(x) -> str:
    try:
        if x is None or pd.isna(x):
            return "-"
        v = float(x)
        if abs(v) >= 1000:
            return f"{v:,.0f}"
        return f"{v:,.2f}".rstrip("0").rstrip(".")
    except Exception:
        return "-"


def pnl_html(v) -> str:
    try:
        f = float(v)
        cls = "pnl-pos" if f >= 0 else "pnl-neg"
        return f'<span class="{cls}">{f:,.0f}</span>'
    except Exception:
        return "-"


def infer_asset_type(name: str, symbol: str, market: str) -> str:
    name = str(name or "")
    symbol = str(symbol or "").upper()
    market = str(market or "").upper()
    if market in ["US", "HK"]:
        return "股票"
    if symbol.startswith("00") or any(h in name for h in ETF_HINTS):
        return "ETF"
    return "股票"


def normalize_symbol_market(symbol: str, market: str = "") -> tuple[str, str]:
    raw = str(symbol or "").strip().upper().replace("（", "(").replace("）", ")")
    raw = raw.replace("(ADR)", "").replace(" ADR", "").strip()
    mkt = str(market or "").strip().upper()
    if raw.endswith(".TWO"):
        return raw[:-4], "TWO"
    if raw.endswith(".TW"):
        return raw[:-3], "TW"
    if raw.endswith(".HK"):
        core = raw[:-3]
        return core.zfill(4) if core.isdigit() else core, "HK"
    if mkt in ["TPEX", "OTC"]:
        mkt = "TWO"
    if mkt in ["NASDAQ", "NYSE", "AMEX", "US"]:
        return raw, "US"
    if mkt in ["HK", "HKG", "香港", "港股"]:
        return raw.zfill(4) if raw.isdigit() else raw, "HK"
    if raw.isalpha() or re.match(r"^[A-Z]{1,5}([.-][A-Z]{1,3})?$", raw):
        return raw, "US"
    if raw.isdigit() and len(raw) <= 4 and raw in KNOWN_TWO:
        return raw, "TWO"
    if raw.isdigit() and len(raw) <= 4:
        return raw, "TW"
    return raw, mkt or "TW"


def to_yahoo_symbol(symbol: str, market: str) -> str:
    s, m = normalize_symbol_market(symbol, market)
    if m == "TW":
        return f"{s}.TW"
    if m == "TWO":
        return f"{s}.TWO"
    if m == "HK":
        return f"{s.zfill(4) if s.isdigit() else s}.HK"
    return s


def currency_for_market(market: str) -> str:
    return {"TW": "TWD", "TWO": "TWD", "US": "USD", "HK": "HKD"}.get(str(market).upper(), "TWD")


def market_label(market: str) -> str:
    return {"TW": "台股上市", "TWO": "台股上櫃", "US": "美股", "HK": "港股"}.get(str(market).upper(), market)


def badge_for_market(market: str) -> str:
    m = str(market).upper()
    cls = "badge-tw" if m in ["TW", "TWO"] else "badge-us" if m == "US" else "badge-hk" if m == "HK" else ""
    return f'<span class="badge {cls}">{market_label(m)}</span>'


def ensure_portfolio_file():
    if not GLOBAL_PORTFOLIO_PATH.exists():
        pd.DataFrame(columns=PORTFOLIO_COLUMNS).to_csv(GLOBAL_PORTFOLIO_PATH, index=False)


def load_portfolio() -> pd.DataFrame:
    ensure_portfolio_file()
    try:
        df = pd.read_csv(GLOBAL_PORTFOLIO_PATH, dtype=str)
    except Exception:
        df = pd.DataFrame(columns=PORTFOLIO_COLUMNS)
    for c in PORTFOLIO_COLUMNS:
        if c not in df.columns:
            df[c] = "" if c not in ["shares", "avg_cost", "last_price"] else 0
    for c in ["shares", "avg_cost", "last_price"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    df["market"] = df["market"].astype(str).str.upper().replace({"": "TW", "NAN": "TW"})
    df["currency"] = df.apply(lambda r: r.get("currency") or currency_for_market(r.get("market")), axis=1)
    return df[PORTFOLIO_COLUMNS]


def save_portfolio(df: pd.DataFrame):
    out = normalize_portfolio_df(df)
    out.to_csv(GLOBAL_PORTFOLIO_PATH, index=False)

def ensure_transaction_file():
    if not TRANSACTION_PATH.exists():
        pd.DataFrame(columns=TRADE_COLUMNS).to_csv(TRANSACTION_PATH, index=False)


def load_transactions() -> pd.DataFrame:
    ensure_transaction_file()
    try:
        df = pd.read_csv(TRANSACTION_PATH, dtype=str)
    except Exception:
        df = pd.DataFrame(columns=TRADE_COLUMNS)
    for c in TRADE_COLUMNS:
        if c not in df.columns:
            df[c] = "" if c not in ["shares", "price", "fee", "tax", "amount", "realized_pnl"] else 0
    for c in ["shares", "price", "fee", "tax", "amount", "realized_pnl"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    df["market"] = df["market"].astype(str).str.upper()
    return df[TRADE_COLUMNS]


def save_transactions(df: pd.DataFrame):
    out = df.copy() if df is not None else pd.DataFrame(columns=TRADE_COLUMNS)
    for c in TRADE_COLUMNS:
        if c not in out.columns:
            out[c] = "" if c not in ["shares", "price", "fee", "tax", "amount", "realized_pnl"] else 0
    out.to_csv(TRANSACTION_PATH, index=False)


def apply_trade_to_portfolio(portfolio: pd.DataFrame, trade: dict) -> tuple[pd.DataFrame, float]:
    df = normalize_portfolio_df(portfolio)
    symbol, market = normalize_symbol_market(trade.get("symbol"), trade.get("market"))
    shares = safe_float(trade.get("shares"))
    price = safe_float(trade.get("price"))
    fee = safe_float(trade.get("fee"))
    tax = safe_float(trade.get("tax"))
    side = str(trade.get("side", "買進"))
    name = str(trade.get("name") or symbol).strip()
    currency = currency_for_market(market)
    realized = 0.0

    mask = (df["symbol"].astype(str).str.upper() == symbol.upper()) & (df["market"].astype(str).str.upper() == market.upper())
    if mask.any():
        idx = df.index[mask][0]
        old_shares = safe_float(df.at[idx, "shares"])
        old_avg = safe_float(df.at[idx, "avg_cost"])
    else:
        idx = None
        old_shares = 0.0
        old_avg = 0.0

    if side == "買進":
        new_shares = old_shares + shares
        new_avg = ((old_shares * old_avg) + (shares * price) + fee) / new_shares if new_shares > 0 else price
        row = {
            "symbol": symbol, "name": name, "market": market, "asset_type": infer_asset_type(name, symbol, market),
            "currency": currency, "shares": new_shares, "avg_cost": new_avg, "last_price": price,
            "note": "買賣記帳更新", "updated_at": now_text()
        }
        if idx is None:
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        else:
            for k, v in row.items():
                df.at[idx, k] = v
    else:
        sell_shares = min(shares, old_shares) if old_shares > 0 else shares
        realized = (price - old_avg) * sell_shares - fee - tax
        new_shares = max(old_shares - shares, 0)
        if idx is None:
            row = {
                "symbol": symbol, "name": name, "market": market, "asset_type": infer_asset_type(name, symbol, market),
                "currency": currency, "shares": 0, "avg_cost": price, "last_price": price,
                "note": "賣出紀錄但原持股不存在", "updated_at": now_text()
            }
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
        else:
            df.at[idx, "shares"] = new_shares
            df.at[idx, "last_price"] = price
            df.at[idx, "note"] = "買賣記帳更新"
            df.at[idx, "updated_at"] = now_text()
    return normalize_portfolio_df(df), realized


def portfolio_to_paste_text(df: pd.DataFrame) -> str:
    df = normalize_portfolio_df(df)
    lines = []
    for _, r in df.iterrows():
        ys = to_yahoo_symbol(r["symbol"], r["market"])
        lines.append(f'{ys},{r.get("name","")},{fmt_num(r.get("shares",0),0).replace(",","")},{fmt_price(r.get("avg_cost",0))},{fmt_price(r.get("last_price",0))},0,0,{r.get("market","")}')
    return "\n".join(lines)


def normalize_portfolio_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=PORTFOLIO_COLUMNS)
    out = df.copy()
    for c in PORTFOLIO_COLUMNS:
        if c not in out.columns:
            out[c] = "" if c not in ["shares", "avg_cost", "last_price"] else 0
    symbols, markets = [], []
    for sym, mkt in zip(out["symbol"], out["market"]):
        s, m = normalize_symbol_market(sym, mkt)
        symbols.append(s); markets.append(m)
    out["symbol"] = symbols
    out["market"] = markets
    out["name"] = out["name"].astype(str).replace({"nan":""}).str.strip()
    out["shares"] = out["shares"].apply(safe_float)
    out["avg_cost"] = out["avg_cost"].apply(safe_float)
    out["last_price"] = out["last_price"].apply(safe_float)
    out["currency"] = out.apply(lambda r: str(r.get("currency") or currency_for_market(r["market"])).upper(), axis=1)
    out["asset_type"] = out.apply(lambda r: r.get("asset_type") or infer_asset_type(r.get("name"), r.get("symbol"), r.get("market")), axis=1)
    out["note"] = out["note"].astype(str).replace({"nan":""})
    out["updated_at"] = out["updated_at"].astype(str).replace({"nan":""})
    out = out[out["symbol"].astype(str).str.strip() != ""]
    out = out.drop_duplicates(subset=["symbol", "market"], keep="last")
    return out[PORTFOLIO_COLUMNS]


def merge_portfolio(current: pd.DataFrame, incoming: pd.DataFrame, mode: str) -> pd.DataFrame:
    incoming = normalize_portfolio_df(incoming)
    if mode == "replace" or current is None or current.empty:
        return incoming
    current = normalize_portfolio_df(current)
    if mode == "append":
        merged = pd.concat([current, incoming], ignore_index=True)
        rows = []
        for (symbol, market), g in merged.groupby(["symbol", "market"], dropna=False):
            shares = g["shares"].sum()
            avg_cost = (g["shares"] * g["avg_cost"]).sum() / shares if shares else g["avg_cost"].iloc[-1]
            last = g.iloc[-1].to_dict(); last["shares"] = shares; last["avg_cost"] = avg_cost
            rows.append(last)
        return normalize_portfolio_df(pd.DataFrame(rows))
    merged = pd.concat([current, incoming], ignore_index=True)
    merged = merged.drop_duplicates(subset=["symbol", "market"], keep="last")
    return normalize_portfolio_df(merged)

# -------------------------
# XLSX parser without openpyxl
# -------------------------
def _xlsx_shared_strings(z: zipfile.ZipFile) -> list[str]:
    try:
        xml = z.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(xml)
    ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    strings = []
    for si in root.findall("a:si", ns):
        texts = [t.text or "" for t in si.findall(".//a:t", ns)]
        strings.append("".join(texts))
    return strings


def _xlsx_sheet_map(z: zipfile.ZipFile) -> dict[str, str]:
    wb_xml = z.read("xl/workbook.xml")
    rels_xml = z.read("xl/_rels/workbook.xml.rels")
    root = ET.fromstring(wb_xml)
    rels = ET.fromstring(rels_xml)
    ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main", "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    rel_ns = {"pr": "http://schemas.openxmlformats.org/package/2006/relationships"}
    rid_to_target = {}
    for rel in rels.findall("pr:Relationship", rel_ns):
        rid = rel.attrib.get("Id")
        target = rel.attrib.get("Target", "")
        if not target.startswith("/"):
            target = "xl/" + target
        target = target.replace("xl/xl/", "xl/")
        rid_to_target[rid] = target
    out = {}
    for sh in root.findall(".//a:sheet", ns):
        name = sh.attrib.get("name", "")
        rid = sh.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        if name and rid in rid_to_target:
            out[name] = rid_to_target[rid]
    return out


def _col_to_idx(cell_ref: str) -> int:
    letters = re.sub(r"[^A-Z]", "", cell_ref.upper())
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return max(n - 1, 0)


def _parse_sheet(z: zipfile.ZipFile, path: str, shared: list[str]) -> list[list[object]]:
    root = ET.fromstring(z.read(path))
    ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    rows = []
    for row in root.findall(".//a:sheetData/a:row", ns):
        vals = []
        for c in row.findall("a:c", ns):
            idx = _col_to_idx(c.attrib.get("r", "A"))
            while len(vals) < idx:
                vals.append(None)
            typ = c.attrib.get("t")
            v_el = c.find("a:v", ns)
            value = None
            if typ == "s" and v_el is not None:
                try: value = shared[int(v_el.text)]
                except Exception: value = ""
            elif typ == "inlineStr":
                texts = [t.text or "" for t in c.findall(".//a:t", ns)]
                value = "".join(texts)
            elif v_el is not None:
                raw = v_el.text
                try:
                    value = float(raw) if raw and "." in raw else int(raw)
                except Exception:
                    value = raw
            vals.append(value)
        rows.append(vals)
    return rows


def read_xlsx_sheets(file_bytes: bytes) -> dict[str, list[list[object]]]:
    with zipfile.ZipFile(BytesIO(file_bytes)) as z:
        shared = _xlsx_shared_strings(z)
        smap = _xlsx_sheet_map(z)
        return {name: _parse_sheet(z, path, shared) for name, path in smap.items()}


def rows_to_records(rows: list[list[object]]) -> list[dict]:
    if not rows:
        return []
    header = [str(x).strip() if x is not None else "" for x in rows[0]]
    recs = []
    for r in rows[1:]:
        if not any(x not in [None, ""] for x in r):
            continue
        d = {header[i]: r[i] if i < len(r) else None for i in range(len(header)) if header[i]}
        recs.append(d)
    return recs


def parse_ifong_xlsx(file_bytes: bytes) -> pd.DataFrame:
    sheets = read_xlsx_sheets(file_bytes)
    rows = []
    for sname, default_type in [("台股個股", "股票"), ("台股ETF", "ETF")]:
        for r in rows_to_records(sheets.get(sname, [])):
            sym = str(r.get("代號", "")).strip()
            if not sym or sym.lower() == "none":
                continue
            market = "TWO" if sym in KNOWN_TWO else "TW"
            name = str(r.get("股票", "")).strip()
            rows.append({
                "symbol": sym, "name": name, "market": market, "asset_type": default_type,
                "currency": "TWD", "shares": safe_float(r.get("持股")), "avg_cost": safe_float(r.get("成本")),
                "last_price": safe_float(r.get("現價")), "note": f"Excel匯入/{sname}", "updated_at": now_text()
            })
    # US watchlist/holdings; workbook currently has tickers only.
    for r in rows_to_records(sheets.get("美股", [])):
        raw = str(r.get("股票", "")).strip()
        if not raw or raw.lower() == "none":
            continue
        sym, market = normalize_symbol_market(raw, "US")
        rows.append({"symbol": sym, "name": raw, "market": "US", "asset_type": "股票", "currency": "USD", "shares": 0, "avg_cost": 0, "last_price": 0, "note": "Excel匯入/美股觀察", "updated_at": now_text()})
    for r in rows_to_records(sheets.get("港股", [])):
        name = str(r.get("股票", "")).strip()
        raw = str(r.get("代號", "")).strip()
        if not raw or raw.lower() == "none":
            continue
        if raw.upper() == "TJGC" or "TJGC" in name.upper():
            sym, market = normalize_symbol_market("TJGC", "US")
            rows.append({"symbol": sym, "name": name or "TJGC Group", "market": "US", "asset_type": "股票", "currency": "USD", "shares": 0, "avg_cost": 0, "last_price": 0, "note": "Excel匯入/美股觀察/TJGC", "updated_at": now_text()})
        else:
            sym, market = normalize_symbol_market(raw, "HK")
            rows.append({"symbol": sym, "name": name or raw, "market": market, "asset_type": "股票", "currency": currency_for_market(market), "shares": 0, "avg_cost": 0, "last_price": 0, "note": "Excel匯入/港股觀察", "updated_at": now_text()})
    return normalize_portfolio_df(pd.DataFrame(rows))


def _looks_like_market_token(v: str) -> bool:
    return str(v or "").strip().upper() in {"TW", "TWO", "TPEX", "OTC", "US", "NYSE", "NASDAQ", "AMEX", "HK", "HKG", "港股", "香港"}


def parse_paste_text(text: str) -> pd.DataFrame:
    """Parse mobile-friendly pasted holdings.

    Supported formats:
    1) 2330.TW 台積電 100 1890
    2) 2330.TW,台積電,100,1890,TW
    3) 2330.TW,台積電,100,1890,2380,238000,49000,TW
       columns = symbol,name,shares,avg_cost,last_price,market_value,unrealized,market

    The market_value/unrealized columns are accepted for user-friendly paste text.
    The app stores last_price and recomputes market value as shares × current price;
    if last_price is blank but market_value is provided, last_price is derived from it.
    """
    rows = []
    for line in str(text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "," in line:
            try:
                parts = [p.strip() for p in next(csv.reader([line]))]
            except Exception:
                parts = [p.strip() for p in line.split(",")]
        else:
            parts = line.split()
        parts = [p for p in parts if p != ""]
        if not parts:
            continue

        symbol = parts[0]
        name = parts[1] if len(parts) >= 2 else symbol
        shares = safe_float(parts[2]) if len(parts) >= 3 else 0
        avg_cost = safe_float(parts[3]) if len(parts) >= 4 else 0
        last_price = 0.0
        market_value = 0.0
        unrealized = 0.0
        market_hint = ""

        # Old 5-column form: symbol,name,shares,avg_cost,market
        if len(parts) >= 5 and _looks_like_market_token(parts[4]):
            market_hint = parts[4]
        else:
            # New value-aware form: symbol,name,shares,avg_cost,last_price,market_value,unrealized,market
            last_price = safe_float(parts[4]) if len(parts) >= 5 else 0.0
            market_value = safe_float(parts[5]) if len(parts) >= 6 else 0.0
            unrealized = safe_float(parts[6]) if len(parts) >= 7 else 0.0
            if len(parts) >= 8:
                market_hint = parts[7]
            elif len(parts) >= 7 and _looks_like_market_token(parts[6]):
                market_hint = parts[6]
                unrealized = 0.0
            elif len(parts) >= 6 and _looks_like_market_token(parts[5]):
                market_hint = parts[5]
                market_value = 0.0

        if last_price <= 0 and market_value > 0 and shares > 0:
            last_price = market_value / shares
        # For US/HK pasted holdings, users often provide shares/cost but leave quote columns as 0.
        # Keep a non-zero snapshot price so the holding is visible and has a cost-based placeholder
        # until live quotes are fetched successfully.
        if last_price <= 0 and shares > 0 and avg_cost > 0:
            last_price = avg_cost

        sym, market = normalize_symbol_market(symbol, market_hint)
        if len(parts) == 1:
            name = symbol
        rows.append({
            "symbol": sym, "name": name, "market": market, "asset_type": infer_asset_type(name, sym, market),
            "currency": currency_for_market(market), "shares": shares, "avg_cost": avg_cost, "last_price": last_price,
            "note": "貼上匯入含市值" if market_value else "貼上匯入", "updated_at": now_text()
        })
    return normalize_portfolio_df(pd.DataFrame(rows))

# -------------------------
# Quotes / FX
# -------------------------

def fetch_quote_yfinance_fallback(ys: str) -> dict:
    """Fallback quote retrieval for Yahoo symbols when query1.finance.yahoo.com returns no data.

    This is especially useful on Streamlit Cloud for US/HK tickers where the lightweight
    quote endpoint may occasionally return empty/blocked results. It tries fast_info first,
    then recent daily history.
    """
    result = {"yahoo_symbol": ys, "current_price": 0.0, "previous_close": 0.0, "change": 0.0, "change_pct": 0.0, "quote_source": "NoData"}
    try:
        ticker = yf.Ticker(ys)
        price = prev = 0.0
        try:
            info = ticker.fast_info
            # yfinance fast_info behaves like a dict-like object, but some keys may raise.
            for key in ["last_price", "lastPrice", "regular_market_price", "regularMarketPrice"]:
                try:
                    v = info.get(key) if hasattr(info, "get") else getattr(info, key, None)
                    if v:
                        price = safe_float(v)
                        break
                except Exception:
                    pass
            for key in ["previous_close", "previousClose", "regular_market_previous_close", "regularMarketPreviousClose"]:
                try:
                    v = info.get(key) if hasattr(info, "get") else getattr(info, key, None)
                    if v:
                        prev = safe_float(v)
                        break
                except Exception:
                    pass
        except Exception:
            pass
        if price <= 0 or prev <= 0:
            try:
                hist = ticker.history(period="7d", interval="1d", auto_adjust=False)
                if hist is not None and not hist.empty:
                    closes = hist["Close"].dropna().tolist()
                    if closes:
                        if price <= 0:
                            price = safe_float(closes[-1])
                        if prev <= 0:
                            prev = safe_float(closes[-2] if len(closes) >= 2 else closes[-1])
            except Exception:
                pass
        if price > 0:
            change = price - prev if prev > 0 else 0.0
            change_pct = change / prev * 100 if prev > 0 else 0.0
            result.update({"current_price": price, "previous_close": prev, "change": change, "change_pct": change_pct, "quote_source": "yfinance"})
    except Exception:
        pass
    return result

@st.cache_data(ttl=60)
def fetch_yahoo_quotes(yahoo_symbols: tuple[str, ...]) -> pd.DataFrame:
    symbols = [s for s in yahoo_symbols if s]
    if not symbols:
        return pd.DataFrame()
    rows = []
    headers = {"User-Agent": "Mozilla/5.0"}
    for i in range(0, len(symbols), 60):
        batch = symbols[i:i+60]
        batch_rows = []
        try:
            resp = requests.get(
                "https://query1.finance.yahoo.com/v7/finance/quote",
                params={"symbols": ",".join(batch), "lang": "zh-TW", "region": "TW"},
                headers=headers,
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json().get("quoteResponse", {}).get("result", [])
        except Exception:
            data = []
        got = set()
        for it in data:
            ys = it.get("symbol")
            got.add(ys)
            price = it.get("regularMarketPrice") or it.get("postMarketPrice") or it.get("preMarketPrice")
            prev = it.get("regularMarketPreviousClose")
            change = it.get("regularMarketChange")
            change_pct = it.get("regularMarketChangePercent")
            if price is not None and prev not in [None, 0] and change is None:
                change = float(price) - float(prev)
            if change is not None and prev not in [None, 0] and change_pct is None:
                change_pct = float(change) / float(prev) * 100
            row = {"yahoo_symbol": ys, "current_price": safe_float(price), "previous_close": safe_float(prev), "change": safe_float(change), "change_pct": safe_float(change_pct), "quote_source": "YahooQuote"}
            # If Yahoo quote endpoint returns an item but without usable price, try yfinance.
            if row["current_price"] <= 0:
                row = fetch_quote_yfinance_fallback(ys)
            batch_rows.append(row)
        for ys in set(batch) - got:
            batch_rows.append(fetch_quote_yfinance_fallback(ys))
        rows.extend(batch_rows)
        time.sleep(0.05)
    return pd.DataFrame(rows)



@st.cache_data(ttl=300)
def fetch_fx_rates() -> dict[str, float]:
    # TWD estimates; fallback values intentionally conservative, user can still use original-currency totals.
    pairs = {"USD": "USDTWD=X", "HKD": "HKDTWD=X"}
    out = {"TWD": 1.0, "USD": 31.0, "HKD": 3.95}
    try:
        q = fetch_yahoo_quotes(tuple(pairs.values()))
        for curr, ys in pairs.items():
            row = q[q["yahoo_symbol"] == ys]
            if not row.empty and row["current_price"].iloc[0] > 0:
                out[curr] = float(row["current_price"].iloc[0])
    except Exception:
        pass
    return out


def enrich_portfolio(df: pd.DataFrame, mode: str = "live") -> pd.DataFrame:
    df = normalize_portfolio_df(df)
    if df.empty:
        return df
    df["yahoo_symbol"] = df.apply(lambda r: to_yahoo_symbol(r["symbol"], r["market"]), axis=1)
    qdf = fetch_yahoo_quotes(tuple(df["yahoo_symbol"].tolist())) if mode == "live" else pd.DataFrame()
    if not qdf.empty:
        out = df.merge(qdf, on="yahoo_symbol", how="left")
    else:
        out = df.copy()
        out["current_price"] = 0; out["previous_close"] = 0; out["change"] = 0; out["change_pct"] = 0; out["quote_source"] = "匯入價"
    out["current_price"] = pd.to_numeric(out.get("current_price", 0), errors="coerce").fillna(0)
    # fallback to imported last_price, useful for Taiwan current snapshots in user Excel.
    out["current_price"] = out["current_price"].where(out["current_price"] > 0, out["last_price"])
    out["cost"] = out["shares"] * out["avg_cost"]
    out["market_value"] = out["shares"] * out["current_price"]
    out["unrealized_pnl"] = out["market_value"] - out["cost"]
    out["unrealized_pnl_pct"] = (out["unrealized_pnl"] / out["cost"].replace(0, pd.NA) * 100).fillna(0)
    rates = fetch_fx_rates()
    out["fx_to_twd"] = out["currency"].map(rates).fillna(1.0)
    out["market_value_twd"] = out["market_value"] * out["fx_to_twd"]
    out["cost_twd"] = out["cost"] * out["fx_to_twd"]
    out["unrealized_pnl_twd"] = out["unrealized_pnl"] * out["fx_to_twd"]
    out["market_label"] = out["market"].apply(market_label)
    return out


def display_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    cols = ["market", "asset_type", "symbol", "name", "shares", "avg_cost", "current_price", "change_pct", "currency", "market_value", "unrealized_pnl", "unrealized_pnl_pct", "market_value_twd", "quote_source"]
    cols = [c for c in cols if c in df.columns]
    out = df[cols].copy()
    ren = {"market": "市場", "asset_type": "類型", "symbol": "代號", "name": "名稱", "shares": "股數", "avg_cost": "成本", "current_price": "現價", "change_pct": "漲跌%", "currency": "幣別", "market_value": "市值(原幣)", "unrealized_pnl": "未實現(原幣)", "unrealized_pnl_pct": "報酬率%", "market_value_twd": "約當台幣市值", "quote_source": "報價來源"}
    out = out.rename(columns=ren)
    return out


def show_mobile_cards(df: pd.DataFrame, limit: int = 80):
    if df.empty:
        st.info("沒有資料。")
        return
    for _, r in df.head(limit).iterrows():
        pnl = safe_float(r.get("unrealized_pnl", 0))
        pnl_cls = "pnl-pos" if pnl >= 0 else "pnl-neg"
        st.markdown(f"""
        <div class="mobile-card">
          <div class="card-title">{r.get('symbol')}　{r.get('name')}</div>
          <div>{badge_for_market(r.get('market'))}<span class="badge badge-etf">{r.get('asset_type')}</span><span class="badge">{r.get('currency')}</span></div>
          <div class="mobile-row"><span>股數</span><b>{fmt_num(r.get('shares'),0)}</b></div>
          <div class="mobile-row"><span>成本 / 現價</span><b>{fmt_price(r.get('avg_cost'))} / {fmt_price(r.get('current_price'))}</b></div>
          <div class="mobile-row"><span>市值</span><b>{fmt_num(r.get('market_value'),0)} {r.get('currency')}</b></div>
          <div class="mobile-row"><span>未實現</span><b class="{pnl_cls}">{fmt_num(pnl,0)}（{fmt_num(r.get('unrealized_pnl_pct'),2)}%）</b></div>
          <div class="mobile-row"><span>今日漲跌</span><b>{fmt_num(r.get('change_pct'),2)}%</b></div>
        </div>
        """, unsafe_allow_html=True)

# -------------------------
# Sidebar
# -------------------------
PAGE_OPTIONS = ["總覽", "匯入/更新持股", "資料編輯", "買賣記帳", "台股個股", "台股ETF", "美股", "港股", "全球統計", "報價診斷"]
page = st.sidebar.radio("功能", PAGE_OPTIONS)
st.sidebar.caption(f"版本：{APP_VERSION}")
quote_mode = st.sidebar.selectbox("報價模式", ["live", "snapshot"], index=0, format_func=lambda x: "線上報價優先" if x == "live" else "只用匯入價")
auto_refresh = st.sidebar.toggle("自動刷新報價", value=False)
refresh_sec = st.sidebar.selectbox("刷新頻率", [60, 180, 300, 600], index=1, format_func=lambda x: f"{x//60} 分鐘")
if auto_refresh:
    st.markdown(f"<meta http-equiv='refresh' content='{int(refresh_sec)}'>", unsafe_allow_html=True)
    st.sidebar.success(f"每 {refresh_sec//60} 分鐘刷新。")
st.sidebar.info("美股、港股若已填股數/成本但暫時抓不到報價，系統會先用成本當暫估價，避免市值歸零。TJGC 請設為 US。")

portfolio = load_portfolio()
enriched = enrich_portfolio(portfolio, mode=quote_mode) if not portfolio.empty else pd.DataFrame()

# -------------------------
# Pages
# -------------------------
def kpi_row(df: pd.DataFrame):
    if df.empty:
        st.info("目前沒有持股資料。請到『匯入/更新持股』匯入 Excel 或貼上資料。")
        return
    total_value_twd = df["market_value_twd"].sum()
    total_cost_twd = df["cost_twd"].sum()
    total_pnl_twd = df["unrealized_pnl_twd"].sum()
    total_pnl_pct = total_pnl_twd / total_cost_twd * 100 if total_cost_twd else 0
    watch_count = int((df["shares"] <= 0).sum())
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("約當總市值 TWD", fmt_num(total_value_twd, 0))
    c2.metric("約當未實現 TWD", fmt_num(total_pnl_twd, 0), f"{total_pnl_pct:.2f}%")
    c3.metric("持股/觀察檔數", f"{len(df):,}", f"觀察 {watch_count} 檔")
    c4.metric("市場數", df["market"].nunique())


def show_overview():
    st.header("總覽")
    kpi_row(enriched)
    if enriched.empty:
        return
    st.subheader("資產配置")
    agg = enriched.groupby(["market_label"], as_index=False).agg({"market_value_twd":"sum", "unrealized_pnl_twd":"sum", "symbol":"count"}).rename(columns={"market_label":"市場", "market_value_twd":"約當台幣市值", "unrealized_pnl_twd":"未實現台幣", "symbol":"檔數"})
    col1, col2 = st.columns([1,1])
    with col1:
        fig = px.pie(agg, names="市場", values="約當台幣市值", title="市場配置（以約當台幣市值）")
        st.plotly_chart(fig, use_container_width=True)
    with col2:
        fig2 = px.bar(agg, x="市場", y="未實現台幣", text="未實現台幣", title="各市場未實現損益（TWD）")
        st.plotly_chart(fig2, use_container_width=True)
    st.subheader("持股明細")
    tabs = st.tabs(["桌機表格", "手機卡片"])
    with tabs[0]:
        st.dataframe(display_df(enriched).style.format({"股數":"{:,.0f}", "成本":"{:,.2f}", "現價":"{:,.2f}", "漲跌%":"{:,.2f}", "市值(原幣)":"{:,.0f}", "未實現(原幣)":"{:,.0f}", "報酬率%":"{:,.2f}", "約當台幣市值":"{:,.0f}"}, na_rep="-"), use_container_width=True, height=520)
    with tabs[1]:
        show_mobile_cards(enriched)


def show_import():
    st.header("匯入 / 更新持股")
    st.caption("支援 IFong 持股 Excel，也支援手機貼上格式；v7.1 起可貼上現價、市值、未實現損益。")
    mode = st.radio("匯入模式", ["完全取代目前資料", "更新同代號/新增"], horizontal=True)
    mode_key = "replace" if mode.startswith("完全") else "update"

    st.subheader("Excel 匯入")
    up = st.file_uploader("上傳 .xlsx", type=None, accept_multiple_files=False)
    if up is not None:
        try:
            incoming = parse_ifong_xlsx(up.getvalue())
            st.success(f"解析成功：{len(incoming)} 檔。")
            st.dataframe(incoming[["market", "asset_type", "symbol", "name", "shares", "avg_cost", "last_price"]], use_container_width=True)
            if st.button("確認匯入 Excel", type="primary", use_container_width=True):
                newdf = merge_portfolio(load_portfolio(), incoming, mode_key)
                save_portfolio(newdf)
                st.success("已匯入，請到總覽查看。")
                st.rerun()
        except Exception as exc:
            st.error(f"Excel 讀取失敗：{exc}")
            st.info("可以改用下方貼上格式。")

    st.subheader("手機備援：直接貼上")
    default_text = """2303.TW,聯電,4000,5.27,144,576000,554920,TW
5289.TWO,宜鼎,500,1774.6,1310,655000,-232300,TWO
NVDA,NVDA,0,0,0,0,0,US
TJGC,TJGC Group,0,0,0,0,0,US
1211.HK,比亞迪,0,0,0,0,0,HK"""
    txt = st.text_area("每行可貼：代號,名稱,股數,成本,現價,市值,未實現,市場；美股/港股沒有股數成本時可填 0", value="", placeholder=default_text, height=220)
    st.info("若要讓匯入後的市值與你的 Excel 截圖一致，請用含現價/市值的逗號格式，並在左側報價模式選『只用匯入價』核對。")
    if st.button("匯入貼上資料", use_container_width=True):
        incoming = parse_paste_text(txt)
        if incoming.empty:
            st.warning("沒有解析到資料。")
        else:
            newdf = merge_portfolio(load_portfolio(), incoming, mode_key)
            save_portfolio(newdf)
            st.success(f"已匯入 {len(incoming)} 檔。")
            st.rerun()

    st.subheader("下載目前資料")
    df = load_portfolio()
    st.download_button("下載 global_portfolio.csv", df.to_csv(index=False).encode("utf-8-sig"), "global_portfolio.csv", "text/csv")
    if not df.empty:
        st.text_area("目前資料的貼上備份格式", portfolio_to_paste_text(df), height=160)


def show_market_page(market_filter: list[str], title: str, asset_type: str | None = None):
    st.header(title)
    if enriched.empty:
        st.info("尚無資料。")
        return
    df = enriched[enriched["market"].isin(market_filter)].copy()
    if asset_type:
        df = df[df["asset_type"] == asset_type]
    kpi_row(df)
    if df.empty:
        st.info("此分類目前沒有資料。")
        return
    # ranking cards
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("漲幅前 5")
        st.dataframe(display_df(df.sort_values("change_pct", ascending=False).head(5)), use_container_width=True)
    with c2:
        st.subheader("跌幅前 5")
        st.dataframe(display_df(df.sort_values("change_pct", ascending=True).head(5)), use_container_width=True)
    st.subheader("明細")
    tab1, tab2 = st.tabs(["桌機表格", "手機卡片"])
    with tab1:
        st.dataframe(display_df(df).style.format({"股數":"{:,.0f}", "成本":"{:,.2f}", "現價":"{:,.2f}", "漲跌%":"{:,.2f}", "市值(原幣)":"{:,.0f}", "未實現(原幣)":"{:,.0f}", "報酬率%":"{:,.2f}", "約當台幣市值":"{:,.0f}"}, na_rep="-"), use_container_width=True, height=520)
    with tab2:
        show_mobile_cards(df)


def show_global_stats():
    st.header("全球統計")
    if enriched.empty:
        st.info("尚無資料。")
        return
    kpi_row(enriched)
    rates = fetch_fx_rates()
    st.caption(f"匯率估算：USD/TWD {rates.get('USD',0):.3f}；HKD/TWD {rates.get('HKD',0):.3f}。美股、港股若股數為 0，視為觀察清單，不計入市值。")
    by_mkt = enriched.groupby(["market", "market_label", "currency"], as_index=False).agg(
        檔數=("symbol", "count"),
        持股檔數=("shares", lambda x: int((x > 0).sum())),
        約當台幣市值=("market_value_twd", "sum"),
        約當台幣未實現=("unrealized_pnl_twd", "sum"),
        平均今日漲跌=("change_pct", "mean"),
    ).rename(columns={"market_label":"市場", "currency":"主要幣別"})
    st.subheader("市場統計")
    st.dataframe(by_mkt.style.format({"約當台幣市值":"{:,.0f}", "約當台幣未實現":"{:,.0f}", "平均今日漲跌":"{:,.2f}"}, na_rep="-"), use_container_width=True)
    col1, col2 = st.columns(2)
    with col1:
        fig = px.bar(by_mkt, x="市場", y="約當台幣市值", color="市場", title="市場市值比較")
        st.plotly_chart(fig, use_container_width=True)
    with col2:
        fig = px.bar(by_mkt, x="市場", y="平均今日漲跌", color="市場", title="各市場平均今日漲跌%")
        st.plotly_chart(fig, use_container_width=True)
    st.subheader("全持股漲跌排行")
    col3, col4 = st.columns(2)
    with col3:
        st.write("漲幅前 10")
        st.dataframe(display_df(enriched.sort_values("change_pct", ascending=False).head(10)), use_container_width=True)
    with col4:
        st.write("跌幅前 10")
        st.dataframe(display_df(enriched.sort_values("change_pct", ascending=True).head(10)), use_container_width=True)


def show_edit_data():
    st.header("資料編輯 / 手動維護")
    st.caption("可直接修改股數、成本、現價、名稱與市場。市場請用 TW / TWO / US / HK。修改後請按下方儲存。")
    df = load_portfolio()
    if df.empty:
        st.info("目前沒有資料。可先到『匯入/更新持股』貼上匯入。")
        df = pd.DataFrame(columns=PORTFOLIO_COLUMNS)

    edited = st.data_editor(
        df,
        use_container_width=True,
        num_rows="dynamic",
        hide_index=True,
        column_config={
            "symbol": st.column_config.TextColumn("代號", help="例如 2330、5289、NVDA、1211"),
            "market": st.column_config.SelectboxColumn("市場", options=["TW", "TWO", "US", "HK"], required=True),
            "asset_type": st.column_config.SelectboxColumn("類型", options=["股票", "ETF"], required=True),
            "currency": st.column_config.SelectboxColumn("幣別", options=["TWD", "USD", "HKD"], required=True),
            "shares": st.column_config.NumberColumn("股數", format="%.4f"),
            "avg_cost": st.column_config.NumberColumn("平均成本", format="%.4f"),
            "last_price": st.column_config.NumberColumn("匯入/手動現價", format="%.4f"),
        },
        key="portfolio_editor",
    )
    c1, c2 = st.columns(2)
    with c1:
        if st.button("儲存修改", type="primary", use_container_width=True):
            save_portfolio(edited)
            st.success("已儲存。")
            st.rerun()
    with c2:
        if st.button("重新載入", use_container_width=True):
            st.rerun()

    st.subheader("資料備份")
    st.download_button("下載目前持股 CSV", normalize_portfolio_df(edited).to_csv(index=False).encode("utf-8-sig"), "global_portfolio_backup.csv", "text/csv", use_container_width=True)
    st.text_area("手機貼上備份格式", portfolio_to_paste_text(edited), height=180)
    st.info("這版會把資料存到 Streamlit 執行環境的 data/global_portfolio.csv。一般重新整理不會消失；但如果重新部署、刪 App、或雲端容器重建，仍可能需要用備份還原。若要永久保存，下一步建議接 Supabase 或 Google Sheets。")


def show_trades():
    st.header("買賣記帳")
    st.caption("新增交易後會同步更新持股股數與平均成本。賣出會以目前平均成本估算已實現損益。")
    p = load_portfolio()
    tx = load_transactions()

    with st.form("trade_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        trade_date = c1.date_input("交易日期", value=datetime.now().date())
        market = c2.selectbox("市場", ["TW", "TWO", "US", "HK"], index=0)
        side = c3.selectbox("買賣", ["買進", "賣出"], index=0)
        c4, c5 = st.columns([1, 2])
        symbol_input = c4.text_input("股票代號", placeholder="例如 2330 / NVDA / 1211.HK")
        name_input = c5.text_input("股票名稱", placeholder="可空白，系統會沿用既有名稱")
        c6, c7, c8 = st.columns(3)
        shares = c6.number_input("股數", min_value=0.0, step=1.0, format="%.4f")
        price = c7.number_input("成交價格", min_value=0.0, step=0.01, format="%.4f")
        fee = c8.number_input("手續費", min_value=0.0, step=1.0, format="%.2f")
        c9, c10 = st.columns([1, 2])
        tax = c9.number_input("證交稅 / 交易稅", min_value=0.0, step=1.0, format="%.2f")
        note = c10.text_input("備註", placeholder="例如：加碼、停損、除息前調整")
        submitted = st.form_submit_button("新增交易並更新持股", type="primary", use_container_width=True)

    if submitted:
        sym, mkt = normalize_symbol_market(symbol_input, market)
        if not sym or shares <= 0 or price <= 0:
            st.warning("請輸入代號、股數與成交價格。")
        else:
            mask = (p["symbol"].astype(str).str.upper() == sym.upper()) & (p["market"].astype(str).str.upper() == mkt.upper()) if not p.empty else pd.Series([], dtype=bool)
            existing_name = p.loc[mask, "name"].iloc[0] if (not p.empty and mask.any()) else ""
            name = name_input.strip() or existing_name or sym
            trade = {
                "trade_date": str(trade_date), "market": mkt, "symbol": sym, "name": name, "side": side,
                "shares": shares, "price": price, "fee": fee, "tax": tax,
                "currency": currency_for_market(mkt), "amount": shares * price + fee + tax,
                "realized_pnl": 0.0, "note": note, "created_at": now_text()
            }
            newp, realized = apply_trade_to_portfolio(p, trade)
            trade["realized_pnl"] = realized
            save_portfolio(newp)
            tx = pd.concat([tx, pd.DataFrame([trade])], ignore_index=True)
            save_transactions(tx)
            st.success(f"已新增交易。估算已實現損益：{realized:,.0f} {trade['currency']}")
            st.rerun()

    st.subheader("交易紀錄")
    tx = load_transactions()
    if tx.empty:
        st.info("尚無交易紀錄。")
    else:
        st.dataframe(tx.style.format({"shares":"{:,.4f}", "price":"{:,.4f}", "fee":"{:,.2f}", "tax":"{:,.2f}", "amount":"{:,.2f}", "realized_pnl":"{:,.2f}"}, na_rep="-"), use_container_width=True, height=420)
        st.download_button("下載交易紀錄 CSV", tx.to_csv(index=False).encode("utf-8-sig"), "transactions_backup.csv", "text/csv", use_container_width=True)


def show_diag():
    st.header("報價診斷")
    if enriched.empty:
        st.info("尚無資料。")
        return
    cols = ["symbol", "name", "market", "yahoo_symbol", "current_price", "last_price", "quote_source", "change_pct", "shares", "avg_cost"]
    st.dataframe(enriched[cols].style.format({"current_price":"{:,.2f}", "last_price":"{:,.2f}", "change_pct":"{:,.2f}", "shares":"{:,.0f}", "avg_cost":"{:,.2f}"}, na_rep="-"), use_container_width=True, height=620)
    st.info("若港股或美股沒有報價，請確認 Yahoo Finance 代號。例如比亞迪為 1211.HK；TME(ADR) 已自動轉成 TME。TJGC 是美股 Nasdaq 代號，請設為市場 US；港股需使用 Yahoo 格式如 1211.HK。若股數為 0，只會顯示報價/漲跌，不會有市值與損益。若已填股數成本但報價為 0，系統會先以成本當暫估現價。")

if page == "總覽":
    show_overview()
elif page == "匯入/更新持股":
    show_import()
elif page == "資料編輯":
    show_edit_data()
elif page == "買賣記帳":
    show_trades()
elif page == "台股個股":
    show_market_page(["TW", "TWO"], "台股個股", asset_type="股票")
elif page == "台股ETF":
    show_market_page(["TW", "TWO"], "台股 ETF", asset_type="ETF")
elif page == "美股":
    show_market_page(["US"], "美股統計 / 觀察")
elif page == "港股":
    show_market_page(["HK"], "港股統計 / 觀察")
elif page == "全球統計":
    show_global_stats()
elif page == "報價診斷":
    show_diag()
