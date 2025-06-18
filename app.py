import os
import json
import threading
import time
from datetime import datetime, timedelta
from flask import Flask, request, abort

import gspread
from google.oauth2.service_account import Credentials

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

# LINE 機器人驗證資訊
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# Google Sheet 授權
SERVICE_ACCOUNT_INFO = json.loads(os.getenv("GOOGLE_CREDENTIALS_JSON"))
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
credentials = Credentials.from_service_account_info(SERVICE_ACCOUNT_INFO, scopes=SCOPES)
gc = gspread.authorize(credentials)
spreadsheet_id = os.getenv("GOOGLE_SPREADSHEET_ID")
sheet = gc.open_by_key(spreadsheet_id).sheet1

app = Flask(__name__)

@app.route("/")
def home():
    return "LINE Reminder Bot is running."

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

# 關鍵字查詢條件（不分大小寫）
EXACT_MATCHES = {
    "今天有哪些行程": "today",
    "明天有哪些行程": "tomorrow",
    "本週有哪些行程": "this_week",
    "下週有哪些行程": "next_week",
    "倒數計時": "countdown",
    "開始倒數": "countdown",
    "說哈囉": "coffee",
    "你好": "coffee",
    "查詢id": "check_id"
}

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_text = event.message.text.strip().lower()
    reply_type = EXACT_MATCHES.get(user_text)

    if not reply_type:
        return

    if reply_type == "coffee":
        reply = "要請我喝杯咖啡嗎?"
    elif reply_type == "countdown":
        reply = "倒數計時三分鐘開始..."
        start_countdown(event.source)
    elif reply_type == "check_id":
        reply = get_source_id(event.source)
    else:
        reply = get_schedule(reply_type)

    if reply:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

def get_source_id(source):
    if source.type == "user":
        return f"你的用戶 ID 是：{source.user_id}"
    elif source.type == "group":
        return f"這個群組 ID 是：{source.group_id}"
    else:
        return "無法辨識來源。"

def start_countdown(source):
    def countdown():
        time.sleep(180)
        if source.type == "user":
            line_bot_api.push_message(source.user_id, TextSendMessage(text="3分鐘已到"))
        elif source.type == "group":
            line_bot_api.push_message(source.group_id, TextSendMessage(text="3分鐘已到"))
    threading.Thread(target=countdown).start()

def get_schedule(period):
    all_rows = sheet.get_all_values()[1:]
    now = datetime.now()
    schedules = []

    for row in all_rows:
        if len(row) < 5:
            continue
        try:
            date_cell, time_str, content, user_id, status = row
            if isinstance(date_cell, datetime):
                date_str = date_cell.strftime("%Y/%m/%d")
            else:
                date_str = str(date_cell).strip()
            time_str = str(time_str).strip()
            dt = datetime.strptime(f"{date_str} {time_str}", "%Y/%m/%d %H:%M")
        except Exception as e:
            print("❌ 跳過資料列：", row, "| 錯誤：", e)
            continue

        if period == "today" and dt.date() == now.date():
            schedules.append(f"{dt.strftime('%Y/%m/%d')} - {content}")
        elif period == "tomorrow" and dt.date() == (now + timedelta(days=1)).date():
            schedules.append(f"{dt.strftime('%Y/%m/%d')} - {content}")
        elif period == "this_week" and dt.isocalendar()[1] == now.isocalendar()[1]:
            schedules.append(f"{dt.strftime('%Y/%m/%d')} - {content}")
        elif period == "next_week" and dt.isocalendar()[1] == (now + timedelta(days=7)).isocalendar()[1]:
            schedules.append(f"{dt.strftime('%Y/%m/%d')} - {content}")

    return "\\n".join(schedules) if schedules else "目前沒有相關排程。"

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
