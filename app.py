from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import os
import datetime
import threading

app = Flask(__name__)

# 環境變數設定（Render 上會自動注入）
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 儲存提醒資料的地方（記憶體中，重啟會消失）
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
# --- 新增功能：查詢今天 / 本週 / 下週提醒 ---
def filter_reminders(mode):
    now = datetime.datetime.now()
    if mode == "today":
        return [r for r in reminders if r["time"].date() == now.date()]
    elif mode == "this_week":
        start = now - datetime.timedelta(days=now.weekday())
        end = start + datetime.timedelta(days=6)
        return [r for r in reminders if start.date() <= r["time"].date() <= end.date()]
    elif mode == "next_week":
        start = now + datetime.timedelta(days=(7 - now.weekday()))
        end = start + datetime.timedelta(days=6)
        return [r for r in reminders if start.date() <= r["time"].date() <= end.date()]
    return []

@handler.add(MessageEvent, message=TextMessage)
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip()
    user_id = event.source.user_id

    # 判斷是否為進階查詢指令
    if "今天有什麼行程" in text:
        today = filter_reminders("today")
        if today:
            reply = "📅 今天行程：\n" + "\n".join([f"- {r['time'].strftime('%H:%M')} {r['task']}" for r in today])
        else:
            reply = "今天沒有安排任何提醒喔！"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return

    if "這週提醒" in text or "這週行程" in text:
        this_week = filter_reminders("this_week")
        if this_week:
            reply = "📅 本週提醒：\n" + "\n".join([f"- {r['time'].strftime('%m/%d %H:%M')} {r['task']}" for r in this_week])
        else:
            reply = "本週還沒有任何提醒喔！"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return

    if "下週" in text:
        next_week = filter_reminders("next_week")
        if next_week:
            reply = "📅 下週提醒：\n" + "\n".join([f"- {r['time'].strftime('%m/%d %H:%M')} {r['task']}" for r in next_week])
        else:
            reply = "下週目前也沒有提醒，可以安排一下喔！"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return

    # 原本的提醒設定語法
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


def reminder_thread():
    while True:
        now = datetime.datetime.now()
        for r in reminders[:]:
            if now >= r['time']:
                try:
                    line_bot_api.push_message(r['user_id'], TextSendMessage(text=f"提醒你：{r['task']}"))
                except:
                    pass
                reminders.remove(r)
        time.sleep(30)

import time
threading.Thread(target=reminder_thread, daemon=True).start()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
