import os
import json
import datetime
import time
import threading
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

import gspread
from oauth2client.service_account import ServiceAccountCredentials

app = Flask(__name__)

# LINE 機器人基本資訊
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 讀取並寫入 Google 憑證檔案
CREDENTIAL_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")
with open("credentials.json", "w") as f:
    f.write(CREDENTIAL_JSON)

# Google Sheets 初始化
SCOPE = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
credentials = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", SCOPE)
gc = gspread.authorize(credentials)
SHEET_NAME = 'LINE提醒排程'
sheet = gc.open(SHEET_NAME).sheet1

# 文字訊息處理
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip()
    source_type = event.source.type
    target_id = event.source.user_id if source_type == "user" else event.source.group_id

    # 查詢關鍵字
    now = datetime.datetime.now()
    if "今天" in text:
        reply = query_schedule(now.date())
    elif "明天" in text:
        reply = query_schedule(now.date() + datetime.timedelta(days=1))
    elif "這週" in text:
        monday = now - datetime.timedelta(days=now.weekday())
        sunday = monday + datetime.timedelta(days=6)
        reply = query_schedule_range(monday.date(), sunday.date())
    elif "下週" in text:
        next_monday = now + datetime.timedelta(days=7 - now.weekday())
        next_sunday = next_monday + datetime.timedelta(days=6)
        reply = query_schedule_range(next_monday.date(), next_sunday.date())
    elif text in ["嗨", "你好", "哈囉"]:
        reply = "要請我喝杯咖啡嗎？"
    elif "倒數開始" in text or "開始倒數" in text:
        reply = "3分鐘倒數開始！等我通知你喔～"
        threading.Thread(target=countdown_timer, args=(target_id,), daemon=True).start()
    else:
        reply = "請輸入「今天」、「明天」、「這週」、「下週」來查詢提醒喔～"

    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

# 倒數計時
def countdown_timer(target_id):
    time.sleep(180)
    line_bot_api.push_message(target_id, TextSendMessage(text="3分鐘已到！"))

# 查詢單一天提醒
def query_schedule(target_date):
    records = sheet.get_all_values()[1:]
    results = []
    for row in records:
        try:
            row_date = datetime.datetime.strptime(row[0], "%Y/%m/%d").date()
            if row_date == target_date:
                results.append(f"{row[1]} - {row[2]}")
        except:
            continue
    return "沒有提醒喔！" if not results else "\n".join(results)

# 查詢範圍提醒
def query_schedule_range(start_date, end_date):
    records = sheet.get_all_values()[1:]
    results = []
    for row in records:
        try:
            row_date = datetime.datetime.strptime(row[0], "%Y/%m/%d").date()
            if start_date <= row_date <= end_date:
                results.append(f"{row[0]} {row[1]} - {row[2]}")
        except:
            continue
    return "這段期間沒有提醒。" if not results else "\n".join(results)

# Webhook
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# 啟動服務
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
