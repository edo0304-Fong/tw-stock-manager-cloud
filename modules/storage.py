from __future__ import annotations

from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
PORTFOLIO_PATH = DATA_DIR / "portfolio.csv"
ALERTS_PATH = DATA_DIR / "alerts.csv"
TRADES_PATH = DATA_DIR / "trades.csv"

# v5.3: 保留匯入時 Yahoo 截圖的價格與市值，避免盤中資料源抓不到時金額歸零或被錯誤報價覆蓋。
PORTFOLIO_COLUMNS = [
    "symbol", "name", "market", "shares", "avg_cost", "note",
    "last_price", "last_change", "last_change_pct", "last_market_value",
    "last_unrealized_pnl", "last_unrealized_pnl_pct", "last_quote_time",
]
ALERT_COLUMNS = [
    "symbol", "name", "rule_type", "operator", "threshold", "enabled", "last_triggered_at", "note"
]
TRADE_COLUMNS = [
    "date", "type", "symbol", "name", "market", "shares", "price", "fee", "tax", "total_amount", "realized_pnl", "note"
]


def ensure_data_files() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not PORTFOLIO_PATH.exists():
        pd.DataFrame(columns=PORTFOLIO_COLUMNS).to_csv(PORTFOLIO_PATH, index=False)
    if not ALERTS_PATH.exists():
        pd.DataFrame(columns=ALERT_COLUMNS).to_csv(ALERTS_PATH, index=False)
    if not TRADES_PATH.exists():
        pd.DataFrame(columns=TRADE_COLUMNS).to_csv(TRADES_PATH, index=False)


