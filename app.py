import os
import json
from datetime import datetime, timedelta
from flask import Flask, request, abort

from apscheduler.schedulers.background import BackgroundScheduler
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

# 初始化 Flask 與 APScheduler
app = Flask(__name__)
scheduler = BackgroundScheduler()
scheduler.start()

# LINE 驗證
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

@app.route("/")
def home():
    return "✅ LINE Reminder Bot 正常運行中"

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

# 倒數提醒發送函數
def send_countdown_reminder(user_id, minutes):
    try:
        line_bot_api.push_message(user_id, TextSendMessage(text=f"⏰ {minutes}分鐘已到"))
    except Exception as e:
        print(f"❌ 倒數提醒發送失敗：{e}")

# 精準文字匹配指令
EXACT_MATCHES = {
    "倒數計時": "countdown_3",
    "開始倒數": "countdown_3",
    "倒數3分鐘": "countdown_3",
    "倒數5分鐘": "countdown_5",
    "倒數1分鐘": "countdown_1",
}

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_text = event.message.text.strip()
    lower_text = user_text.lower()
    user_id = getattr(event.source, "group_id", None) or event.source.user_id
    reply_type = EXACT_MATCHES.get(lower_text)

    if reply_type == "countdown_1":
        line_bot_api.reply_message(event.reply_token, TextSendMessage(
            text="⏰ 1分鐘倒數計時開始！\n📢 1分鐘後我會提醒您時間到了"
        ))
        scheduler.add_job(
            send_countdown_reminder,
            trigger="date",
            run_date=datetime.now() + timedelta(minutes=1),
            args=[user_id, 1],
            id=f"countdown_1_{user_id}_{datetime.now().timestamp()}"
        )
    elif reply_type == "countdown_3":
        line_bot_api.reply_message(event.reply_token, TextSendMessage(
            text="⏰ 3分鐘倒數計時開始！\n📢 3分鐘後我會提醒您時間到了"
        ))
        scheduler.add_job(
            send_countdown_reminder,
            trigger="date",
            run_date=datetime.now() + timedelta(minutes=3),
            args=[user_id, 3],
            id=f"countdown_3_{user_id}_{datetime.now().timestamp()}"
        )
    elif reply_type == "countdown_5":
        line_bot_api.reply_message(event.reply_token, TextSendMessage(
            text="⏰ 5分鐘倒數計時開始！\n📢 5分鐘後我會提醒您時間到了"
        ))
        scheduler.add_job(
            send_countdown_reminder,
            trigger="date",
            run_date=datetime.now() + timedelta(minutes=5),
            args=[user_id, 5],
            id=f"countdown_5_{user_id}_{datetime.now().timestamp()}"
        )
    else:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="指令尚未支援，請輸入『倒數1分鐘』、『倒數3分鐘』或『倒數5分鐘』"))

if __name__ == "__main__":
    print("🚀 LINE Reminder Bot 正在啟動...")
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
