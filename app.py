import os
import json
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

# 關鍵字指令（不分大小寫比對）
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
    lower_text = user_text.lower()

    # 只在用戶輸入「如何新增排程」時顯示說明
    if lower_text == "如何新增排程":
        reply = (
            "📌 新增排程請使用以下格式：\n"
            "月/日 時:分 行程內容\n\n"
            "✅ 範例：\n"
            "7/1 14:00 餵小鳥\n"
            "（也可寫成 2025/7/1 14:00 客戶拜訪）"
        )
    else:
        reply_type = next((v for k, v in EXACT_MATCHES.items() if k.lower() == lower_text), None)

        if reply_type == "coffee":
            reply = "要請我喝杯咖啡嗎?"
        elif reply_type == "countdown":
            reply = "倒數計時三分鐘開始...\n（3分鐘後我會提醒你：3分鐘已到）"
        elif reply_type:
            reply = get_schedule(reply_type, event.source.user_id)
        else:
            reply = try_add_schedule(user_text, event.source.user_id)

    if reply:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

def get_schedule(period, requester_id):
    all_rows = sheet.get_all_values()[1:]
    now = datetime.now()
    schedules = []

    for row in all_rows:
        if len(row) < 5:
            continue
        try:
            date_cell, time_str, content, user_id, status = row
            date_str = date_cell if isinstance(date_cell, str) else date_cell.strftime("%Y/%m/%d")
            dt = datetime.strptime(f"{date_str.strip()} {time_str.strip()}", "%Y/%m/%d %H:%M")
        except:
            continue

        is_target = requester_id.lower() == user_id.lower()

        if (
            is_target and (
                (period == "today" and dt.date() == now.date()) or
                (period == "tomorrow" and dt.date() == (now + timedelta(days=1)).date()) or
                (period == "this_week" and dt.isocalendar()[1] == now.isocalendar()[1]) or
                (period == "next_week" and dt.isocalendar()[1] == (now + timedelta(days=7)).isocalendar()[1])
            )
        ):
            schedules.append(f"*{dt.strftime('%Y/%m/%d')}*\n{content}")

    return "\n\n".join(schedules) if schedules else "目前沒有相關排程。"

def try_add_schedule(text, user_id):
    try:
        parts = text.strip().split()
        if len(parts) >= 3:
            date_part, time_part = parts[0], parts[1]
            content = " ".join(parts[2:])

            if date_part.count("/") == 1:
                date_part = f"{datetime.now().year}/{date_part}"

            dt = datetime.strptime(f"{date_part} {time_part}", "%Y/%m/%d %H:%M")

            sheet.append_row([
                dt.strftime("%Y/%m/%d"),
                dt.strftime("%H:%M"),
                content,
                user_id,
                ""
            ])

            return (
                f"✅ 行程已新增：\n"
                f"- 日期：{dt.strftime('%Y/%m/%d')}\n"
                f"- 時間：{dt.strftime('%H:%M')}\n"
                f"- 內容：{content}\n"
                f"（一小時前會提醒你）"
            )
    except Exception:
        return None  # 不回覆任何內容，交由 handle_message 最後處理

    return None

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
