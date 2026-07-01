from __future__ import annotations

import numpy as np
import pandas as pd


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if out.empty:
        return out

    close = out["Close"].astype(float)
    high = out["High"].astype(float)
    low = out["Low"].astype(float)

    for n in [5, 10, 20, 60, 120, 240]:
        out[f"MA{n}"] = close.rolling(n).mean()

    # RSI 14
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out["RSI14"] = 100 - (100 / (1 + rs))

    # MACD 12, 26, 9
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    out["MACD"] = ema12 - ema26
    out["MACD_SIGNAL"] = out["MACD"].ewm(span=9, adjust=False).mean()
    out["MACD_HIST"] = out["MACD"] - out["MACD_SIGNAL"]

    # KD 9
    low_min = low.rolling(9).min()
    high_max = high.rolling(9).max()
    rsv = (close - low_min) / (high_max - low_min).replace(0, np.nan) * 100
    out["K"] = rsv.ewm(com=2, adjust=False).mean()
    out["D"] = out["K"].ewm(com=2, adjust=False).mean()

    # Bollinger Bands 20, 2 std
    ma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    out["BB_MID"] = ma20
    out["BB_UPPER"] = ma20 + 2 * std20
    out["BB_LOWER"] = ma20 - 2 * std20

    # ATR 14
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    out["ATR14"] = tr.rolling(14).mean()

    return out


def latest_signal(df: pd.DataFrame) -> dict:
    if df.empty or len(df) < 60:
        return {"score": 0, "summary": "資料不足，無法判斷", "signals": []}

    ind = add_indicators(df).dropna(subset=["Close"])
    last = ind.iloc[-1]
    prev = ind.iloc[-2] if len(ind) >= 2 else last

    signals = []
    score = 50
    close = float(last["Close"])

    ma20 = last.get("MA20")
    ma60 = last.get("MA60")
    ma5 = last.get("MA5")
    ma10 = last.get("MA10")
    rsi = last.get("RSI14")

    if pd.notna(ma20) and close > ma20:
        signals.append("站上20日均線，短線趨勢偏多")
        score += 8
    elif pd.notna(ma20):
        signals.append("跌破20日均線，短線轉弱")
        score -= 10

    if pd.notna(ma60) and close > ma60:
        signals.append("站上60日均線，中期趨勢仍在")
        score += 8
    elif pd.notna(ma60):
        signals.append("跌破60日均線，中期趨勢轉弱")
        score -= 12

    if all(pd.notna(x) for x in [ma5, ma10, ma20]) and ma5 > ma10 > ma20:
        signals.append("5/10/20日均線呈多頭排列")
        score += 10

    if pd.notna(rsi):
        if rsi > 70:
            signals.append(f"RSI {rsi:.1f}，短線偏熱，追價風險升高")
            score -= 3
        elif rsi < 30:
            signals.append(f"RSI {rsi:.1f}，短線偏弱或超賣")
            score -= 5
        else:
            signals.append(f"RSI {rsi:.1f}，動能未過熱")
            score += 2

    if pd.notna(last.get("MACD_HIST")) and pd.notna(prev.get("MACD_HIST")):
        if last["MACD_HIST"] > 0 and prev["MACD_HIST"] <= 0:
            signals.append("MACD 柱狀體翻正，動能轉強")
            score += 8
        elif last["MACD_HIST"] < 0 and prev["MACD_HIST"] >= 0:
            signals.append("MACD 柱狀體翻負，動能轉弱")
            score -= 8

    if pd.notna(last.get("Volume")) and len(ind) >= 20:
        vol20 = ind["Volume"].tail(20).mean()
        if vol20 and last["Volume"] > vol20 * 1.8 and close > prev["Close"]:
            signals.append("放量上漲，買盤動能增強")
            score += 8
        elif vol20 and last["Volume"] > vol20 * 1.8 and close < prev["Close"]:
            signals.append("放量下跌，賣壓明顯增加")
            score -= 10

    score = int(max(0, min(100, score)))
    if score >= 75:
        summary = "技術面偏多，可續抱或觀察加碼條件"
    elif score >= 60:
        summary = "技術面中性偏多，仍可觀察"
    elif score >= 40:
        summary = "技術面中性偏弱，注意支撐"
    else:
        summary = "技術面偏弱，應列入減碼或停損觀察"
    return {"score": score, "summary": summary, "signals": signals}
