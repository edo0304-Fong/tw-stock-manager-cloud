from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from html import unescape
from typing import Iterable
from urllib.parse import quote_plus, urljoin
import re
import xml.etree.ElementTree as ET

import pandas as pd
import requests

try:
    from bs4 import BeautifulSoup
except Exception:  # pragma: no cover - app will show a friendly error
    BeautifulSoup = None


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36"
    )
}

NEWS_COLUMNS = ["source", "title", "published", "url", "sentiment", "summary"]
DISCUSSION_COLUMNS = ["source", "title", "published", "url", "engagement", "sentiment", "summary"]

POSITIVE_WORDS = [
    "利多", "看多", "上看", "調高", "買進", "加碼", "成長", "創高", "突破", "噴", "大漲", "旺", "強勢", "回升",
    "優於", "轉強", "題材", "AI", "伺服器", "訂單", "獲利", "EPS", "填息", "配息", "外資買超", "投信買超",
]
NEGATIVE_WORDS = [
    "利空", "看空", "下修", "賣出", "減碼", "衰退", "轉弱", "跌破", "崩", "大跌", "虧損", "停損", "套牢", "爆雷",
    "不如", "疑慮", "風險", "法說失望", "外資賣超", "投信賣超", "跌", "殺", "破線",
]


def _clean_text(text: str) -> str:
    text = unescape(str(text or ""))
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def infer_sentiment(text: str) -> str:
    text = str(text or "")
    pos = sum(1 for w in POSITIVE_WORDS if w.lower() in text.lower())
    neg = sum(1 for w in NEGATIVE_WORDS if w.lower() in text.lower())
    if pos > neg:
        return "偏多"
    if neg > pos:
        return "偏空"
    return "中性"


def short_summary(title: str, source: str = "") -> str:
    sentiment = infer_sentiment(title)
    if sentiment == "偏多":
        prefix = "標題語氣偏多，建議確認是否有基本面或籌碼面支撐。"
    elif sentiment == "偏空":
        prefix = "標題語氣偏空，建議確認是否涉及營運、法說或籌碼轉弱。"
    else:
        prefix = "標題偏中性，可作為觀察資訊。"
    return f"{prefix} 來源：{source or '未標示'}。"


def empty_news_df() -> pd.DataFrame:
    return pd.DataFrame(columns=NEWS_COLUMNS)


def empty_discussion_df() -> pd.DataFrame:
    return pd.DataFrame(columns=DISCUSSION_COLUMNS)


def dedupe_rows(rows: list[dict], key: str = "url", limit: int = 10) -> list[dict]:
    seen = set()
    out = []
    for r in rows:
        k = str(r.get(key) or r.get("title") or "").strip()
        if not k or k in seen:
            continue
        seen.add(k)
        out.append(r)
        if len(out) >= limit:
            break
    return out


def fetch_google_news(symbol: str, name: str, limit: int = 10) -> pd.DataFrame:
    """Fetch recent stock-related headlines from Google News RSS.

    This is intentionally lightweight for a local MVP. It stores only titles, source,
    timestamps and links; it does not copy full articles.
    """
    q = quote_plus(f'"{name}" {symbol} 台股 OR 股價 OR 營收 OR 法人')
    url = f"https://news.google.com/rss/search?q={q}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=12)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception:
        return empty_news_df()

    rows = []
    for item in root.findall(".//item"):
        title = _clean_text(item.findtext("title"))
        link = _clean_text(item.findtext("link"))
        pub = _clean_text(item.findtext("pubDate"))
        source_el = item.find("source")
        source = _clean_text(source_el.text if source_el is not None else "Google News")
        if not title:
            continue
        rows.append({
            "source": source or "Google News",
            "title": title,
            "published": pub,
            "url": link,
            "sentiment": infer_sentiment(title),
            "summary": short_summary(title, source),
        })
    rows = dedupe_rows(rows, limit=limit)
    return pd.DataFrame(rows, columns=NEWS_COLUMNS)


def fetch_ptt_stock(symbol: str, name: str, limit: int = 10) -> pd.DataFrame:
    if BeautifulSoup is None:
        return empty_discussion_df()

    rows: list[dict] = []
    queries = [name, symbol]
    for q in queries:
        if not q:
            continue
        url = f"https://www.ptt.cc/bbs/Stock/search?q={quote_plus(str(q))}"
        try:
            resp = requests.get(url, headers=HEADERS, cookies={"over18": "1"}, timeout=12)
            resp.raise_for_status()
        except Exception:
            continue
        soup = BeautifulSoup(resp.text, "html.parser")
        for ent in soup.select("div.r-ent"):
            title_el = ent.select_one("div.title a")
            if title_el is None:
                continue
            title = _clean_text(title_el.get_text(" "))
            href = title_el.get("href") or ""
            link = urljoin("https://www.ptt.cc", href)
            date = _clean_text(ent.select_one("div.date").get_text(" ")) if ent.select_one("div.date") else ""
            nrec = _clean_text(ent.select_one("div.nrec").get_text(" ")) if ent.select_one("div.nrec") else ""
            if not title:
                continue
            rows.append({
                "source": "PTT Stock",
                "title": title,
                "published": date,
                "url": link,
                "engagement": nrec or "-",
                "sentiment": infer_sentiment(title),
                "summary": short_summary(title, "PTT Stock"),
            })
    rows = dedupe_rows(rows, limit=limit)
    return pd.DataFrame(rows, columns=DISCUSSION_COLUMNS)


