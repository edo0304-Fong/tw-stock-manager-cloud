from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import time

import pandas as pd
import requests
import yfinance as yf


@dataclass
class Quote:
    symbol: str
    yahoo_symbol: str
    price: Optional[float]
    previous_close: Optional[float]
    change: Optional[float]
    change_pct: Optional[float]
    source: str = "-"
    quote_time: str = ""
    error: str = ""


def to_yahoo_symbol(symbol: str, market: str = "TW") -> str:
    """Convert Taiwan stock symbol to Yahoo Finance ticker.

    Listed stocks/ETFs usually use .TW. OTC stocks usually use .TWO.
    """
    symbol = str(symbol).strip().upper()
    market = str(market or "TW").upper().strip()
    if symbol.endswith(".TW") or symbol.endswith(".TWO"):
        return symbol
    if market in ["TWO", "OTC", "TPEX"]:
        return f"{symbol}.TWO"
    return f"{symbol}.TW"


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _as_float(v) -> Optional[float]:
    try:
        if v is None or pd.isna(v):
            return None
        return float(v)
    except Exception:
        return None


def fetch_history(symbol: str, market: str = "TW", period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    ticker = to_yahoo_symbol(symbol, market)
    try:
        df = yf.download(ticker, period=period, interval=interval, auto_adjust=False, progress=False, threads=False)
    except Exception:
        return pd.DataFrame(columns=["Date", "Open", "High", "Low", "Close", "Volume"])
    if df.empty:
        return pd.DataFrame(columns=["Date", "Open", "High", "Low", "Close", "Volume"])
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df = df.reset_index()
    if "Datetime" in df.columns:
        df = df.rename(columns={"Datetime": "Date"})
    keep = [c for c in ["Date", "Open", "High", "Low", "Close", "Volume"] if c in df.columns]
    df = df[keep].copy()
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["Close"])


def fetch_yahoo_quote_batch(symbols: list[tuple[str, str]], timeout: int = 8) -> dict[str, Quote]:
    """Batch fetch quote from Yahoo Finance quote endpoint.

    This is usually faster and more suitable for portfolio refresh than yfinance.download per ticker.
    If it fails, caller can fallback to yfinance or imported snapshot prices.
    """
    out: dict[str, Quote] = {}
    if not symbols:
        return out
    yahoo_symbols = [to_yahoo_symbol(sym, mkt) for sym, mkt in symbols]
    # Deduplicate while preserving order.
    yahoo_symbols = list(dict.fromkeys(yahoo_symbols))
    url = "https://query1.finance.yahoo.com/v7/finance/quote"
    headers = {"User-Agent": "Mozilla/5.0"}
    for start in range(0, len(yahoo_symbols), 80):
        batch = yahoo_symbols[start:start + 80]
        try:
            resp = requests.get(url, params={"symbols": ",".join(batch), "lang": "zh-TW", "region": "TW"}, headers=headers, timeout=timeout)
            resp.raise_for_status()
            data = resp.json().get("quoteResponse", {}).get("result", [])
        except Exception as exc:
            for ys in batch:
                out[ys] = Quote(ys.split(".")[0], ys, None, None, None, None, source="YahooQuote失敗", quote_time=_now_text(), error=str(exc))
            continue
        for item in data:
            ys = item.get("symbol", "")
            price = _as_float(item.get("regularMarketPrice"))
            previous_close = _as_float(item.get("regularMarketPreviousClose"))
            change = _as_float(item.get("regularMarketChange"))
            change_pct = _as_float(item.get("regularMarketChangePercent"))
            if price is not None and previous_close is not None and change is None:
                change = price - previous_close
            if change is not None and previous_close not in [None, 0] and change_pct is None:
                change_pct = change / previous_close * 100
            qtime = item.get("regularMarketTime")
            if isinstance(qtime, (int, float)):
                try:
                    qtime = datetime.fromtimestamp(qtime).strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    qtime = _now_text()
            else:
                qtime = _now_text()
            out[ys] = Quote(ys.split(".")[0], ys, price, previous_close, change, change_pct, source="YahooQuote", quote_time=str(qtime), error="")
        missing = set(batch) - set(out.keys())
        for ys in missing:
            out[ys] = Quote(ys.split(".")[0], ys, None, None, None, None, source="YahooQuote無資料", quote_time=_now_text(), error="no result")
        time.sleep(0.1)
    return out


