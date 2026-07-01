from __future__ import annotations

from datetime import datetime
from html import unescape
from urllib.parse import quote_plus
import math
import re
import xml.etree.ElementTree as ET

import pandas as pd
import requests
import yfinance as yf

from .market_data import to_yahoo_symbol, fetch_history
from .indicators import latest_signal
from .news_discussions import HEADERS, infer_sentiment, sentiment_summary, fetch_google_news, fetch_discussions

COMMON_TW_UNIVERSE = [
    {"symbol":"2330","name":"台積電","market":"TW"},{"symbol":"2317","name":"鴻海","market":"TW"},{"symbol":"2454","name":"聯發科","market":"TW"},
    {"symbol":"2308","name":"台達電","market":"TW"},{"symbol":"2382","name":"廣達","market":"TW"},{"symbol":"3231","name":"緯創","market":"TW"},
    {"symbol":"6669","name":"緯穎","market":"TW"},{"symbol":"2379","name":"瑞昱","market":"TW"},{"symbol":"2357","name":"華碩","market":"TW"},
    {"symbol":"3008","name":"大立光","market":"TW"},{"symbol":"3661","name":"世芯-KY","market":"TW"},{"symbol":"3443","name":"創意","market":"TW"},
    {"symbol":"3034","name":"聯詠","market":"TW"},{"symbol":"3017","name":"奇鋐","market":"TW"},{"symbol":"3324","name":"雙鴻","market":"TWO"},
    {"symbol":"3653","name":"健策","market":"TW"},{"symbol":"2059","name":"川湖","market":"TW"},{"symbol":"2345","name":"智邦","market":"TW"},
    {"symbol":"3711","name":"日月光投控","market":"TW"},{"symbol":"2303","name":"聯電","market":"TW"},{"symbol":"2408","name":"南亞科","market":"TW"},
    {"symbol":"2327","name":"國巨","market":"TW"},{"symbol":"2881","name":"富邦金","market":"TW"},{"symbol":"2882","name":"國泰金","market":"TW"},
    {"symbol":"2886","name":"兆豐金","market":"TW"},{"symbol":"2891","name":"中信金","market":"TW"},{"symbol":"2884","name":"玉山金","market":"TW"},
    {"symbol":"2892","name":"第一金","market":"TW"},{"symbol":"5880","name":"合庫金","market":"TW"},{"symbol":"1101","name":"台泥","market":"TW"},
    {"symbol":"1102","name":"亞泥","market":"TW"},{"symbol":"1301","name":"台塑","market":"TW"},{"symbol":"1303","name":"南亞","market":"TW"},
    {"symbol":"2002","name":"中鋼","market":"TW"},{"symbol":"2207","name":"和泰車","market":"TW"},{"symbol":"2603","name":"長榮","market":"TW"},
    {"symbol":"2609","name":"陽明","market":"TW"},{"symbol":"2615","name":"萬海","market":"TW"},{"symbol":"2618","name":"長榮航","market":"TW"},
    {"symbol":"2610","name":"華航","market":"TW"},{"symbol":"1513","name":"中興電","market":"TW"},{"symbol":"1519","name":"華城","market":"TW"},
    {"symbol":"1504","name":"東元","market":"TW"},{"symbol":"2301","name":"光寶科","market":"TW"},{"symbol":"2356","name":"英業達","market":"TW"},
    {"symbol":"2353","name":"宏碁","market":"TW"},{"symbol":"2474","name":"可成","market":"TW"},{"symbol":"8046","name":"南電","market":"TW"},
    {"symbol":"2376","name":"技嘉","market":"TW"},{"symbol":"6285","name":"啟碁","market":"TW"},{"symbol":"4938","name":"和碩","market":"TW"},
    {"symbol":"3037","name":"欣興","market":"TW"},{"symbol":"2352","name":"佳世達","market":"TW"},{"symbol":"3294","name":"英濟","market":"TWO"},
    {"symbol":"6515","name":"穎崴","market":"TW"},{"symbol":"5274","name":"信驊","market":"TWO"},{"symbol":"8299","name":"群聯","market":"TWO"},
    {"symbol":"5483","name":"中美晶","market":"TWO"},{"symbol":"4966","name":"譜瑞-KY","market":"TWO"},{"symbol":"4961","name":"天鈺","market":"TW"},
    {"symbol":"6409","name":"旭隼","market":"TW"},{"symbol":"1560","name":"中砂","market":"TWO"},{"symbol":"2231","name":"為升","market":"TW"},
    {"symbol":"0050","name":"元大台灣50","market":"TW"},{"symbol":"0056","name":"元大高股息","market":"TW"},{"symbol":"006208","name":"富邦台50","market":"TW"},
    {"symbol":"00631L","name":"元大台灣50正2","market":"TW"},{"symbol":"00713","name":"元大台灣高息低波","market":"TW"},{"symbol":"00878","name":"國泰永續高股息","market":"TW"},
    {"symbol":"00881","name":"國泰台灣5G+","market":"TW"},{"symbol":"00919","name":"群益台灣精選高息","market":"TW"},{"symbol":"00929","name":"復華台灣科技優息","market":"TW"},
    {"symbol":"00940","name":"元大台灣價值高息","market":"TW"},{"symbol":"00981A","name":"主動統一台股增長","market":"TW"},{"symbol":"00990A","name":"主動野村臺灣優選","market":"TW"},
]