def fetch_dcard_money(symbol: str, name: str, limit: int = 10) -> pd.DataFrame:
    """Best-effort Dcard search. Dcard may block automated requests; return empty if unavailable."""
    rows: list[dict] = []
    query = quote_plus(f"{name} {symbol}")
    # Dcard forum names may change; money is the usual finance/investment forum.
    url = f"https://www.dcard.tw/service/api/v2/search/posts?query={query}&forum=money&limit={limit}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=12)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return empty_discussion_df()

    for item in data if isinstance(data, list) else []:
        title = _clean_text(item.get("title", ""))
        post_id = item.get("id")
        if not title or not post_id:
            continue
        created = _clean_text(item.get("createdAt", ""))
        like_count = item.get("likeCount", 0)
        comment_count = item.get("commentCount", 0)
        rows.append({
            "source": "Dcard 理財",
            "title": title,
            "published": created[:10],
            "url": f"https://www.dcard.tw/f/money/p/{post_id}",
            "engagement": f"愛心{like_count}／留言{comment_count}",
            "sentiment": infer_sentiment(title),
            "summary": short_summary(title, "Dcard 理財"),
        })
    rows = dedupe_rows(rows, limit=limit)
    return pd.DataFrame(rows, columns=DISCUSSION_COLUMNS)


def fetch_indexed_forum_results(symbol: str, name: str, limit: int = 10) -> pd.DataFrame:
    """Use Google News RSS as a fallback to surface forum-like indexed pages.

    This does not guarantee coverage, but gives the MVP extra recall without copying
    third-party content. It mainly returns titles and source links.
    """
    query = quote_plus(f'("{name}" OR {symbol}) (site:mobile01.com OR site:cmoney.tw OR site:money.udn.com OR site:ptt.cc) 股票 討論')
    url = f"https://news.google.com/rss/search?q={query}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=12)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception:
        return empty_discussion_df()
    rows = []
    for item in root.findall(".//item"):
        title = _clean_text(item.findtext("title"))
        link = _clean_text(item.findtext("link"))
        pub = _clean_text(item.findtext("pubDate"))
        source_el = item.find("source")
        source = _clean_text(source_el.text if source_el is not None else "討論區索引")
        if not title:
            continue
        rows.append({
            "source": source or "討論區索引",
            "title": title,
            "published": pub,
            "url": link,
            "engagement": "-",
            "sentiment": infer_sentiment(title),
            "summary": short_summary(title, source),
        })
    rows = dedupe_rows(rows, limit=limit)
    return pd.DataFrame(rows, columns=DISCUSSION_COLUMNS)


def fetch_discussions(symbol: str, name: str, limit: int = 10) -> pd.DataFrame:
    frames = [
        fetch_ptt_stock(symbol, name, limit=limit),
        fetch_dcard_money(symbol, name, limit=limit),
        fetch_indexed_forum_results(symbol, name, limit=limit),
    ]
    combined = pd.concat([f for f in frames if isinstance(f, pd.DataFrame) and not f.empty], ignore_index=True) if any(not f.empty for f in frames) else empty_discussion_df()
    if combined.empty:
        return combined
    combined = combined.drop_duplicates(subset=["url"], keep="first")
    return combined.head(limit).reset_index(drop=True)


def sentiment_summary(df: pd.DataFrame) -> dict:
    if df is None or df.empty or "sentiment" not in df.columns:
        return {"偏多": 0, "中性": 0, "偏空": 0, "total": 0, "overall": "資料不足"}
    counts = df["sentiment"].value_counts().to_dict()
    pos = int(counts.get("偏多", 0))
    neu = int(counts.get("中性", 0))
    neg = int(counts.get("偏空", 0))
    total = pos + neu + neg
    if total == 0:
        overall = "資料不足"
    elif pos > neg and pos >= neu:
        overall = "偏多"
    elif neg > pos and neg >= neu:
        overall = "偏空"
    else:
        overall = "中性"
    return {"偏多": pos, "中性": neu, "偏空": neg, "total": total, "overall": overall}


def search_links(symbol: str, name: str) -> dict[str, str]:
    q = quote_plus(f"{name} {symbol}")
    return {
        "Google 新聞": f"https://news.google.com/search?q={q}&hl=zh-TW&gl=TW&ceid=TW%3Azh-Hant",
        "PTT Stock": f"https://www.ptt.cc/bbs/Stock/search?q={q}",
        "Dcard 理財": f"https://www.dcard.tw/search?query={q}",
        "Mobile01 搜尋": f"https://www.google.com/search?q={quote_plus(f'site:mobile01.com {name} {symbol} 股票')}",
        "CMoney 搜尋": f"https://www.google.com/search?q={quote_plus(f'site:cmoney.tw {name} {symbol}')}",
        "Yahoo 股市": f"https://tw.stock.yahoo.com/quote/{symbol}.TW",
    }