def fetch_quote_yfinance(symbol: str, market: str = "TW") -> Quote:
    ticker = to_yahoo_symbol(symbol, market)
    # 先嘗試盤中 1 分 K；抓不到時退回 5 日日 K
    try:
        intraday = fetch_history(symbol, market, period="1d", interval="1m")
        if not intraday.empty:
            last = intraday.dropna(subset=["Close"]).tail(1)
            if not last.empty:
                price = float(last["Close"].iloc[0])
                prev_daily = fetch_history(symbol, market, period="5d", interval="1d")
                previous_close = None
                if len(prev_daily) >= 2:
                    previous_close = float(prev_daily["Close"].iloc[-2])
                elif len(prev_daily) == 1:
                    previous_close = float(prev_daily["Close"].iloc[-1])
                change = price - previous_close if previous_close else None
                change_pct = change / previous_close * 100 if previous_close else None
                return Quote(symbol, ticker, price, previous_close, change, change_pct, source="yfinance 1m", quote_time=_now_text())

        daily = fetch_history(symbol, market, period="5d", interval="1d")
        if daily.empty:
            return Quote(symbol, ticker, None, None, None, None, source="yfinance無資料", quote_time=_now_text())
        price = float(daily["Close"].iloc[-1])
        previous_close = float(daily["Close"].iloc[-2]) if len(daily) >= 2 else None
        change = price - previous_close if previous_close else None
        change_pct = change / previous_close * 100 if previous_close else None
        return Quote(symbol, ticker, price, previous_close, change, change_pct, source="yfinance日K", quote_time=_now_text())
    except Exception as exc:
        return Quote(symbol, ticker, None, None, None, None, source="yfinance失敗", quote_time=_now_text(), error=str(exc))


def fetch_quote(symbol: str, market: str = "TW") -> Quote:
    ys = to_yahoo_symbol(symbol, market)
    qmap = fetch_yahoo_quote_batch([(symbol, market)])
    q = qmap.get(ys)
    if q and q.price is not None:
        return q
    return fetch_quote_yfinance(symbol, market)


def _snapshot_quote(row: pd.Series) -> Quote:
    symbol = str(row.get("symbol", ""))
    market = str(row.get("market", "TW"))
    ticker = to_yahoo_symbol(symbol, market)
    price = _as_float(row.get("last_price"))
    if price == 0:
        price = None
    change = _as_float(row.get("last_change"))
    change_pct = _as_float(row.get("last_change_pct"))
    prev = None
    if price is not None and change not in [None, 0]:
        try:
            prev = price - change
        except Exception:
            prev = None
    return Quote(symbol, ticker, price, prev, change, change_pct, source="匯入截圖價", quote_time=str(row.get("last_quote_time", "CSV匯入") or "CSV匯入"), error="")


def enrich_portfolio_with_quotes(portfolio: pd.DataFrame, quote_source: str = "mixed") -> pd.DataFrame:
    """Attach quote, market value and P/L columns to portfolio.

    quote_source:
    - mixed: YahooQuote -> yfinance -> imported snapshot price
    - yahoo: YahooQuote -> yfinance; no snapshot fallback unless both fail for display safety
    - snapshot: use imported CSV/screenshot price only
    """
    if portfolio is None or portfolio.empty:
        return pd.DataFrame()
    quote_source = str(quote_source or "mixed").lower()
    rows = []

    batch_quotes: dict[str, Quote] = {}
    if quote_source in ["mixed", "yahoo", "live"]:
        pairs = [(str(r.get("symbol")), str(r.get("market", "TW"))) for _, r in portfolio.iterrows()]
        batch_quotes = fetch_yahoo_quote_batch(pairs)

    for _, row in portfolio.iterrows():
        symbol = str(row.get("symbol", ""))
        market = str(row.get("market", "TW"))
        ys = to_yahoo_symbol(symbol, market)
        snap = _snapshot_quote(row)

        if quote_source == "snapshot":
            q = snap
        else:
            q = batch_quotes.get(ys)
            if q is None or q.price is None:
                yf_q = fetch_quote_yfinance(symbol, market)
                q = yf_q if yf_q.price is not None else snap
            # mixed/live 若真的都沒有現價，才用截圖價，避免金額變 0。
            if q.price is None:
                q = snap

        price = float(q.price or 0.0)
        shares = float(row.get("shares", 0) or 0)
        avg_cost = float(row.get("avg_cost", 0) or 0)
        cost = shares * avg_cost
        market_value = shares * price
        pnl = market_value - cost
        pnl_pct = pnl / cost * 100 if cost else 0.0
        rows.append({
            **row.to_dict(),
            "yahoo_symbol": q.yahoo_symbol,
            "current_price": price,
            "previous_close": q.previous_close,
            "change": q.change,
            "change_pct": q.change_pct,
            "quote_source": q.source,
            "quote_time": q.quote_time,
            "quote_error": q.error,
            "cost": cost,
            "market_value": market_value,
            "unrealized_pnl": pnl,
            "unrealized_pnl_pct": pnl_pct,
        })
    return pd.DataFrame(rows)
