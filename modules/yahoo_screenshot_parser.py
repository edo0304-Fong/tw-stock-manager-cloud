from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

import pandas as pd
from PIL import Image, ImageEnhance, ImageFilter, ImageOps


@dataclass
class ParsedHolding:
    symbol: str
    name: str
    market: str = "TW"
    shares: float = 0.0
    avg_cost: float = 0.0
    note: str = "Yahoo 股市匯入"
    confidence: float = 0.5


def preprocess_for_ocr(image: Image.Image) -> Image.Image:
    """Basic preprocessing for phone screenshots.

    Tesseract 對手機深色模式、細字、縮圖比較容易失敗；這裡先放大、灰階、增加對比。
    """
    img = image.convert("RGB")
    # 轉灰階後自動對比
    img = ImageOps.grayscale(img)
    img = ImageOps.autocontrast(img)
    # 放大 2 倍，對小字比較有幫助
    w, h = img.size
    if max(w, h) < 3000:
        img = img.resize((w * 2, h * 2))
    img = ImageEnhance.Contrast(img).enhance(1.6)
    img = ImageEnhance.Sharpness(img).enhance(1.4)
    img = img.filter(ImageFilter.SHARPEN)
    return img


def ocr_image(image: Image.Image) -> str:
    """Run OCR if pytesseract + Tesseract binary are installed.

    注意：pip 安裝 pytesseract 只是一個 Python 介面，Windows 還必須另外安裝 Tesseract 主程式。
    """
    try:
        import pytesseract  # type: ignore
    except Exception as exc:
        raise RuntimeError("尚未安裝 pytesseract。請改用『手動表格匯入』，或先安裝 Tesseract OCR。") from exc

    images_to_try = [image, preprocess_for_ocr(image)]
    langs_to_try = ["chi_tra+eng", "eng", None]
    errors = []
    best_text = ""

    for img in images_to_try:
        for lang in langs_to_try:
            try:
                if lang:
                    text = pytesseract.image_to_string(img, lang=lang, config="--psm 6")
                else:
                    text = pytesseract.image_to_string(img, config="--psm 6")
                # 取包含台股代號最多的版本
                if len(_extract_symbols(text)) > len(_extract_symbols(best_text)):
                    best_text = text
                elif not best_text and text.strip():
                    best_text = text
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))

    if best_text.strip():
        return best_text

    joined_errors = "；".join(errors[-2:]) if errors else "沒有 OCR 輸出"
    raise RuntimeError(
        "OCR 執行失敗。最常見原因是 Windows 只安裝了 Python 套件，沒有安裝 Tesseract 主程式，"
        "或缺少繁體中文字庫。你可以改用『手動表格匯入』先使用。錯誤：" + joined_errors
    )


def _clean_number(value: str) -> Optional[float]:
    if value is None:
        return None
    cleaned = str(value)
    cleaned = cleaned.replace(",", "").replace("，", "")
    cleaned = cleaned.replace("股", "").replace("張", "").replace("元", "")
    cleaned = cleaned.replace("--", "").replace("—", "").strip()
    # 處理 OCR 常見誤判
    cleaned = cleaned.replace("O", "0").replace("o", "0")
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _extract_symbols(text: str) -> List[str]:
    # 台股：4~6 位數，ETF/權證/特別股可能帶英文字，如 00631L、00981A
    # 避免抓日期年份
    result = []
    for s in re.findall(r"(?<!\d)(\d{4,6}[A-Z]?)(?!\d)", text.upper()):
        if s in {"2023", "2024", "2025", "2026", "0000"}:
            continue
        # Yahoo 有時會出現 1,000 這種被拆成 1000，這裡用常見範圍粗略排除極小/極大雜訊
        result.append(s)
    return result


def normalize_manual_table(text: str) -> pd.DataFrame:
    """Parse user pasted simple table.

    支援：
    2330 台積電 1000 980
    2330,台積電,1000,980
    2330\t台積電\t1000\t980
    00631L 元大台灣50正2 5000 210.5
    """
    rows = []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for ln in lines:
        if any(h in ln.lower() for h in ["symbol", "股票代號", "代號"]):
            continue
        parts = re.split(r"[\t,，| ]+", ln.strip())
        if len(parts) < 2:
            continue
        symbol = None
        symbol_idx = None
        for i, p in enumerate(parts):
            p2 = p.strip().upper()
            if re.fullmatch(r"\d{4,6}[A-Z]?", p2):
                symbol, symbol_idx = p2, i
                break
        if not symbol:
            continue
        # 名稱抓代號後第一個非數字片段；若沒有則用代號
        name = symbol
        for p in parts[symbol_idx + 1:]:
            if not re.fullmatch(r"-?\d+(?:\.\d+)?", p.replace(",", "")):
                name = p.strip()
                break
        nums = []
        for p in parts[symbol_idx + 1:]:
            n = _clean_number(p)
            if n is not None:
                nums.append(n)
        shares = nums[0] if len(nums) >= 1 else 0.0
        avg_cost = nums[1] if len(nums) >= 2 else 0.0
        # 若使用者輸入 3 張，會在下一個 parse_ocr_text 處理；這裡保守不乘 1000
        market = "TWO" if symbol.startswith(("3", "4", "6")) and not symbol.startswith("00") else "TW"
        rows.append(ParsedHolding(symbol=symbol, name=name, market=market, shares=shares, avg_cost=avg_cost, confidence=0.9).__dict__)
    return pd.DataFrame(rows, columns=["symbol", "name", "market", "shares", "avg_cost", "note", "confidence"])


