import os
import json
from datetime import datetime, timedelta
from threading import Timer
from flask import Flask, request, abort

import gspread
from google.oauth2.service_account import Credentials

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

# LINE 驗證資訊
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# Google Sheets 授權
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

# 指令關鍵字（轉為小寫比對）
EXACT_MATCHES = {
    "今天有哪些行程": "today",
    "明天有哪些行程": "tomorrow",
    "本週有哪些行程": "this_week",
    "下週有哪些行程": "next_week",
    "倒數計時": "countdown",
    "開始倒數": "countdown",
    "說哈囉": "coffee",
    "你好": "coffee",
    "查詢id": "id"
}

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_text = event.message.text.strip().lower()
    reply_type = EXACT_MATCHES.get(user_text)

    if not reply_type:
        return  # 指令不符，不回覆

    if reply_type == "coffee":
        reply = "要請我喝杯咖啡嗎?"
    elif reply_type == "countdown":
        reply = "倒數計時三分鐘開始..."
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        Timer(180, lambda: send_followup_message(event)).start()
        return
    elif reply_type == "id":
        source = event.source
        if source.type == "user":
            reply = f"你的 User ID 是：\n{source.user_id}"
        elif source.type == "group":
            reply = f"這個群組的 Group ID 是：\n{source.group_id}"
        else:
            reply = "無法取得 ID。"
    else:
        reply = get_schedule(reply_type)

    if reply:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

def send_followup_message(event):
    target_id = event.source.user_id if event.source.type == "user" else event.source.group_id
    line_bot_api.push_message(target_id, TextSendMessage(text="3分鐘已到"))

def get_schedule(period):
    all_rows = sheet.get_all_values()[1:]
    now = datetime.now()
    schedules = []

    for row in all_rows:
        if len(row) < 5:
            continue

        try:
            date_cell, time_str, content, user_id, status = row

            # 日期處理
            if isinstance(date_cell, datetime):
                date_str = date_cell.strftime("%Y/%m/%d")
            else:
                date_str = str(date_cell).strip()
            time_str = str(time_str).strip()

            dt = datetime.strptime(f"{date_str} {time_str}", "%Y/%m/%d %H:%M")

        except Exception:
            continue

        # 比對時間條件
        match = (
            (period == "today" and dt.date() == now.date()) or
            (period == "tomorrow" and dt.date() == (now + timedelta(days=1)).date()) or
            (period == "this_week" and dt.isocalendar()[1] == now.isocalendar()[1]) or
            (period == "next_week" and dt.isocalendar()[1] == (now + timedelta(days=7)).isocalendar()[1])
        )

        if match:
            schedules.append(f"**{dt.strftime('%Y/%m/%d')}**\n{content}")

    return "\n\n".join(schedules) if schedules else "目前沒有相關排程。"

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
