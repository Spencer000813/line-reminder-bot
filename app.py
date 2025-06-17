import os
import datetime
import gspread
from flask import Flask, request, abort
from oauth2client.service_account import ServiceAccountCredentials
from linebot import LineBotApi, WebhookHandler
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import threading
import time

app = Flask(__name__)

# 使用環境變數
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
GOOGLE_SPREADSHEET_ID = os.getenv("GOOGLE_SPREADSHEET_ID")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 建立 Google Sheet API 連線
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
client = gspread.authorize(creds)
sheet = client.open_by_key(GOOGLE_SPREADSHEET_ID).sheet1

def get_schedule_for_range(start_date, end_date):
    rows = sheet.get_all_values()[1:]  # 排除標題列
    result = []

    for row in rows:
        if len(row) < 3:
            continue
        date_str, time_str, content = row[0], row[1], row[2]

        try:
            date_obj = datetime.datetime.strptime(date_str, "%Y/%m/%d").date()
        except:
            continue

        if start_date <= date_obj <= end_date:
            result.append(f"{date_str} {time_str}：{content}")

    return "\n".join(result) if result else "目前沒有行程喔！"

def start_countdown(user_id):
    def countdown():
        for i in range(3, 0, -1):
            line_bot_api.push_message(user_id, TextSendMessage(text=f"倒數 {i} 分鐘"))
            time.sleep(60)
        line_bot_api.push_message(user_id, TextSendMessage(text="倒數結束！"))
    threading.Thread(target=countdown).start()

@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except Exception as e:
        print("Webhook 錯誤:", e)
        abort(400)

    return "OK"

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip()
    reply_token = event.reply_token
    user_id = event.source.user_id
    today = datetime.date.today()
    weekday = today.weekday()

    if text == "今天有哪些行程":
        reply = get_schedule_for_range(today, today)
    elif text == "明天有哪些行程":
        reply = get_schedule_for_range(today + datetime.timedelta(days=1), today + datetime.timedelta(days=1))
    elif text == "本週有哪些行程":
        start = today - datetime.timedelta(days=weekday)
        end = start + datetime.timedelta(days=6)
        reply = get_schedule_for_range(start, end)
    elif text == "下週有哪些行程":
        start = today + datetime.timedelta(days=(7 - weekday))
        end = start + datetime.timedelta(days=6)
        reply = get_schedule_for_range(start, end)
    elif text in ["倒數計時", "開始倒數"]:
        start_countdown(user_id)
        return
    elif text in ["哈囉", "你好"]:
        reply = "要請我喝杯咖啡嗎？"
    else:
        return  # 完全不符合就不回覆

    line_bot_api.reply_message(reply_token, TextSendMessage(text=reply))

if __name__ == "__main__":
    app.run()