# 常用台股 ETF 池：用於 ETF 專區；不是全市場官方清單，但涵蓋常見市值型、高股息、槓桿反向、債券、產業與主動式 ETF。
ETF_UNIVERSE = [
    {"symbol":"0050","name":"元大台灣50","market":"TW"},{"symbol":"0051","name":"元大中型100","market":"TW"},
    {"symbol":"0052","name":"富邦科技","market":"TW"},{"symbol":"0053","name":"元大電子","market":"TW"},
    {"symbol":"0055","name":"元大MSCI金融","market":"TW"},{"symbol":"0056","name":"元大高股息","market":"TW"},
    {"symbol":"0061","name":"元大寶滬深","market":"TW"},{"symbol":"006203","name":"元大MSCI台灣","market":"TW"},
    {"symbol":"006204","name":"永豐臺灣加權","market":"TW"},{"symbol":"006208","name":"富邦台50","market":"TW"},
    {"symbol":"00631L","name":"元大台灣50正2","market":"TW"},{"symbol":"00632R","name":"元大台灣50反1","market":"TW"},
    {"symbol":"00633L","name":"富邦上証正2","market":"TW"},{"symbol":"00634R","name":"富邦上証反1","market":"TW"},
    {"symbol":"00637L","name":"元大滬深300正2","market":"TW"},{"symbol":"00638R","name":"元大滬深300反1","market":"TW"},
    {"symbol":"00646","name":"元大S&P500","market":"TW"},{"symbol":"00647L","name":"元大S&P500正2","market":"TW"},
    {"symbol":"00648R","name":"元大S&P500反1","market":"TW"},{"symbol":"00650L","name":"復華香港正2","market":"TW"},
    {"symbol":"00651R","name":"復華香港反1","market":"TW"},{"symbol":"00657","name":"國泰日經225","market":"TW"},
    {"symbol":"00660","name":"元大歐洲50","market":"TW"},{"symbol":"00662","name":"富邦NASDAQ","market":"TW"},
    {"symbol":"00663L","name":"國泰臺灣加權正2","market":"TW"},{"symbol":"00664R","name":"國泰臺灣加權反1","market":"TW"},
    {"symbol":"00668","name":"國泰美國道瓊","market":"TW"},{"symbol":"00670L","name":"富邦NASDAQ正2","market":"TW"},
    {"symbol":"00671R","name":"富邦NASDAQ反1","market":"TW"},{"symbol":"00675L","name":"富邦臺灣加權正2","market":"TW"},
    {"symbol":"00676R","name":"富邦臺灣加權反1","market":"TW"},{"symbol":"00678","name":"群益NBI生技","market":"TW"},
    {"symbol":"00679B","name":"元大美債20年","market":"TW"},{"symbol":"00687B","name":"國泰20年美債","market":"TW"},
    {"symbol":"00692","name":"富邦公司治理","market":"TW"},{"symbol":"00701","name":"國泰股利精選30","market":"TW"},
    {"symbol":"00713","name":"元大台灣高息低波","market":"TW"},{"symbol":"00730","name":"富邦臺灣優質高息","market":"TW"},
    {"symbol":"00733","name":"富邦臺灣中小","market":"TW"},{"symbol":"00752","name":"中信中國50","market":"TW"},
    {"symbol":"00757","name":"統一FANG+","market":"TW"},{"symbol":"00762","name":"元大全球AI","market":"TW"},
    {"symbol":"00770","name":"國泰北美科技","market":"TW"},{"symbol":"00771","name":"元大US高息特別股","market":"TW"},
    {"symbol":"00795B","name":"中信美國公債20年","market":"TW"},{"symbol":"00830","name":"國泰費城半導體","market":"TW"},
    {"symbol":"00850","name":"元大臺灣ESG永續","market":"TW"},{"symbol":"00878","name":"國泰永續高股息","market":"TW"},
    {"symbol":"00881","name":"國泰台灣5G+","market":"TW"},{"symbol":"00882","name":"中信中國高股息","market":"TW"},
    {"symbol":"00891","name":"中信關鍵半導體","market":"TW"},{"symbol":"00892","name":"富邦台灣半導體","market":"TW"},
    {"symbol":"00893","name":"國泰智能電動車","market":"TW"},{"symbol":"00895","name":"富邦未來車","market":"TW"},
    {"symbol":"00900","name":"富邦特選高股息30","market":"TW"},{"symbol":"00901","name":"永豐智能車供應鏈","market":"TW"},
    {"symbol":"00905","name":"FT臺灣Smart","market":"TW"},{"symbol":"00907","name":"永豐優息存股","market":"TW"},
    {"symbol":"00915","name":"凱基優選高股息30","market":"TW"},{"symbol":"00918","name":"大華優利高填息30","market":"TW"},
    {"symbol":"00919","name":"群益台灣精選高息","market":"TW"},{"symbol":"00922","name":"國泰台灣領袖50","market":"TW"},
    {"symbol":"00923","name":"群益台ESG低碳50","market":"TW"},{"symbol":"00927","name":"群益半導體收益","market":"TW"},
    {"symbol":"00929","name":"復華台灣科技優息","market":"TW"},{"symbol":"00930","name":"永豐ESG低碳高息","market":"TW"},
    {"symbol":"00932","name":"兆豐永續高息等權","market":"TW"},{"symbol":"00934","name":"中信成長高股息","market":"TW"},
    {"symbol":"00935","name":"野村臺灣新科技50","market":"TW"},{"symbol":"00936","name":"台新永續高息中小","market":"TW"},
    {"symbol":"00939","name":"統一台灣高息動能","market":"TW"},{"symbol":"00940","name":"元大台灣價值高息","market":"TW"},
    {"symbol":"00941","name":"中信上游半導體","market":"TW"},{"symbol":"00944","name":"野村趨勢動能高息","market":"TW"},
    {"symbol":"00946","name":"群益科技高息成長","market":"TW"},{"symbol":"00980A","name":"主動野村臺灣優選","market":"TW"},
    {"symbol":"00981A","name":"主動統一台股增長","market":"TW"},{"symbol":"00982A","name":"主動群益台灣強棒","market":"TW"},
    {"symbol":"00990A","name":"主動元大AI新經濟","market":"TW"},
]


