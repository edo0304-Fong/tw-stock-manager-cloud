from __future__ import annotations

import os
import smtplib
from email.mime.text import MIMEText
from email.header import Header
from typing import Iterable, Dict

from dotenv import load_dotenv

load_dotenv()


def send_email(subject: str, body: str, to_email: str | None = None, smtp_user: str | None = None, app_password: str | None = None) -> None:
    smtp_user = smtp_user or os.getenv("GMAIL_SMTP_USER")
    app_password = app_password or os.getenv("GMAIL_APP_PASSWORD")
    to_email = to_email or os.getenv("ALERT_RECIPIENT") or smtp_user

    if not smtp_user or not app_password or not to_email:
        raise ValueError("缺少 Gmail SMTP 設定。請填入 Gmail、應用程式密碼和收件者。")

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(subject, "utf-8")
    msg["From"] = smtp_user
    msg["To"] = to_email

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(smtp_user, app_password)
        server.sendmail(smtp_user, [to_email], msg.as_string())


def build_alert_email(triggered: Iterable[Dict]) -> tuple[str, str]:
    items = list(triggered)
    subject = f"台股價格/技術提醒：{len(items)} 則條件觸發"
    lines = ["以下提醒條件已觸發：", ""]
    for item in items:
        lines.append(f"- {item.get('message', '')}")
    lines.extend([
        "",
        "提醒：此系統僅提供資訊整理，不構成投資建議。請搭配大盤、資金控管與自身策略判斷。",
    ])
    return subject, "\n".join(lines)
