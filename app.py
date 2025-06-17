import os
import json
from datetime import datetime, timedelta
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import gspread
from google.oauth2.service_account import Credentials

# LINE credentials
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

# Google Sheets
SPREADSHEET_ID = os.getenv("GOOGLE_SPREADSHEET_ID")
SHEET_NAME = os.getenv("REMINDER_SHEET_NAME")
GOOGLE_CREDENTIALS = json.loads(os.getenv("GOOGLE_CREDENTIALS_JSON"))

# Setup Flask and LINE API
app = Flask(__name__)
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# Setup Google Sheets access
scopes = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
credentials = Credentials.from_service_account_info(GOOGLE_CREDENTIALS, scopes=scopes)
gc = gspread.authorize(credentials)
sheet = gc.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)

# Helper to get reminders by date range
def get_reminders_by_date(start_date, end_date):
    data = sheet.get_all_values()[1:]  # Skip header
    results = []
    for row in data:
        try:
            row_date = datetime.strptime(row[0], "%Y/%m/%d")
            if start_date <= row_date <= end_date:
                results.append(f"{row[0]} {row[1]}：{row[2]}")
        except:
            continue
    return results if results else ["查無排程"]

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip()
    reply = ""

    now = datetime.now()
    if "今天" in text:
        reply = "\n".join(get_reminders_by_date(now, now))
    elif "明天" in text:
        tomorrow = now + timedelta(days=1)
        reply = "\n".join(get_reminders_by_date(tomorrow, tomorrow))
    elif "這週" in text or "本週" in text:
        start = now - timedelta(days=now.weekday())
        end = start + timedelta(days=6)
        reply = "\n".join(get_reminders_by_date(start, end))
    elif "下週" in text:
        start = now - timedelta(days=now.weekday()) + timedelta(days=7)
        end = start + timedelta(days=6)
        reply = "\n".join(get_reminders_by_date(start, end))
    elif "ID" in text:
        source_type = event.source.type
        if source_type == "user":
            reply = f"你的 User ID 是：{event.source.user_id}"
        elif source_type == "group":
            reply = f"這個群組 ID 是：{event.source.group_id}"
        else:
            reply = "來源無法辨識。"
    elif "倒數" in text:
        reply = "倒數 3 分鐘開始⏳"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        import threading, time
        def delayed_msg():
            time.sleep(180)
            line_bot_api.push_message(event.source.user_id, TextSendMessage(text="⏰ 3 分鐘到了！"))
        threading.Thread(target=delayed_msg).start()
        return
    elif "咖啡" in text or "聊天" in text:
        reply = "要請我喝杯咖啡嗎？☕️"
    else:
        return  # 不含任何關鍵字，不做回覆

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

if __name__ == "__main__":
    app.run()