def is_etf(symbol: str, name: str = "") -> bool:
    sym = str(symbol or "").strip().upper()
    nm = str(name or "")
    if sym in {e["symbol"] for e in ETF_UNIVERSE}:
        return True
    keywords = ["ETF", "高股息", "高息", "台灣50", "臺灣50", "正2", "反1", "美債", "公債", "NASDAQ", "S&P", "日經", "滬深", "上証", "主動"]
    if any(k.lower() in nm.lower() for k in keywords):
        return True
    return bool(re.match(r"^00\d{2,4}[A-Z]?$", sym)) and any(k in nm for k in ["元大", "富邦", "國泰", "群益", "復華", "中信", "統一", "野村", "永豐", "兆豐", "凱基", "台新", "大華", "ETF"])


def classify_etf(symbol: str, name: str = "") -> str:
    nm = str(name or "")
    sym = str(symbol or "").upper()
    if not is_etf(sym, nm):
        return ""
    if sym.endswith("L") or "正2" in nm or "槓桿" in nm:
        return "槓桿型"
    if sym.endswith("R") or "反1" in nm or "反向" in nm:
        return "反向型"
    if "主動" in nm or sym.endswith("A"):
        return "主動式"
    if any(k in nm for k in ["高股息", "高息", "優息", "收益", "股利", "填息"]):
        return "高股息"
    if any(k in nm for k in ["美債", "公債", "債", "特別股"]):
        return "債券/收益"
    if any(k in nm for k in ["半導體", "科技", "AI", "5G", "電動車", "未來車", "生技", "金融", "電子"]):
        return "產業型"
    if any(k in nm for k in ["S&P", "NASDAQ", "日經", "歐洲", "中國", "香港", "滬深", "上証", "全球", "FANG"]):
        return "海外/跨境"
    if any(k in nm for k in ["0050", "台灣50", "臺灣50", "MSCI", "加權", "公司治理", "ESG", "低碳", "領袖50", "中型100"]):
        return "市值/寬基"
    return "其他ETF"


