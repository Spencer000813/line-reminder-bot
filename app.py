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

LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

REMINDERS_FILE = "reminders.json"
reminders = []
reminded_today = set()

# 載入提醒
if os.path.exists(REMINDERS_FILE):
    try:
        with open(REMINDERS_FILE, "r", encoding="utf-8") as f:
            reminders = json.load(f)
            for r in reminders:
                r["time"] = datetime.datetime.strptime(r["time"], "%Y-%m-%d %H:%M:%S")
    except:
        reminders = []

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip()
    source_type = event.source.type
    user_id = event.source.user_id
    target_id = user_id if source_type == "user" else event.source.group_id

    # 查詢 ID
    if "ID" in text:
        if source_type == "user":
            reply = f"你的使用者 ID 是：{user_id}"
        elif source_type == "group":
            reply = f"這個群組的 ID 是：{event.source.group_id}"
        else:
            reply = "無法辨識來源類型。"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return

    # 倒數計時 3 分鐘
    if "倒數開始" in text or "開始倒數" in text:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="倒數 3 分鐘開始..."))
        threading.Timer(180, lambda: line_bot_api.push_message(target_id, TextSendMessage(text="⏰ 3分鐘已到！"))).start()
        return

    # 聊天對話
    if text in ["嗨", "你好", "在嗎", "機器人"]:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="要請我喝杯咖啡嗎？"))
        return

    # 查詢提醒
    now = datetime.datetime.now()
    today = now.date()
    weekday = today.weekday()
    start_of_week = today - datetime.timedelta(days=weekday)
    end_of_week = start_of_week + datetime.timedelta(days=6)

    if "今天" in text:
        filtered = [r for r in reminders if r['time'].date() == today and r['user_id'] == user_id]
    elif "明天" in text:
        tomorrow = today + datetime.timedelta(days=1)
        filtered = [r for r in reminders if r['time'].date() == tomorrow and r['user_id'] == user_id]
    elif "這週" in text:
        filtered = [r for r in reminders if start_of_week <= r['time'].date() <= end_of_week and r['user_id'] == user_id]
    else:
        filtered = []

    if filtered:
        reply = "\n".join([f"{r['time'].strftime('%m/%d %H:%M')} - {r['task']}" for r in filtered])
    elif text.startswith("查詢"):
        reply = "目前沒有符合的提醒喔！"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return

    # 設定提醒
    if not filtered and not text.startswith("查詢"):
        try:
            task_time, task_content = parse_text(text)
            new_reminder = {
                'time': task_time,
                'task': task_content,
                'user_id': target_id,
                'raw': text
            }
            reminders.append(new_reminder)
            save_reminders()
            reply = f"提醒已設定：{task_time.strftime('%m/%d %H:%M')} {task_content}"
        except:
            reply = "請輸入正確格式，例如：6/17 晚上9點45分 傳心"

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

def parse_text(text):
    import re
    now = datetime.datetime.now()
    m = re.search(r'(\d{1,2})[\/月](\d{1,2})[日號 ]*(上午|下午|晚上)?(\d{1,2})[:點](\d{1,2})?', text)
    if not m:
        raise ValueError("格式錯誤")

    month = int(m.group(1))
    day = int(m.group(2))
    hour = int(m.group(4))
    minute = int(m.group(5)) if m.group(5) else 0

    if m.group(3) in ['下午', '晚上'] and hour < 12:
        hour += 12

    task_time = datetime.datetime(now.year, month, day, hour, minute)
    task_content = text[m.end():].strip()
    return task_time, task_content

def save_reminders():
    with open(REMINDERS_FILE, "w", encoding="utf-8") as f:
        data = [
            {
                'time': r['time'].strftime("%Y-%m-%d %H:%M:%S"),
                'task': r['task'],
                'user_id': r['user_id'],
                'raw': r['raw']
            } for r in reminders
        ]
        json.dump(data, f, ensure_ascii=False, indent=2)

# 後台排程提醒
def reminder_thread():
    while True:
        now = datetime.datetime.now()
        if now.hour == 10 and now.minute == 0:
            for r in reminders:
                if r['time'].date() == now.date() and (r['user_id'], now.date()) not in reminded_today:
                    try:
                        line_bot_api.push_message(r['user_id'], TextSendMessage(text=f"📌 今日提醒：{r['task']}"))
                    except:
                        pass
                    reminded_today.add((r['user_id'], now.date()))

        for r in reminders[:]:
            if now >= r['time']:
                try:
                    line_bot_api.push_message(r['user_id'], TextSendMessage(text=f"🔔 到時間了：{r['task']}"))
                except:
                    pass
                reminders.remove(r)
                save_reminders()
        time.sleep(30)

threading.Thread(target=reminder_thread, daemon=True).start()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