def _coerce_numeric_columns(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    for col in columns:
        if col in df.columns:
            df[col] = (
                df[col]
                .astype(str)
                .str.replace(",", "", regex=False)
                .str.replace("股", "", regex=False)
                .str.replace("TWD", "", regex=False)
                .str.replace("%", "", regex=False)
                .str.strip()
            )
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(float)
    return df


def load_portfolio() -> pd.DataFrame:
    ensure_data_files()
    df = pd.read_csv(PORTFOLIO_PATH, dtype={"symbol": str, "market": str, "name": str, "note": str, "last_quote_time": str})
    for col in PORTFOLIO_COLUMNS:
        if col not in df.columns:
            df[col] = "" if col in ["symbol", "name", "market", "note", "last_quote_time"] else 0
    df["market"] = df["market"].astype(str).replace({"nan": "TW", "": "TW"})
    df = _coerce_numeric_columns(df, [
        "shares", "avg_cost", "last_price", "last_change", "last_change_pct", "last_market_value",
        "last_unrealized_pnl", "last_unrealized_pnl_pct"
    ])
    return df[PORTFOLIO_COLUMNS]


def save_portfolio(df: pd.DataFrame) -> None:
    ensure_data_files()
    out = df.copy()
    for col in PORTFOLIO_COLUMNS:
        if col not in out.columns:
            out[col] = "" if col in ["symbol", "name", "market", "note", "last_quote_time"] else 0
    out["symbol"] = out["symbol"].astype(str).str.strip()
    out = out[out["symbol"] != ""]
    out.to_csv(PORTFOLIO_PATH, index=False)


def load_alerts() -> pd.DataFrame:
    ensure_data_files()
    df = pd.read_csv(ALERTS_PATH, dtype={"symbol": str, "name": str, "rule_type": str, "operator": str, "note": str})
    for col in ALERT_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df["threshold"] = pd.to_numeric(df["threshold"], errors="coerce").fillna(0).astype(float)
    df["enabled"] = df["enabled"].astype(str).str.upper().isin(["TRUE", "1", "YES", "Y"])
    return df[ALERT_COLUMNS]


def save_alerts(df: pd.DataFrame) -> None:
    ensure_data_files()
    out = df.copy()
    for col in ALERT_COLUMNS:
        if col not in out.columns:
            out[col] = ""
    out["symbol"] = out["symbol"].astype(str).str.strip()
    out = out[out["symbol"] != ""]
    out.to_csv(ALERTS_PATH, index=False)


def normalize_market_symbol(symbol: str, market: str = "TW") -> tuple[str, str]:
    """Return (pure_symbol, market) from inputs such as 2330.TW or 5289.TWO."""
    raw = str(symbol or "").strip().upper()
    mkt = str(market or "TW").strip().upper()
    if raw.endswith(".TWO"):
        return raw[:-4], "TWO"
    if raw.endswith(".TW"):
        return raw[:-3], "TW"
    if mkt in ["TPEX", "OTC"]:
        mkt = "TWO"
    if mkt not in ["TW", "TWO"]:
        mkt = "TW"
    return raw, mkt


def normalize_portfolio_import(df: pd.DataFrame) -> pd.DataFrame:
    """Convert common portfolio CSV formats into the app portfolio schema.

    Supports native columns and the Yahoo screenshot CSV columns:
    股票代號、股票名稱、持有股數、持股成本均價、股價、漲跌、漲跌幅%、市值、未實現損益、未實現報酬率%.
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=PORTFOLIO_COLUMNS)

    out = pd.DataFrame()
    cols = {str(c).strip().replace("\ufeff", ""): c for c in df.columns}

    def pick(*names, default=None):
        for name in names:
            if name in cols:
                return df[cols[name]]
        if default is None:
            return pd.Series([""] * len(df))
        return pd.Series([default] * len(df))

    out["symbol"] = pick("symbol", "股票代號", "代號", "股號", "ticker")
    out["name"] = pick("name", "股票名稱", "名稱", "股名")
    out["shares"] = pick("shares", "持有股數", "股數", "庫存股數", "持股")
    out["avg_cost"] = pick("avg_cost", "持股成本均價", "平均成本", "成本均價", "成本")
    out["market"] = pick("market", "市場", default="TW")
    out["note"] = pick("note", "備註", default="CSV匯入")
    out["last_price"] = pick("last_price", "current_price", "股價", "現價", default=0)
    out["last_change"] = pick("last_change", "change", "漲跌", default=0)
    out["last_change_pct"] = pick("last_change_pct", "change_pct", "漲跌幅%", "今日漲跌%", default=0)
    out["last_market_value"] = pick("last_market_value", "market_value", "市值", default=0)
    out["last_unrealized_pnl"] = pick("last_unrealized_pnl", "unrealized_pnl", "未實現損益", default=0)
    out["last_unrealized_pnl_pct"] = pick("last_unrealized_pnl_pct", "unrealized_pnl_pct", "未實現報酬率%", "報酬率%", default=0)
    out["last_quote_time"] = pick("last_quote_time", "更新時間", default="CSV匯入")

    symbols = []
    markets = []
    for sym, mkt in zip(out["symbol"], out["market"]):
        s2, m2 = normalize_market_symbol(sym, mkt)
        symbols.append(s2)
        markets.append(m2)
    out["symbol"] = symbols
    out["market"] = markets

    out["name"] = out["name"].astype(str).str.strip()
    out["note"] = out["note"].astype(str).str.strip().replace({"nan": "CSV匯入", "": "CSV匯入"})
    out = _coerce_numeric_columns(out, [
        "shares", "avg_cost", "last_price", "last_change", "last_change_pct", "last_market_value",
        "last_unrealized_pnl", "last_unrealized_pnl_pct"
    ])
    # 如果 CSV 有股價但沒有市值/未實現損益，就補算，避免金額錯。
    missing_mv = out["last_market_value"].fillna(0) <= 0
    out.loc[missing_mv, "last_market_value"] = out.loc[missing_mv, "shares"] * out.loc[missing_mv, "last_price"]
    missing_pnl = out["last_unrealized_pnl"].fillna(0) == 0
    calc_pnl = out["last_market_value"] - (out["shares"] * out["avg_cost"])
    out.loc[missing_pnl, "last_unrealized_pnl"] = calc_pnl.loc[missing_pnl]
    cost = out["shares"] * out["avg_cost"]
    out["last_unrealized_pnl_pct"] = out["last_unrealized_pnl_pct"].where(
        out["last_unrealized_pnl_pct"].abs() > 0,
        out["last_unrealized_pnl"] / cost.replace(0, pd.NA) * 100,
    ).fillna(0)

    out = out[out["symbol"].astype(str).str.strip() != ""]
    return out[PORTFOLIO_COLUMNS]


def merge_portfolio(current: pd.DataFrame, incoming: pd.DataFrame, mode: str = "update") -> pd.DataFrame:
    current = normalize_portfolio_import(current) if current is not None and not current.empty else pd.DataFrame(columns=PORTFOLIO_COLUMNS)
    incoming = normalize_portfolio_import(incoming)
    if mode == "replace":
        return incoming
    if mode == "append":
        merged = pd.concat([current, incoming], ignore_index=True)
        rows = []
        for symbol, g in merged.groupby("symbol", dropna=False):
            shares = g["shares"].sum()
            avg_cost = (g["shares"] * g["avg_cost"]).sum() / shares if shares else 0
            last = g.iloc[-1].to_dict()
            last["shares"] = shares
            last["avg_cost"] = avg_cost
            rows.append(last)
        return pd.DataFrame(rows)[PORTFOLIO_COLUMNS]
    merged = pd.concat([current, incoming], ignore_index=True)
    merged = merged.drop_duplicates(subset=["symbol"], keep="last")
    return merged[PORTFOLIO_COLUMNS]


def load_trades() -> pd.DataFrame:
    ensure_data_files()
    df = pd.read_csv(TRADES_PATH, dtype={"type": str, "symbol": str, "name": str, "market": str, "note": str})
    for col in TRADE_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    for col in ["shares", "price", "fee", "tax", "total_amount", "realized_pnl"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(float)
    df["date"] = df["date"].astype(str)
    df["type"] = df["type"].astype(str).str.upper().replace({"BUY": "BUY", "SELL": "SELL", "買進": "BUY", "賣出": "SELL"})
    return df[TRADE_COLUMNS]


def save_trades(df: pd.DataFrame) -> None:
    ensure_data_files()
    out = df.copy()
    for col in TRADE_COLUMNS:
        if col not in out.columns:
            out[col] = ""
    out["symbol"] = out["symbol"].astype(str).str.strip()
    out = out[out["symbol"] != ""]
    out.to_csv(TRADES_PATH, index=False)


def normalize_trade_import(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame(columns=TRADE_COLUMNS)
    cols = {str(c).strip().replace("\ufeff", ""): c for c in df.columns}

    def pick(*names, default=None):
        for name in names:
            if name in cols:
                return df[cols[name]]
        if default is None:
            return pd.Series([""] * len(df))
        return pd.Series([default] * len(df))

    out = pd.DataFrame()
    out["date"] = pick("date", "日期", "交易日期")
    out["type"] = pick("type", "交易類型", "買賣", "類型")
    out["symbol"] = pick("symbol", "股票代號", "代號", "股號")
    out["name"] = pick("name", "股票名稱", "名稱", "股名")
    out["market"] = pick("market", "市場", default="TW")
    out["shares"] = pick("shares", "股數", "交易股數", "成交股數")
    out["price"] = pick("price", "價格", "成交價", "買進價格", "賣出價格")
    out["fee"] = pick("fee", "手續費", default=0)
    out["tax"] = pick("證交稅", "交易稅", "tax", default=0)
    out["total_amount"] = pick("total_amount", "交易金額", "總金額", default=0)
    out["realized_pnl"] = pick("realized_pnl", "已實現損益", default=0)
    out["note"] = pick("note", "備註", default="交易CSV匯入")

    symbols, markets = [], []
    for sym, mkt in zip(out["symbol"], out["market"]):
        s2, m2 = normalize_market_symbol(sym, mkt)
        symbols.append(s2)
        markets.append(m2)
    out["symbol"] = symbols
    out["market"] = markets
    out["type"] = out["type"].astype(str).str.upper().replace({"買進": "BUY", "買": "BUY", "B": "BUY", "BUY": "BUY", "賣出": "SELL", "賣": "SELL", "S": "SELL", "SELL": "SELL"})
    for col in ["shares", "price", "fee", "tax", "total_amount", "realized_pnl"]:
        out[col] = out[col].astype(str).str.replace(",", "", regex=False).str.strip()
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0).astype(float)
    out = out[out["symbol"].astype(str).str.strip() != ""]
    return out[TRADE_COLUMNS]


def apply_trade_to_portfolio(portfolio: pd.DataFrame, trade: dict) -> tuple[pd.DataFrame, float, str]:
    """Apply one BUY/SELL trade to portfolio and return (new_portfolio, realized_pnl, message)."""
    portfolio = load_portfolio() if portfolio is None else portfolio.copy()
    if portfolio.empty:
        portfolio = pd.DataFrame(columns=PORTFOLIO_COLUMNS)
    for col in PORTFOLIO_COLUMNS:
        if col not in portfolio.columns:
            portfolio[col] = "" if col in ["symbol", "name", "market", "note", "last_quote_time"] else 0
    symbol, market = normalize_market_symbol(trade.get("symbol", ""), trade.get("market", "TW"))
    name = str(trade.get("name", "")).strip()
    side = str(trade.get("type", "BUY")).upper()
    shares = float(trade.get("shares", 0) or 0)
    price = float(trade.get("price", 0) or 0)
    fee = float(trade.get("fee", 0) or 0)
    tax = float(trade.get("tax", 0) or 0)
    mask = portfolio["symbol"].astype(str).str.upper() == symbol.upper()
    realized_pnl = 0.0

    if shares <= 0 or price <= 0:
        return portfolio, realized_pnl, "股數與價格必須大於 0。"

    if side == "BUY":
        buy_cost = shares * price + fee + tax
        if mask.any():
            idx = portfolio[mask].index[0]
            old_shares = float(portfolio.at[idx, "shares"] or 0)
            old_cost = float(portfolio.at[idx, "avg_cost"] or 0)
            new_shares = old_shares + shares
            new_avg = ((old_shares * old_cost) + buy_cost) / new_shares if new_shares else 0
            portfolio.at[idx, "shares"] = new_shares
            portfolio.at[idx, "avg_cost"] = round(new_avg, 4)
            if name:
                portfolio.at[idx, "name"] = name
            portfolio.at[idx, "market"] = market
        else:
            new_row = {col: 0 for col in PORTFOLIO_COLUMNS}
            new_row.update({"symbol": symbol, "name": name, "market": market, "shares": shares, "avg_cost": round(buy_cost / shares, 4), "note": "交易新增"})
            portfolio = pd.concat([portfolio, pd.DataFrame([new_row])], ignore_index=True)
        return portfolio[PORTFOLIO_COLUMNS], realized_pnl, "買進已更新持股與平均成本。"

    if side == "SELL":
        if not mask.any():
            return portfolio, realized_pnl, "找不到持股，無法賣出。"
        idx = portfolio[mask].index[0]
        old_shares = float(portfolio.at[idx, "shares"] or 0)
        avg_cost = float(portfolio.at[idx, "avg_cost"] or 0)
        if shares > old_shares:
            return portfolio, realized_pnl, f"賣出股數 {shares:,.0f} 超過目前持股 {old_shares:,.0f}。"
        sell_proceeds = shares * price - fee - tax
        cost_basis = shares * avg_cost
        realized_pnl = sell_proceeds - cost_basis
        new_shares = old_shares - shares
        portfolio.at[idx, "shares"] = new_shares
        if new_shares <= 0:
            portfolio = portfolio.drop(index=idx)
        return portfolio[PORTFOLIO_COLUMNS], realized_pnl, "賣出已扣除股數並估算已實現損益。"

    return portfolio[PORTFOLIO_COLUMNS], realized_pnl, "交易類型需為 BUY 或 SELL。"
