from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os
import datetime
import threading
import json
import time

app = Flask(__name__)

# 環境變數設定（Render 上會自動注入）
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 提醒資料儲存路徑
REMINDERS_FILE = "reminders.json"
reminders = []
reminded_today = set()

# 載入提醒資料
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
    user_id = event.source.user_id

    if text == "我的ID是？":
        reply = f"你的 ID 是：{user_id}"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return

    if text.startswith("查詢提醒"):
        if reminders:
            reply = "目前提醒：\n" + "\n".join([f"{r['time']} - {r['task']}" for r in reminders])
        else:
            reply = "目前沒有任何提醒喔！"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return

    if text.startswith("取消"):
        for r in reminders:
            if r['raw'].startswith(text.replace("取消", "").strip()):
                reminders.remove(r)
                save_reminders()
                reply = f"已取消提醒：{r['raw']}"
                break
        else:
            reply = "找不到要取消的提醒。"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return

    try:
        task_time, task_content = parse_text(text)
        new_reminder = {
            'time': task_time,
            'task': task_content,
            'user_id': user_id,
            'raw': text
        }
        reminders.append(new_reminder)
        save_reminders()
        reply = f"提醒已設定：{task_time.strftime('%m/%d %H:%M')} {task_content}"
    except Exception as e:
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

def reminder_thread():
    while True:
        now = datetime.datetime.now()
        # 早上10點提醒當天所有任務
        if now.hour == 10 and now.minute == 0:
            today = now.date()
            for r in reminders:
                if r['time'].date() == today and (r['user_id'], today) not in reminded_today:
                    try:
                        line_bot_api.push_message(r['user_id'], TextSendMessage(text=f"你今天有提醒：{r['task']}"))
                    except:
                        pass
                    reminded_today.add((r['user_id'], today))

        # 正常時間到點提醒
        for r in reminders[:]:
            if now >= r['time']:
                try:
                    line_bot_api.push_message(r['user_id'], TextSendMessage(text=f"提醒你：{r['task']}"))
                except:
                    pass
                reminders.remove(r)
                save_reminders()
        time.sleep(30)

threading.Thread(target=reminder_thread, daemon=True).start()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