def add_security_type(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy()
    out["security_type"] = out.apply(lambda r: "ETF" if is_etf(r.get("symbol", ""), r.get("name", "")) else "股票", axis=1)
    out["etf_category"] = out.apply(lambda r: classify_etf(r.get("symbol", ""), r.get("name", "")) if r.get("security_type") == "ETF" else "", axis=1)
    return out


def _to_float(x, default: float | None = None):
    try:
        s = str(x).replace(",", "").replace("--", "").replace("-", "").replace("%", "").strip()
        if s == "":
            return default
        return float(s)
    except Exception:
        return default


def _clean(text: str) -> str:
    text = unescape(str(text or ""))
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def universe_from_portfolio(portfolio: pd.DataFrame | None = None, include_common: bool = True) -> pd.DataFrame:
    rows = []
    if include_common:
        rows.extend(COMMON_TW_UNIVERSE)
        rows.extend(ETF_UNIVERSE)
    if portfolio is not None and not portfolio.empty:
        for _, r in portfolio.iterrows():
            rows.append({
                "symbol": str(r.get("symbol", "")).strip(),
                "name": str(r.get("name", "")).strip(),
                "market": str(r.get("market", "TW") or "TW"),
            })
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["symbol", "name", "market"])
    df = df[df["symbol"].astype(str).str.strip() != ""]
    return df.drop_duplicates(subset=["symbol"], keep="last").reset_index(drop=True)


def fetch_twse_daily() -> pd.DataFrame:
    """Official TWSE daily all-stock quote. Best-effort parser because column names may vary."""
    url = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    try:
        data = requests.get(url, headers=HEADERS, timeout=15).json()
    except Exception:
        return pd.DataFrame()
    if not isinstance(data, list):
        return pd.DataFrame()
    df = pd.DataFrame(data)
    if df.empty:
        return df

    def pick(*candidates):
        for c in candidates:
            if c in df.columns:
                return c
        return None

    col_code = pick("Code", "證券代號", "股票代號", "code")
    col_name = pick("Name", "證券名稱", "股票名稱", "name")
    col_close = pick("ClosingPrice", "收盤價", "Close", "closing_price")
    col_change = pick("Change", "漲跌價差", "漲跌", "change")
    col_open = pick("OpeningPrice", "開盤價", "Open")
    col_high = pick("HighestPrice", "最高價", "High")
    col_low = pick("LowestPrice", "最低價", "Low")
    col_volume = pick("TradeVolume", "成交股數", "成交量", "Volume")

    out = pd.DataFrame()
    out["symbol"] = df[col_code].astype(str).str.strip() if col_code else ""
    out["name"] = df[col_name].astype(str).str.strip() if col_name else ""
    out["market"] = "TW"
    out["close"] = df[col_close].map(_to_float) if col_close else None
    out["change"] = df[col_change].map(lambda x: _signed_number(x)) if col_change else None
    out["open"] = df[col_open].map(_to_float) if col_open else None
    out["high"] = df[col_high].map(_to_float) if col_high else None
    out["low"] = df[col_low].map(_to_float) if col_low else None
    out["volume"] = df[col_volume].map(_to_float) if col_volume else None
    out["change_pct"] = out.apply(lambda r: (r["change"] / (r["close"] - r["change"]) * 100) if pd.notna(r["change"]) and pd.notna(r["close"]) and (r["close"] - r["change"]) else None, axis=1)
    return out.dropna(subset=["close"])


def _signed_number(x):
    raw = str(x).replace(",", "").strip()
    if raw in ["", "--"]:
        return None
    # TWSE sometimes uses X0.00 for unchanged or plain signed strings.
    raw = raw.replace("X", "").replace("+", "")
    try:
        return float(raw)
    except Exception:
        return None


