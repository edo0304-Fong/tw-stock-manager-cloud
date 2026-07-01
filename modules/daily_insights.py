from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import pandas as pd

from .market_data import fetch_history, fetch_quote
from .indicators import add_indicators, latest_signal


def _f(x: Any, default: float = 0.0) -> float:
    try:
        if pd.isna(x):
            return default
        return float(x)
    except Exception:
        return default


def _pct(x: float) -> str:
    if not math.isfinite(x):
        return "-"
    return f"{x:.1f}%"


def _money(x: float) -> str:
    if not math.isfinite(x):
        return "-"
    return f"{x:,.0f}"


def analyze_one_position(row: pd.Series) -> dict:
    symbol = str(row.get("symbol", "")).strip()
    name = str(row.get("name", "")).strip() or symbol
    market = str(row.get("market", "TW") or "TW")
    shares = _f(row.get("shares"))
    avg_cost = _f(row.get("avg_cost"))

    hist = fetch_history(symbol, market, period="1y", interval="1d")
    if hist.empty or len(hist) < 65:
        return {
            "代號": symbol, "名稱": name, "現價": 0.0, "報酬率%": 0.0, "技術分數": 0,
            "狀態": "資料不足", "動作": "觀察", "原因": "歷史行情不足，暫不判斷", "風險": "資料不足",
            "距52週高點%": 0.0, "距20MA%": 0.0, "RSI": 0.0, "成交量倍率": 0.0,
        }

    ind = add_indicators(hist).dropna(subset=["Close"])
    last = ind.iloc[-1]
    prev = ind.iloc[-2] if len(ind) >= 2 else last
    signal = latest_signal(hist)

    close = _f(last.get("Close"))
    high_52 = _f(ind["High"].tail(252).max(), close)
    low_52 = _f(ind["Low"].tail(252).min(), close)
    ma20 = _f(last.get("MA20"), float("nan"))
    ma60 = _f(last.get("MA60"), float("nan"))
    ma120 = _f(last.get("MA120"), float("nan"))
    rsi = _f(last.get("RSI14"), float("nan"))
    vol = _f(last.get("Volume"), 0.0)
    vol20 = _f(ind["Volume"].tail(20).mean(), 0.0)
    vol_ratio = vol / vol20 if vol20 else 0.0
    pnl_pct = (close - avg_cost) / avg_cost * 100 if avg_cost else 0.0
    pnl = (close - avg_cost) * shares if avg_cost and shares else 0.0
    from_high = (close / high_52 - 1) * 100 if high_52 else 0.0
    from_low = (close / low_52 - 1) * 100 if low_52 else 0.0
    from_ma20 = (close / ma20 - 1) * 100 if ma20 and math.isfinite(ma20) else 0.0
    from_ma60 = (close / ma60 - 1) * 100 if ma60 and math.isfinite(ma60) else 0.0

    score = int(signal.get("score", 0))
    signals = signal.get("signals", []) or []

    close_above_ma20 = math.isfinite(ma20) and close >= ma20
    close_above_ma60 = math.isfinite(ma60) and close >= ma60
    ma20_above_ma60 = math.isfinite(ma20) and math.isfinite(ma60) and ma20 >= ma60
    macd_hist = _f(last.get("MACD_HIST"), 0.0)
    macd_prev = _f(prev.get("MACD_HIST"), 0.0)

    tags = []
    reasons = []

    if close >= high_52 * 0.995:
        tags.append("52週新高")
        reasons.append("股價已逼近或刷新近一年高點，代表資金願意用更高價格承接")
    elif close >= ind["High"].tail(120).max() * 0.995:
        tags.append("半年新高")
        reasons.append("已接近近半年高點，短線趨勢明顯偏強")

    if close_above_ma20 and close_above_ma60 and ma20_above_ma60:
        tags.append("趨勢偏多")
        reasons.append("股價站在月線與季線之上，趨勢結構仍然健康")
    if vol_ratio >= 1.8 and close > _f(prev.get("Close"), close):
        tags.append("放量上攻")
        reasons.append(f"成交量約為20日均量的 {vol_ratio:.1f} 倍，屬於放量上漲")
    if macd_hist > 0 and macd_prev <= 0:
        tags.append("動能轉強")
        reasons.append("MACD柱狀體剛翻正，動能有轉強跡象")
    if rsi >= 75:
        tags.append("短線過熱")
        reasons.append(f"RSI 約 {rsi:.1f}，不適合在急漲後追高")
    if not close_above_ma20:
        tags.append("跌破月線")
        reasons.append("股價低於20日均線，短線防守需要更嚴格")
    if not close_above_ma60:
        tags.append("跌破季線")
        reasons.append("股價低於60日均線，中期趨勢轉弱")
    if pnl_pct <= -10:
        tags.append("成本壓力")
        reasons.append(f"以你的成本計算約虧損 {_pct(abs(pnl_pct))}，要避免變成長期套牢")

    action = "續抱觀察"
    status = "中性"
    risk = "中"

    if score >= 75 and close >= high_52 * 0.995:
        action = "強勢續抱，但不要追高加碼"
        status = "創高強勢"
        risk = "中"
    elif score >= 70 and close_above_ma20 and close_above_ma60 and rsi < 72:
        action = "仍有潛力，可等回測支撐或突破放量"
        status = "偏多"
        risk = "中低"
    elif score >= 60 and close_above_ma20:
        action = "續抱，觀察能否放量突破前高"
        status = "中性偏多"
        risk = "中"
    elif rsi >= 75 and pnl_pct > 8:
        action = "獲利部位可準備分批停利"
        status = "過熱"
        risk = "中高"
    elif score < 40 or (not close_above_ma20 and not close_above_ma60):
        action = "準備賣出或至少減碼觀察"
        status = "偏弱"
        risk = "高"
    elif pnl_pct <= -10 and not close_above_ma20:
        action = "列入停損檢討名單"
        status = "成本壓力偏高"
        risk = "高"

    reason_text = "；".join(reasons[:4]) if reasons else "尚未出現明確方向，先看月線與成交量是否表態"

    return {
        "代號": symbol,
        "名稱": name,
        "現價": close,
        "股數": shares,
        "成本": avg_cost,
        "未實現損益": pnl,
        "報酬率%": pnl_pct,
        "技術分數": score,
        "狀態": status,
        "動作": action,
        "原因": reason_text,
        "風險": risk,
        "標籤": "、".join(dict.fromkeys(tags)),
        "距52週高點%": from_high,
        "距52週低點%": from_low,
        "距20MA%": from_ma20,
        "距60MA%": from_ma60,
        "RSI": rsi if math.isfinite(rsi) else 0.0,
        "成交量倍率": vol_ratio,
        "技術訊號": "；".join(signals[:4]),
    }


