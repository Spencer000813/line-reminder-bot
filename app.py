import os
import json
from datetime import datetime, timedelta
from flask import Flask, request, abort

import gspread
from google.oauth2.service_account import Credentials

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

# 初始化 Flask 與 APScheduler
app = Flask(__name__)
scheduler = BackgroundScheduler()
scheduler.start()

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

# 設定要發送早安訊息的群組 ID
TARGET_GROUP_ID = os.getenv("MORNING_GROUP_ID", "C4e138aa0eb252daa89846daab0102e41")  # 可以從環境變數設定

@app.route("/")
def home():
    return "LINE Reminder Bot is running."

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature")
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return "OK"

# 每天早上7點發送早安訊息
def send_morning_message():
    try:
        if TARGET_GROUP_ID != "C4e138aa0eb252daa89846daab0102e41":
            message = "早安，又是新的一天 ☀️"
            line_bot_api.push_message(TARGET_GROUP_ID, TextSendMessage(text=message))
            print(f"早安訊息已發送到群組: {TARGET_GROUP_ID}")
        else:
            print("早安群組 ID 尚未設定")
    except Exception as e:
        print(f"發送早安訊息失敗：{e}")

# 延遲三分鐘後推播倒數訊息
def send_countdown_reminder(user_id):
    try:
        line_bot_api.push_message(user_id, TextSendMessage(text="⏰ 3分鐘已到"))
    except Exception as e:
        print(f"推播失敗：{e}")

# 每週日晚間推播下週行程
def weekly_summary():
    all_rows = sheet.get_all_values()[1:]
    now = datetime.now()
    start = now + timedelta(days=(7 - now.weekday()))
    end = start + timedelta(days=6)
    start = start.replace(hour=0, minute=0)
    end = end.replace(hour=23, minute=59)

    user_schedules = {}

    for row in all_rows:
        if len(row) < 5:
            continue
        try:
            date_str, time_str, content, user_id, _ = row
            dt = datetime.strptime(f"{date_str} {time_str}", "%Y/%m/%d %H:%M")
            if start <= dt <= end:
                user_schedules.setdefault(user_id, []).append((dt, content))
        except Exception:
            continue

    for user_id, items in user_schedules.items():
        items.sort()
        summary = "\n\n".join([f"*{dt.strftime('%Y/%m/%d')}*\n{content}" for dt, content in items])
        try:
            line_bot_api.push_message(user_id, TextSendMessage(text=f"📅 下週行程摘要：\n\n{summary}"))
        except Exception as e:
            print(f"推播下週行程失敗：{e}")

# 排程任務
scheduler.add_job(weekly_summary, CronTrigger(day_of_week="sun", hour=23, minute=30))
scheduler.add_job(send_morning_message, CronTrigger(hour=7, minute=0))  # 每天早上7點

# 指令對應表
EXACT_MATCHES = {
    "今日行程": "today",
    "明日行程": "tomorrow",
    "本週行程": "this_week",
    "下週行程": "next_week",
    "本月行程": "this_month",
    "下個月行程": "next_month",
    "明年行程": "next_year",
    "倒數計時": "countdown",
    "開始倒數": "countdown",
    "哈囉": "hello",
    "hi": "hi",
    "你還會說什麼?": "what_else"
}

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_text = event.message.text.strip()
    lower_text = user_text.lower()
    user_id = getattr(event.source, "group_id", None) or event.source.user_id

    # 新增早安相關指令
    if lower_text == "設定早安群組":
        group_id = getattr(event.source, "group_id", None)
        if group_id:
            global TARGET_GROUP_ID
            TARGET_GROUP_ID = group_id
            reply = f"✅ 已設定此群組為早安訊息群組\n群組 ID: {group_id}\n每天早上7點會自動發送早安訊息"
        else:
            reply = "❌ 此指令只能在群組中使用"
    elif lower_text == "查看早安設定":
        reply = f"目前早安群組 ID: {TARGET_GROUP_ID}\n{'✅ 已設定' if TARGET_GROUP_ID != 'YOUR_GROUP_ID_HERE' else '❌ 尚未設定'}"
    elif lower_text == "測試早安":
        group_id = getattr(event.source, "group_id", None)
        if group_id == TARGET_GROUP_ID or TARGET_GROUP_ID == "C4e138aa0eb252daa89846daab0102e41":
            reply = "早安，又是新的一天 ☀️"
        else:
            reply = "此群組未設定為早安群組"
    elif lower_text == "如何增加行程":
        reply = (
            "📌 新增行程請使用以下格式：\n"
            "月/日 時:分 行程內容\n\n"
            "✅ 範例：\n"
            "7/1 14:00 餵小鳥\n"
            "（也可寫成 2025/7/1 14:00 客戶拜訪）\n\n"
            "🌅 早安訊息指令：\n"
            "• 設定早安群組 - 設定此群組為早安訊息群組\n"
            "• 查看早安設定 - 查看目前設定\n"
            "• 測試早安 - 測試早安訊息"
        )
    else:
        reply_type = next((v for k, v in EXACT_MATCHES.items() if k.lower() == lower_text), None)

        if reply_type == "hello":
            reply = "怎樣?"
        elif reply_type == "hi":
            reply = "呷飽沒?"
        elif reply_type == "what_else":
            reply = "我愛你❤️"
        elif reply_type == "countdown":
            reply = "倒數計時三分鐘開始...\n（3分鐘後我會提醒你：3分鐘已到）"
            scheduler.add_job(
                send_countdown_reminder,
                trigger="date",
                run_date=datetime.now() + timedelta(minutes=3),
                args=[user_id]
            )
        elif reply_type:
            reply = get_schedule(reply_type, user_id)
        else:
            reply = try_add_schedule(user_text, user_id)

    if reply:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

def get_schedule(period, user_id):
    all_rows = sheet.get_all_values()[1:]
    now = datetime.now()
    schedules = []

    for row in all_rows:
        if len(row) < 5:
            continue
        try:
            date_str, time_str, content, uid, _ = row
            dt = datetime.strptime(f"{date_str.strip()} {time_str.strip()}", "%Y/%m/%d %H:%M")
        except:
            continue

        if user_id.lower() != uid.lower():
            continue

        if (
            (period == "today" and dt.date() == now.date()) or
            (period == "tomorrow" and dt.date() == (now + timedelta(days=1)).date()) or
            (period == "this_week" and dt.isocalendar()[1] == now.isocalendar()[1]) or
            (period == "next_week" and dt.isocalendar()[1] == (now + timedelta(days=7)).isocalendar()[1]) or
            (period == "this_month" and dt.year == now.year and dt.month == now.month) or
            (period == "next_month" and (
                dt.year == (now.year + 1 if now.month == 12 else now.year)
            ) and dt.month == ((now.month % 12) + 1)) or
            (period == "next_year" and dt.year == now.year + 1)
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
    except Exception as e:
        print(f"新增行程失敗：{e}")
    return None

if __name__ == "__main__":
    print("LINE Bot 啟動中...")
    print("排程任務:")
    print("- 每天早上 7:00 發送早安訊息")
    print("- 每週日晚上 23:30 發送下週行程摘要")
    
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