def parse_ocr_text(text: str) -> pd.DataFrame:
    """Parse Yahoo Finance portfolio OCR text.

    Yahoo 股市畫面可能因手機解析度和版面不同而變動，因此這裡採寬鬆規則：
    - 找出台股代號：4 位數，或 ETF/槓桿 ETF 可能含英文字如 00631L、00981A
    - 同一行或鄰近行嘗試抓股票名稱
    - 嘗試抓持股股數、平均成本；抓不到則留 0 給使用者確認
    """
    if not text or not text.strip():
        return pd.DataFrame(columns=["symbol", "name", "market", "shares", "avg_cost", "note", "confidence"])

    # 如果使用者貼的是乾淨表格，優先用表格解析
    manual = normalize_manual_table(text)
    if not manual.empty:
        return manual

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    parsed: List[ParsedHolding] = []
    seen = set()

    for idx, line in enumerate(lines):
        candidates = _extract_symbols(line)
        for symbol in candidates:
            if symbol in seen:
                continue
            seen.add(symbol)

            name = ""
            # 名稱：優先看同一行代號附近的中文字/ETF 名稱
            cleaned_line = line.replace(symbol, " ")
            chunks = re.findall(r"[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9\-]{1,18}", cleaned_line)
            bad_words = {"持股", "庫存", "股數", "成本", "均價", "現價", "市值", "損益", "報酬", "今日", "漲跌", "自選", "投資組合"}
            for chunk in chunks:
                if chunk not in bad_words and not re.fullmatch(r"TW|TWO|ETF", chunk, re.IGNORECASE):
                    name = chunk
                    break
            if not name:
                window_lines = lines[max(0, idx - 2): min(len(lines), idx + 3)]
                joined = " ".join(window_lines).replace(symbol, " ")
                chunks = re.findall(r"[\u4e00-\u9fff]{2,12}", joined)
                for c in chunks:
                    if c not in bad_words:
                        name = c
                        break

            window = " ".join(lines[max(0, idx - 1): min(len(lines), idx + 5)])
            shares = 0.0
            avg_cost = 0.0

            share_patterns = [
                r"(?:股數|持股|庫存|數量)\s*[:：]?\s*([\d,，]+(?:\.\d+)?)\s*(股|張)?",
                r"([\d,，]+(?:\.\d+)?)\s*張",
                r"([\d,，]+)\s*股",
            ]
            for pat in share_patterns:
                m = re.search(pat, window)
                if m:
                    num = _clean_number(m.group(1))
                    if num is not None:
                        unit = m.group(2) if len(m.groups()) >= 2 else ("張" if "張" in m.group(0) else "股")
                        shares = num * 1000 if unit == "張" else num
                        break

            cost_patterns = [
                r"(?:成本均價|平均成本|買進均價|成本|均價)\s*[:：]?\s*([\d,，]+(?:\.\d+)?)",
                r"(?:Avg|Cost)\s*[:：]?\s*([\d,，]+(?:\.\d+)?)",
            ]
            for pat in cost_patterns:
                m = re.search(pat, window, flags=re.IGNORECASE)
                if m:
                    num = _clean_number(m.group(1))
                    if num is not None:
                        avg_cost = num
                        break

            confidence = 0.55
            if name:
                confidence += 0.15
            if shares > 0:
                confidence += 0.15
            if avg_cost > 0:
                confidence += 0.1
            market = "TWO" if symbol.startswith(("3", "4", "6")) and not symbol.startswith("00") else "TW"

            parsed.append(ParsedHolding(
                symbol=symbol,
                name=name or symbol,
                market=market,
                shares=shares,
                avg_cost=avg_cost,
                confidence=min(confidence, 0.95),
            ))

    rows = [p.__dict__ for p in parsed]
    if not rows:
        return pd.DataFrame(columns=["symbol", "name", "market", "shares", "avg_cost", "note", "confidence"])
    return pd.DataFrame(rows)