def build_portfolio_diagnosis(portfolio: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    if portfolio is None or portfolio.empty:
        return pd.DataFrame(), "目前沒有持股資料，無法產生健檢。"

    rows = [analyze_one_position(row) for _, row in portfolio.iterrows()]
    df = pd.DataFrame(rows)
    if df.empty:
        return df, "目前資料不足。"

    # 分類挑選，避免每檔都用制式模板。
    new_high = df[df["標籤"].astype(str).str.contains("新高", na=False)].sort_values(["技術分數", "報酬率%"], ascending=False).head(5)
    sell_watch = df[
        (df["動作"].astype(str).str.contains("賣出|減碼|停損", na=False)) | (df["風險"] == "高")
    ].sort_values(["技術分數", "報酬率%"], ascending=[True, True]).head(6)
    potential = df[
        (df["動作"].astype(str).str.contains("潛力|續抱", na=False)) & (df["技術分數"] >= 60)
    ].sort_values(["技術分數", "成交量倍率"], ascending=False).head(6)
    overheat = df[df["標籤"].astype(str).str.contains("過熱", na=False)].sort_values("報酬率%", ascending=False).head(5)

    best = df.sort_values("技術分數", ascending=False).head(3)
    weakest = df.sort_values("技術分數", ascending=True).head(3)

    lines: list[str] = []
    lines.append("### 今日持股健檢")
    lines.append("今天的重點不是每檔都看一遍，而是先把『強勢續抱、該停利、該處理、可觀察加碼』分出來。")

    if not new_high.empty:
        names = "、".join([f"{r['名稱']}({r['代號']})" for _, r in new_high.iterrows()])
        lines.append(f"**創高/接近新高名單：{names}。** 這類股票資金動能較明顯，原則上不急著賣，但若 RSI 已偏高或漲幅離均線太遠，適合把停利線往上移，而不是追價加碼。")
    else:
        lines.append("**目前沒有明顯創 52 週新高的持股。** 這代表今天比較像整理盤，重點應放在有沒有跌破月線，以及弱勢股是否繼續拖累資金效率。")

    if not sell_watch.empty:
        detail = []
        for _, r in sell_watch.head(4).iterrows():
            detail.append(f"{r['名稱']}({r['代號']})：{r['動作']}，主因是{r['原因']}")
        lines.append("**應準備賣出/減碼觀察：** " + "；".join(detail) + "。這些部位建議不要只等反彈，應先設定明確停損或減碼價。")
    else:
        lines.append("**今天沒有很明確的停損清單。** 但仍建議檢查跌破 20MA 的股票，因為短線弱勢常常先從月線失守開始。")

    if not overheat.empty:
        detail = "、".join([f"{r['名稱']}({r['代號']}) RSI {r['RSI']:.1f}" for _, r in overheat.iterrows()])
        lines.append(f"**短線過熱提醒：{detail}。** 若這些股票同時已有獲利，適合準備分批停利或至少不要再追高。")

    if not potential.empty:
        detail = []
        for _, r in potential.head(5).iterrows():
            detail.append(f"{r['名稱']}({r['代號']})技術分數{int(r['技術分數'])}")
        lines.append("**仍有潛力的觀察名單：** " + "、".join(detail) + "。這些股票的共同點是趨勢沒有壞，下一步要看回測月線是否守住、或突破前高是否放量。")

    if not best.empty and not weakest.empty:
        b = "、".join([f"{r['名稱']}({r['代號']})" for _, r in best.iterrows()])
        w = "、".join([f"{r['名稱']}({r['代號']})" for _, r in weakest.iterrows()])
        lines.append(f"**資金效率排序上，技術面最強的是 {b}；目前最拖累的可能是 {w}。** 如果你要執行汰弱留強，應優先從後者檢討，而不是賣掉強勢股。")

    total_pnl = df["未實現損益"].sum()
    win_rate = (df["報酬率%"] > 0).mean() * 100 if len(df) else 0
    high_risk_count = int((df["風險"] == "高").sum())
    lines.append(f"整體來看，目前持股勝率約 {_pct(win_rate)}，未實現損益約 {_money(total_pnl)} 元，高風險觀察名單 {high_risk_count} 檔。這份健檢只做資訊整理，不代表自動買賣，最後仍要搭配你的資金配置和停損紀律。")

    return df, "\n\n".join(lines)
