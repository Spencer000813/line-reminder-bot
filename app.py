import os
import json
import logging
from flask import Flask, request, abort
from datetime import datetime, timedelta

import gspread
from google.oauth2.service_account import Credentials

from apscheduler.schedulers.background import BackgroundScheduler
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError, LineBotApiError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

# 日誌
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
scheduler = BackgroundScheduler()
scheduler.start()

# 環境變數
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
GOOGLE_CREDENTIALS = json.loads(os.getenv("GOOGLE_CREDENTIALS"))
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
credentials = Credentials.from_service_account_info(GOOGLE_CREDENTIALS, scopes=scope)
gc = gspread.authorize(credentials)
sheet = gc.open_by_key(SPREADSHEET_ID).sheet1

# 指令對應表
EXACT_MATCHES = {
    "今日行程": "today",
    "明日行程": "tomorrow",
    "本週行程": "this_week",
    "下週行程": "next_week",
    "倒數3分鐘": "countdown_3",
    "倒數5分鐘": "countdown_5",
    "倒數1分鐘": "countdown_1",  # ✅ 新增這行
}

@app.route("/")
def home():
    return "✅ LINE Reminder Bot 正常運行中"

@app.route("/webhook", methods=["POST"])
def webhook():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK"

def send_countdown_reminder(user_id, minutes):
    try:
        line_bot_api.push_message(user_id, TextSendMessage(text=f"⏰ {minutes}分鐘已到"))
    except LineBotApiError as e:
        logger.error(f"推播失敗: {e}")

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_text = event.message.text.strip().lower()
    user_id = getattr(event.source, "group_id", None) or event.source.user_id

    reply_type = EXACT_MATCHES.get(user_text)

    if reply_type == "countdown_1":
        reply = (
            "⏰ 1分鐘倒數計時開始！\n"
            "━━━━━━━━━━━━━━━━\n"
            "🕐 計時器已啟動\n"
            "📢 1分鐘後我會提醒您時間到了"
        )
        scheduler.add_job(
            send_countdown_reminder,
            trigger="date",
            run_date=datetime.now() + timedelta(minutes=1),
            args=[user_id, 1],
            id=f"countdown_1_{user_id}_{datetime.now().timestamp()}"
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

    elif reply_type == "countdown_3":
        reply = (
            "⏰ 3分鐘倒數計時開始！\n"
            "━━━━━━━━━━━━━━━━\n"
            "🕒 計時器已啟動\n"
            "📢 3分鐘後我會提醒您時間到了"
        )
        scheduler.add_job(
            send_countdown_reminder,
            trigger="date",
            run_date=datetime.now() + timedelta(minutes=3),
            args=[user_id, 3],
            id=f"countdown_3_{user_id}_{datetime.now().timestamp()}"
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

    elif reply_type == "countdown_5":
        reply = (
            "⏰ 5分鐘倒數計時開始！\n"
            "━━━━━━━━━━━━━━━━\n"
            "🕔 計時器已啟動\n"
            "📢 5分鐘後我會提醒您時間到了"
        )
        scheduler.add_job(
            send_countdown_reminder,
            trigger="date",
            run_date=datetime.now() + timedelta(minutes=5),
            args=[user_id, 5],
            id=f"countdown_5_{user_id}_{datetime.now().timestamp()}"
        )
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

    else:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(
            text="📌 支援指令：今日行程、明日行程、本週行程、倒數1/3/5分鐘"
        ))

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
