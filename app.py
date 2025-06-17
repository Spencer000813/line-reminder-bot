
import os
import json
from datetime import datetime, timedelta
from flask import Flask, request, abort

import gspread
from google.oauth2.service_account import Credentials

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

# LINE 機器人驗證資訊（從環境變數中讀取）
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 授權 Google Sheets
SERVICE_ACCOUNT_INFO = json.loads(os.getenv("GOOGLE_CREDENTIALS_JSON"))
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
credentials = Credentials.from_service_account_info(SERVICE_ACCOUNT_INFO, scopes=SCOPES)
gc = gspread.authorize(credentials)

# 開啟指定 Google Sheet
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

# 關鍵字查詢條件（完全符合）
EXACT_MATCHES = {
    "今天有哪些行程": "today",
    "明天有哪些行程": "tomorrow",
    "本週有哪些行程": "this_week",
    "下週有哪些行程": "next_week",
    "倒數計時": "countdown",
    "開始倒數": "countdown",
    "說哈囉": "coffee",
    "你好": "coffee"
}

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_text = event.message.text.strip()
    reply_type = EXACT_MATCHES.get(user_text)

    if not reply_type:
        return  # 非完全符合關鍵字，不回覆

    if reply_type == "coffee":
        reply = "要請我喝杯咖啡嗎?"
    elif reply_type == "countdown":
        reply = "倒數計時三分鐘開始..."
    else:
        reply = get_schedule(reply_type)

    if reply:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

def get_schedule(period):
    all_rows = sheet.get_all_values()[1:]  # 忽略標題列
    now = datetime.now()
    schedules = []

    for row in all_rows:
        try:
            date_str, time_str, content, user_id, status = row
            dt = datetime.strptime(f"{date_str} {time_str}", "%Y/%m/%d %H:%M")
        except:
            continue  # 跳過格式錯誤的列

        if period == "today" and dt.date() == now.date():
            schedules.append(f"{dt.strftime('%H:%M')} - {content}")
        elif period == "tomorrow" and dt.date() == (now + timedelta(days=1)).date():
            schedules.append(f"{dt.strftime('%H:%M')} - {content}")
        elif period == "this_week" and dt.isocalendar()[1] == now.isocalendar()[1]:
            schedules.append(f"{dt.strftime('%m/%d %H:%M')} - {content}")
        elif period == "next_week" and dt.isocalendar()[1] == (now + timedelta(days=7)).isocalendar()[1]:
            schedules.append(f"{dt.strftime('%m/%d %H:%M')} - {content}")

    if not schedules:
        return "目前沒有相關排程。"
    return "\n".join(schedules)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
