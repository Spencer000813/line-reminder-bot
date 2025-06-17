from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os
import datetime
import threading
import time
import json

app = Flask(__name__)

# 環境變數
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# 儲存倒數計時用戶
countdown_users = {}

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text.strip()
    user_id = event.source.user_id
    group_id = getattr(event.source, "group_id", None)
    target_id = group_id if group_id else user_id

    now = datetime.datetime.now()
    today = now.date()
    tomorrow = today + datetime.timedelta(days=1)
    weekday = today.weekday()

    # 查詢個人或群組 ID
    if user_message in ["查ID", "查詢ID", "查詢 id"]:
        reply = f"你的ID是：{target_id}"

    # 行程查詢
    elif "今天" in user_message:
        reply = "請至 Google Sheet 中查詢今天的提醒記錄。"
    elif "明天" in user_message:
        reply = "請至 Google Sheet 中查詢明天的提醒記錄。"
    elif "這週" in user_message:
        reply = "請至 Google Sheet 中查詢這週的提醒記錄。"
    elif "下週" in user_message:
        reply = "請至 Google Sheet 中查詢下週的提醒記錄。"

    # 倒數3分鐘
    elif user_message in ["倒數開始", "開始倒數"]:
        if target_id in countdown_users:
            reply = "已經在倒數中，請稍候。"
        else:
            countdown_users[target_id] = True
            reply = "3分鐘倒數開始。"
            threading.Thread(target=start_countdown, args=(target_id,), daemon=True).start()

    # 聊天回覆
    elif user_message.endswith("?") or "嗎" in user_message:
        reply = "要請我喝杯咖啡嗎？"

    else:
        reply = "請使用：查ID、倒數開始、今天/明天/這週/下週提醒。"

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

def start_countdown(target_id):
    time.sleep(180)
    try:
        line_bot_api.push_message(target_id, TextSendMessage(text="3分鐘已到"))
    except:
        pass
    countdown_users.pop(target_id, None)

# 自動提醒（由 Google Sheet 負責排程與主動推播，此段保留以後可擴充）
def dummy_reminder_check():
    while True:
        time.sleep(60)

threading.Thread(target=dummy_reminder_check, daemon=True).start()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
