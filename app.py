
import os
import json
import re
from datetime import datetime, timedelta
from flask import Flask, request, abort

import gspread
from google.oauth2.service_account import Credentials

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

# LINE 驗證
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

# 查詢命令
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
    reply_type = EXACT_MATCHES.get(user_text.lower())

    # 查詢功能
    if reply_type:
        if reply_type == "coffee":
            reply = "要請我喝杯咖啡嗎?"
        elif reply_type == "countdown":
            reply = "倒數計時三分鐘開始..."
            # 延遲三分鐘後再發送結束訊息
            # 設計上這裡應該交給排程服務觸發
        else:
            reply = get_schedule(reply_type)
        if reply:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return

    # 嘗試解析為新增排程
    parsed = parse_schedule_input(user_text)
    if parsed:
        add_schedule_to_sheet(parsed["date"], parsed["remind_time"], parsed["content"], event.source.user_id)
        reply = f"✅ 行程已新增：
**{parsed['date']}**
{parsed['content']}"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
    else:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="⚠️ 無法解析這句話的行程內容，請使用：6/21 下午3點半 看牙醫 這樣的格式。"))

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
        except:
            continue

        match = False
        if period == "today" and dt.date() == now.date():
            match = True
        elif period == "tomorrow" and dt.date() == (now + timedelta(days=1)).date():
            match = True
        elif period == "this_week" and dt.isocalendar()[1] == now.isocalendar()[1]:
            match = True
        elif period == "next_week" and dt.isocalendar()[1] == (now + timedelta(days=7)).isocalendar()[1]:
            match = True

        if match:
            schedules.append(f"**{dt.strftime('%Y/%m/%d')}**
{content}")

    return "\n".join(schedules) if schedules else "目前沒有相關排程。"

def parse_schedule_input(text):
    text = text.strip()
    date_match = re.search(r"(\d{1,2})[\/](\d{1,2})", text)
    time_match = re.search(r"(上午|下午)?\s?(\d{1,2})點(\d{1,2})?分?", text)
    if not date_match or not time_match:
        return None

    month = int(date_match.group(1))
    day = int(date_match.group(2))
    hour = int(time_match.group(2))
    minute = int(time_match.group(3)) if time_match.group(3) else 0
    if "下午" in time_match.group(1) and hour < 12:
        hour += 12

    year = datetime.now().year
    event_time = datetime(year, month, day, hour, minute)
    remind_time = (event_time - timedelta(hours=1)).strftime("%H:%M")
    return {
        "date": event_time.strftime("%Y/%m/%d"),
        "remind_time": remind_time,
        "content": re.sub(r".*點.*?分?\s*", "", text)
    }

def add_schedule_to_sheet(date, time, content, user_id):
    sheet.append_row([date, time, content, user_id, ""])

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