def fetch_twse_pe_yield() -> pd.DataFrame:
    url = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL"
    try:
        data = requests.get(url, headers=HEADERS, timeout=15).json()
    except Exception:
        return pd.DataFrame()
    if not isinstance(data, list):
        return pd.DataFrame()
    df = pd.DataFrame(data)
    if df.empty:
        return df

    def pick(*candidates):
        for c in candidates:
            if c in df.columns:
                return c
        return None

    col_code = pick("Code", "證券代號", "股票代號", "code")
    col_name = pick("Name", "證券名稱", "股票名稱", "name")
    col_pe = pick("PEratio", "本益比", "P/E Ratio", "本益比(倍)")
    col_yield = pick("DividendYield", "殖利率", "股利殖利率", "Dividend Yield(%)")
    col_pb = pick("PBratio", "股價淨值比", "P/B Ratio")

    out = pd.DataFrame()
    out["symbol"] = df[col_code].astype(str).str.strip() if col_code else ""
    out["name"] = df[col_name].astype(str).str.strip() if col_name else ""
    out["pe_ratio"] = df[col_pe].map(_to_float) if col_pe else None
    out["dividend_yield"] = df[col_yield].map(_to_float) if col_yield else None
    out["pb_ratio"] = df[col_pb].map(_to_float) if col_pb else None
    return out


def fetch_yahoo_batch(universe: pd.DataFrame, period: str = "1y") -> pd.DataFrame:
    if universe is None or universe.empty:
        return pd.DataFrame()
    tickers = [to_yahoo_symbol(r.symbol, r.market) for r in universe.itertuples()]
    try:
        raw = yf.download(" ".join(tickers), period=period, interval="1d", group_by="ticker", auto_adjust=False, progress=False, threads=True)
    except Exception:
        raw = pd.DataFrame()
    rows = []
    for r in universe.itertuples():
        ys = to_yahoo_symbol(r.symbol, r.market)
        close_series = pd.Series(dtype=float)
        volume_series = pd.Series(dtype=float)
        if not raw.empty:
            try:
                if isinstance(raw.columns, pd.MultiIndex):
                    close_series = pd.to_numeric(raw[(ys, "Close")], errors="coerce").dropna()
                    volume_series = pd.to_numeric(raw[(ys, "Volume")], errors="coerce").dropna()
                else:
                    close_series = pd.to_numeric(raw["Close"], errors="coerce").dropna()
                    volume_series = pd.to_numeric(raw["Volume"], errors="coerce").dropna()
            except Exception:
                pass
        if close_series.empty:
            hist = fetch_history(r.symbol, r.market, period=period, interval="1d")
            if not hist.empty:
                close_series = pd.to_numeric(hist["Close"], errors="coerce").dropna()
                volume_series = pd.to_numeric(hist.get("Volume", pd.Series(dtype=float)), errors="coerce").dropna()
        if close_series.empty:
            continue
        close = float(close_series.iloc[-1])
        prev = float(close_series.iloc[-2]) if len(close_series) >= 2 else None
        chg = close - prev if prev else None
        chg_pct = chg / prev * 100 if prev else None
        high_52 = float(close_series.tail(252).max()) if len(close_series) else close
        low_52 = float(close_series.tail(252).min()) if len(close_series) else close
        vol = float(volume_series.iloc[-1]) if not volume_series.empty else None
        vol20 = float(volume_series.tail(20).mean()) if len(volume_series) >= 5 else None
        rows.append({
            "symbol": r.symbol, "name": r.name, "market": r.market, "close": close,
            "change": chg, "change_pct": chg_pct, "volume": vol, "volume_ratio": vol / vol20 if vol and vol20 else None,
            "high_52w": high_52, "low_52w": low_52, "distance_to_52w_high_pct": (close / high_52 - 1) * 100 if high_52 else None,
            "source": "Yahoo Finance/yfinance",
        })
    return pd.DataFrame(rows)


def fetch_yahoo_fundamentals(universe: pd.DataFrame, max_items: int = 80) -> pd.DataFrame:
    rows = []
    if universe is None or universe.empty:
        return pd.DataFrame(columns=["symbol", "pe_ratio", "dividend_yield", "pb_ratio"])
    for r in universe.head(max_items).itertuples():
        try:
            info = yf.Ticker(to_yahoo_symbol(r.symbol, r.market)).get_info()
        except Exception:
            info = {}
        dy = info.get("dividendYield")
        if dy is not None and dy < 1:
            dy = dy * 100
        rows.append({
            "symbol": r.symbol,
            "pe_ratio": info.get("trailingPE") or info.get("forwardPE"),
            "dividend_yield": dy,
            "pb_ratio": info.get("priceToBook"),
        })
    return pd.DataFrame(rows)


