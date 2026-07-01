from __future__ import annotations

from datetime import datetime
from typing import Dict, List

import pandas as pd

from .indicators import add_indicators
from .market_data import fetch_history, fetch_quote


def _compare(value: float, operator: str, threshold: float) -> bool:
    if operator == ">=":
        return value >= threshold
    if operator == ">":
        return value > threshold
    if operator == "<=":
        return value <= threshold
    if operator == "<":
        return value < threshold
    if operator == "==":
        return value == threshold
    return False


def evaluate_alert(row: pd.Series) -> Dict:
    symbol = str(row.get("symbol", "")).strip()
    market = str(row.get("market", "TW") or "TW")
    name = str(row.get("name", symbol))
    rule_type = str(row.get("rule_type", "price"))
    operator = str(row.get("operator", ""))
    threshold = float(row.get("threshold", 0) or 0)

    result = {
        "triggered": False,
        "symbol": symbol,
        "name": name,
        "rule_type": rule_type,
        "message": "",
        "value": None,
    }

    if not symbol:
        result["message"] = "缺少股票代號"
        return result

    if rule_type == "price":
        q = fetch_quote(symbol, market)
        if q.price is None:
            result["message"] = "抓不到現價"
            return result
        triggered = _compare(q.price, operator, threshold)
        result.update({
            "triggered": triggered,
            "value": q.price,
            "message": f"{name}({symbol}) 現價 {q.price:.2f}，條件：價格 {operator} {threshold:.2f}",
        })
        return result

    hist = fetch_history(symbol, market, period="1y", interval="1d")
    if hist.empty:
        result["message"] = "抓不到歷史行情"
        return result
    ind = add_indicators(hist).dropna(subset=["Close"])
    if len(ind) < 2:
        result["message"] = "歷史資料不足"
        return result
    last = ind.iloc[-1]
    prev = ind.iloc[-2]
    close = float(last["Close"])

    if rule_type == "ma20_cross_down":
        ma20 = last.get("MA20")
        prev_ma20 = prev.get("MA20")
        if pd.isna(ma20) or pd.isna(prev_ma20):
            result["message"] = "MA20 資料不足"
            return result
        triggered = float(prev["Close"]) >= float(prev_ma20) and close < float(ma20)
        result.update({
            "triggered": triggered,
            "value": close,
            "message": f"{name}({symbol}) 跌破20MA：收盤/現價 {close:.2f}，20MA {float(ma20):.2f}",
        })
        return result

    if rule_type == "ma20_cross_up":
        ma20 = last.get("MA20")
        prev_ma20 = prev.get("MA20")
        if pd.isna(ma20) or pd.isna(prev_ma20):
            result["message"] = "MA20 資料不足"
            return result
        triggered = float(prev["Close"]) <= float(prev_ma20) and close > float(ma20)
        result.update({
            "triggered": triggered,
            "value": close,
            "message": f"{name}({symbol}) 站上20MA：收盤/現價 {close:.2f}，20MA {float(ma20):.2f}",
        })
        return result

    if rule_type == "rsi":
        rsi = last.get("RSI14")
        if pd.isna(rsi):
            result["message"] = "RSI 資料不足"
            return result
        triggered = _compare(float(rsi), operator, threshold)
        result.update({
            "triggered": triggered,
            "value": float(rsi),
            "message": f"{name}({symbol}) RSI14 {float(rsi):.1f}，條件：RSI {operator} {threshold:.1f}",
        })
        return result

    result["message"] = f"尚未支援的提醒類型：{rule_type}"
    return result


def evaluate_alerts(alerts_df: pd.DataFrame) -> List[Dict]:
    results = []
    enabled_df = alerts_df[alerts_df["enabled"] == True] if "enabled" in alerts_df.columns else alerts_df
    for _, row in enabled_df.iterrows():
        try:
            results.append(evaluate_alert(row))
        except Exception as exc:
            results.append({
                "triggered": False,
                "symbol": row.get("symbol", ""),
                "name": row.get("name", ""),
                "rule_type": row.get("rule_type", ""),
                "message": f"提醒檢查失敗：{exc}",
                "value": None,
            })
    return results


def stamp_trigger(alerts_df: pd.DataFrame, symbol: str, rule_type: str) -> pd.DataFrame:
    out = alerts_df.copy()
    mask = (out["symbol"].astype(str) == str(symbol)) & (out["rule_type"].astype(str) == str(rule_type))
    out.loc[mask, "last_triggered_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return out