def build_market_screener(portfolio: pd.DataFrame | None = None, include_common: bool = True, fetch_yahoo_info: bool = False) -> tuple[pd.DataFrame, dict]:
    universe = universe_from_portfolio(portfolio, include_common=include_common)
    source_notes = []

    official_quote = fetch_twse_daily()
    official_fund = fetch_twse_pe_yield()

    if not official_quote.empty:
        base = official_quote
        missing_universe = universe[~universe["symbol"].astype(str).isin(base["symbol"].astype(str))] if not universe.empty and "symbol" in base.columns else universe
        if missing_universe is not None and not missing_universe.empty:
            yahoo_missing = fetch_yahoo_batch(missing_universe, period="1y")
            if not yahoo_missing.empty:
                base = pd.concat([base, yahoo_missing], ignore_index=True, sort=False)
        source_notes.append("上市行情：TWSE OpenAPI；缺漏/上櫃/部分ETF：Yahoo Finance 備援")
    else:
        base = fetch_yahoo_batch(universe, period="1y")
        source_notes.append("行情：Yahoo Finance/yfinance 備援")

    if not official_fund.empty:
        base = base.merge(official_fund[["symbol", "pe_ratio", "dividend_yield", "pb_ratio"]], on="symbol", how="left")
        source_notes.append("本益比/殖利率：TWSE OpenAPI")
    elif fetch_yahoo_info:
        fin = fetch_yahoo_fundamentals(universe, max_items=80)
        base = base.merge(fin, on="symbol", how="left") if not base.empty else fin
        source_notes.append("本益比/殖利率：Yahoo Finance 備援，可能不完整")
    else:
        for c in ["pe_ratio", "dividend_yield", "pb_ratio"]:
            if c not in base.columns:
                base[c] = None
        source_notes.append("本益比/殖利率：未啟用慢速備援，若官方資料抓不到會空白")

    if not universe.empty and not base.empty:
        base = base.merge(universe[["symbol", "name", "market"]].rename(columns={"name":"u_name", "market":"u_market"}), on="symbol", how="left")
        base["name"] = base.get("name", pd.Series(dtype=str)).fillna(base["u_name"]).replace("", pd.NA).fillna(base["u_name"])
        base["market"] = base.get("market", pd.Series(dtype=str)).fillna(base["u_market"])
        base = base.drop(columns=[c for c in ["u_name", "u_market"] if c in base.columns])

    for c in ["close", "change", "change_pct", "volume", "volume_ratio", "pe_ratio", "dividend_yield", "pb_ratio", "distance_to_52w_high_pct"]:
        if c in base.columns:
            base[c] = pd.to_numeric(base[c], errors="coerce")

    base = add_security_type(base)
    preferred = ["symbol", "name", "market", "security_type", "etf_category", "close", "change_pct", "change", "volume", "volume_ratio", "dividend_yield", "pe_ratio", "pb_ratio", "distance_to_52w_high_pct", "source"]
    ordered = [c for c in preferred if c in base.columns] + [c for c in base.columns if c not in preferred]
    base = base[ordered]
    meta = {"source_notes": "；".join(source_notes), "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    return base, meta


def _view_cols(df: pd.DataFrame) -> list[str]:
    return [c for c in ["symbol", "name", "market", "security_type", "etf_category", "close", "change_pct", "change", "volume", "volume_ratio", "dividend_yield", "pe_ratio", "pb_ratio", "distance_to_52w_high_pct"] if c in df.columns]


def top_rankings(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    if df is None or df.empty:
        return {}
    out = {}
    view_cols = _view_cols(df)
    if "change_pct" in df.columns:
        out["漲幅前十"] = df.dropna(subset=["change_pct"]).sort_values("change_pct", ascending=False).head(10)[view_cols]
        out["跌幅前十"] = df.dropna(subset=["change_pct"]).sort_values("change_pct", ascending=True).head(10)[view_cols]
    if "dividend_yield" in df.columns:
        out["殖利率前十"] = df.dropna(subset=["dividend_yield"]).query("dividend_yield > 0").sort_values("dividend_yield", ascending=False).head(10)[view_cols]
    if "pe_ratio" in df.columns:
        valid_pe = df.dropna(subset=["pe_ratio"]).query("pe_ratio > 0")
        if "security_type" in valid_pe.columns:
            valid_pe = valid_pe[valid_pe["security_type"] != "ETF"]
        out["本益比最低前十"] = valid_pe.sort_values("pe_ratio", ascending=True).head(10)[view_cols]
    if "volume_ratio" in df.columns:
        out["量能放大前十"] = df.dropna(subset=["volume_ratio"]).sort_values("volume_ratio", ascending=False).head(10)[view_cols]
    if "distance_to_52w_high_pct" in df.columns:
        out["接近52週新高前十"] = df.dropna(subset=["distance_to_52w_high_pct"]).sort_values("distance_to_52w_high_pct", ascending=False).head(10)[view_cols]
    return out


def top_etf_rankings(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    if df is None or df.empty:
        return {}
    etf = add_security_type(df)
    etf = etf[etf["security_type"] == "ETF"].copy()
    if etf.empty:
        return {}
    out = {}
    view_cols = _view_cols(etf)
    if "change_pct" in etf.columns:
        out["ETF漲幅前十"] = etf.dropna(subset=["change_pct"]).sort_values("change_pct", ascending=False).head(10)[view_cols]
        out["ETF跌幅前十"] = etf.dropna(subset=["change_pct"]).sort_values("change_pct", ascending=True).head(10)[view_cols]
    if "volume" in etf.columns:
        out["ETF成交量前十"] = etf.dropna(subset=["volume"]).sort_values("volume", ascending=False).head(10)[view_cols]
    if "dividend_yield" in etf.columns:
        dy = etf.dropna(subset=["dividend_yield"]).query("dividend_yield > 0")
        if not dy.empty:
            out["ETF殖利率前十"] = dy.sort_values("dividend_yield", ascending=False).head(10)[view_cols]
    if "volume_ratio" in etf.columns:
        out["ETF量能放大前十"] = etf.dropna(subset=["volume_ratio"]).sort_values("volume_ratio", ascending=False).head(10)[view_cols]
    if "distance_to_52w_high_pct" in etf.columns:
        out["ETF接近52週新高"] = etf.dropna(subset=["distance_to_52w_high_pct"]).sort_values("distance_to_52w_high_pct", ascending=False).head(10)[view_cols]
    for category in ["高股息", "市值/寬基", "主動式", "槓桿型", "反向型", "債券/收益", "產業型", "海外/跨境"]:
        sub = etf[etf["etf_category"] == category] if "etf_category" in etf.columns else pd.DataFrame()
        if not sub.empty and "change_pct" in sub.columns:
            out[f"{category}ETF"] = sub.dropna(subset=["change_pct"]).sort_values("change_pct", ascending=False).head(10)[view_cols]
    return out


def fetch_market_news_feed(limit: int = 80) -> pd.DataFrame:
    query = quote_plus('台股 個股 ETF AI 法人 營收 創高 漲停 題材')
    url = f"https://news.google.com/rss/search?q={query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception:
        return pd.DataFrame(columns=["source", "title", "published", "url", "sentiment"])
    rows = []
    for item in root.findall(".//item"):
        title = _clean(item.findtext("title"))
        link = _clean(item.findtext("link"))
        pub = _clean(item.findtext("pubDate"))
        source_el = item.find("source")
        source = _clean(source_el.text if source_el is not None else "Google News")
        if title:
            rows.append({"source": source, "title": title, "published": pub, "url": link, "sentiment": infer_sentiment(title)})
        if len(rows) >= limit:
            break
    return pd.DataFrame(rows)


def _match_title_to_universe(title: str, universe: pd.DataFrame) -> list[dict]:
    title_l = str(title).lower()
    matches = []
    for r in universe.itertuples():
        sym = str(r.symbol)
        name = str(r.name)
        if not sym or not name:
            continue
        if sym in title_l or name.lower() in title_l:
            matches.append({"symbol": sym, "name": name, "market": r.market})
    return matches


def build_daily_trend_radar(portfolio: pd.DataFrame | None = None, scan_my_holdings_first: bool = True, limit: int = 10) -> tuple[pd.DataFrame, pd.DataFrame]:
    universe = universe_from_portfolio(portfolio, include_common=True)
    feed = fetch_market_news_feed(limit=100)
    score: dict[str, dict] = {}

    def touch(sym: str, name: str, market: str, title: str, source: str, url: str, sentiment: str, points: float):
        if sym not in score:
            score[sym] = {"代號": sym, "名稱": name, "市場": market, "分數": 0.0, "新聞數": 0, "討論數": 0, "偏多": 0, "偏空": 0, "代表標題": [], "連結": []}
        item = score[sym]
        item["分數"] += points
        item["新聞數"] += 1 if source != "討論區" else 0
        item["討論數"] += 1 if source == "討論區" else 0
        if sentiment == "偏多":
            item["偏多"] += 1
            item["分數"] += 1.5
        elif sentiment == "偏空":
            item["偏空"] += 1
            item["分數"] += 1.0
        if len(item["代表標題"]) < 3:
            item["代表標題"].append(title)
            item["連結"].append(url)

    if not feed.empty:
        for _, row in feed.iterrows():
            title = str(row.get("title", ""))
            sentiment = str(row.get("sentiment", "中性"))
            for m in _match_title_to_universe(title, universe):
                touch(m["symbol"], m["name"], m["market"], title, str(row.get("source", "新聞")), str(row.get("url", "")), sentiment, 4.0)

    # 對目前持股做較精準的新聞/討論掃描，讓每日雷達能兼顧使用者自己的部位。
    if scan_my_holdings_first and portfolio is not None and not portfolio.empty:
        for _, r in portfolio.head(12).iterrows():
            sym = str(r.get("symbol", ""))
            name = str(r.get("name", ""))
            market = str(r.get("market", "TW") or "TW")
            ndf = fetch_google_news(sym, name, limit=5)
            ddf = fetch_discussions(sym, name, limit=5)
            for _, nr in ndf.iterrows():
                touch(sym, name, market, str(nr.get("title", "")), str(nr.get("source", "新聞")), str(nr.get("url", "")), str(nr.get("sentiment", "中性")), 3.0)
            for _, dr in ddf.iterrows():
                touch(sym, name, market, str(dr.get("title", "")), "討論區", str(dr.get("url", "")), str(dr.get("sentiment", "中性")), 2.0)

    rows = []
    for item in score.values():
        # 加入技術面小判斷，避免只有新聞熱度。
        try:
            hist = fetch_history(item["代號"], item["市場"], period="6mo", interval="1d")
            sig = latest_signal(hist)
            tech = int(sig.get("score", 0))
            item["分數"] += tech / 25
            item["技術分數"] = tech
            item["技術判斷"] = sig.get("summary", "")
        except Exception:
            item["技術分數"] = 0
            item["技術判斷"] = "技術資料不足"
        titles = item.pop("代表標題", [])
        links = item.pop("連結", [])
        item["代表標題"] = "\n".join([f"- {t}" for t in titles])
        item["第一連結"] = links[0] if links else ""
        if item["偏多"] > item["偏空"]:
            item["情緒"] = "偏多"
        elif item["偏空"] > item["偏多"]:
            item["情緒"] = "偏空"
        else:
            item["情緒"] = "中性"
        item["注意理由"] = _trend_reason(item)
        rows.append(item)

    radar = pd.DataFrame(rows)
    if radar.empty:
        return pd.DataFrame(columns=["排名", "代號", "名稱", "分數", "注意理由"]), feed
    radar = radar.sort_values("分數", ascending=False).head(limit).reset_index(drop=True)
    radar.insert(0, "排名", range(1, len(radar) + 1))
    radar["分數"] = radar["分數"].round(1)
    return radar, feed


def _trend_reason(item: dict) -> str:
    pieces = []
    if item.get("新聞數", 0):
        pieces.append(f"新聞{int(item['新聞數'])}則")
    if item.get("討論數", 0):
        pieces.append(f"討論{int(item['討論數'])}則")
    if item.get("情緒") == "偏多":
        pieces.append("標題/討論偏多")
    elif item.get("情緒") == "偏空":
        pieces.append("偏空消息較多，適合觀察是否為轉折風險")
    if item.get("技術分數", 0) >= 70:
        pieces.append("技術面偏強")
    elif item.get("技術分數", 0) <= 40 and item.get("技術分數", 0) > 0:
        pieces.append("技術面偏弱，僅適合風險觀察")
    return "；".join(pieces) if pieces else "市場提及度上升"
