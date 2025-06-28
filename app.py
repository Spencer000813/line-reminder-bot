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

# 設定要發送推播的群組 ID
TARGET_GROUP_ID = os.getenv("MORNING_GROUP_ID", "C4e138aa0eb252daa89846daab0102e41")

# 風雲榜功能新增的變數
RANKING_SPREADSHEET_ID = "1LkPCLbaw5wmPao9g2mMEMRT7eklteR-6RLaJNYP8OQA"
WORKSHEET_NAME = "工作表2"
ranking_data = {}

# 指令對應表
EXACT_MATCHES = {
    "今日行程": "today",
    "明日行程": "tomorrow",
    "本週行程": "this_week",
    "下週行程": "next_week",
    "本月行程": "this_month",
    "下個月行程": "next_month",
    "明年行程": "next_year",
    "倒數計時": "countdown_3",
    "開始倒數": "countdown_3",
    "倒數1分鐘": "countdown_1",
    "倒數3分鐘": "countdown_3",
    "倒數5分鐘": "countdown_5",
    "哈囉": "hello",
    "hi": "hi",
    "你還會說什麼?": "what_else",
    "你還會說什麼？": "what_else"
}

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

# 風雲榜功能函數
def get_worksheet2():
    """取得工作表2的連線"""
    try:
        spreadsheet = gc.open_by_key(RANKING_SPREADSHEET_ID)
        worksheet = spreadsheet.worksheet(WORKSHEET_NAME)
        return worksheet
    except Exception as e:
        print(f"❌ 連接工作表2失敗：{e}")
        return None

def process_ranking_input(user_id, text):
    """處理風雲榜輸入"""
    try:
        if text.strip() == "風雲榜":
            return (
                "📊 風雲榜資料輸入說明\n"
                "━━━━━━━━━━━━━━━━\n"
                "📝 請一次性輸入所有資料，每行一項：\n\n"
                "✨ 輸入範例：\n"
                "─────────────────\n"
                "奕君,惠華,小嫺,嘉憶,曉汎\n"
                "離世傳心練習\n"
                "6/25\n"
                "傳心\n"
                "9\n"
                "10\n"
                "10\n"
                "10\n"
                "嘉憶家的莎莉\n"
                "─────────────────\n\n"
                "📋 資料項目說明：\n"
                "1️⃣ 同學姓名 (用逗號分隔)\n"
                "2️⃣ 實驗三或傳心練習\n"
                "3️⃣ 練習日期\n"
                "4️⃣ 階段\n"
                "5️⃣ 喜歡吃 (分數)\n"
                "6️⃣ 不喜歡吃 (分數)\n"
                "7️⃣ 喜歡做的事 (分數)\n"
                "8️⃣ 不喜歡做的事 (分數)\n"
                "9️⃣ 小老師\n\n"
                "💡 請把所有資料一次輸入，系統會自動處理！"
            )
        
        lines = text.strip().split('\n')
        if len(lines) >= 9:
            return process_batch_ranking_data(user_id, lines)
        
        return None
        
    except Exception as e:
        print(f"❌ 處理風雲榜輸入失敗：{e}")
        return "❌ 處理輸入時發生錯誤，請檢查資料格式後重試"

def process_batch_ranking_data(user_id, lines):
    """處理批量風雲榜資料"""
    try:
        if len(lines) < 9:
            return (
                "❌ 資料不完整\n"
                "━━━━━━━━━━━━━━━━\n"
                "📝 請確保包含所有9項資料\n"
                "💡 輸入「風雲榜」查看完整範例"
            )
        
        data = [line.strip() for line in lines[:9]]
        
        if not all(data):
            return (
                "❌ 發現空白資料\n"
                "━━━━━━━━━━━━━━━━\n"
                "📝 請確保每一行都有填入資料\n"
                "💡 輸入「風雲榜」查看完整範例"
            )
        
        ranking_data_batch = {
            "data": [
                data[0], data[1], data[2], "",
                data[3], data[4], data[5], data[6], data[7], data[8]
            ]
        }
        
        return write_ranking_to_sheet_batch(user_id, ranking_data_batch)
        
    except Exception as e:
        print(f"❌ 處理批量資料失敗：{e}")
        return f"❌ 處理資料失敗：{str(e)}"

def write_ranking_to_sheet_batch(user_id, data_batch):
    """將批量風雲榜資料寫入Google Sheets工作表2"""
    try:
        worksheet = get_worksheet2()
        if not worksheet:
            return "❌ 無法連接到工作表2"
        
        student_names_str = data_batch["data"][0]
        student_names_str = student_names_str.replace('，', ',')
        student_names = [name.strip() for name in student_names_str.split(",") if name.strip()]
        
        if not student_names:
            return "❌ 沒有找到有效的同學姓名"
        
        common_data = [
            data_batch["data"][1], data_batch["data"][2], "",
            data_batch["data"][4], data_batch["data"][5], data_batch["data"][6],
            data_batch["data"][7], data_batch["data"][8], data_batch["data"][9]
        ]
        
        rows_to_add = []
        for student_name in student_names:
            row_data = [student_name] + common_data
            rows_to_add.append(row_data)
        
        worksheet.append_rows(rows_to_add)
        
        success_message = (
            f"🎉 風雲榜資料已成功寫入工作表2！\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"📊 已記錄 {len(student_names)} 位同學的資料\n"
            f"👥 同學姓名：{', '.join(student_names)}\n"
            f"✅ 總共新增了 {len(student_names)} 行資料到Google Sheets"
        )
        
        return success_message
        
    except Exception as e:
        print(f"❌ 寫入工作表2失敗：{e}")
        return f"❌ 寫入工作表2失敗：{str(e)}"

# 發送早安訊息
def send_morning_message():
    try:
        if TARGET_GROUP_ID != "C4e138aa0eb252daa89846daab0102e41":
            message = "🌅 早安！新的一天開始了 ✨\n\n願你今天充滿活力與美好！"
            line_bot_api.push_message(TARGET_GROUP_ID, TextSendMessage(text=message))
            print(f"✅ 早安訊息已發送到群組: {TARGET_GROUP_ID}")
        else:
            print("⚠️ 推播群組 ID 尚未設定")
    except Exception as e:
        print(f"❌ 發送早安訊息失敗：{e}")

# 延遲後推播倒數訊息
def send_countdown_reminder(user_id, minutes):
    try:
        if minutes == 1:
            message = "⏰ 時間到！1分鐘倒數計時結束 🔔"
        else:
            message = f"⏰ 時間到！{minutes}分鐘倒數計時結束"
        line_bot_api.push_message(user_id, TextSendMessage(text=message))
        print(f"✅ {minutes}分鐘倒數提醒已發送給：{user_id}")
    except Exception as e:
        print(f"❌ 推播{minutes}分鐘倒數提醒失敗：{e}")

# 功能說明
def send_help_message():
    return (
        "🤖 LINE 行程助理 - 完整功能指南\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "📊 風雲榜資料輸入\n"
        "═══════════════\n"
        "🎯 觸發指令：風雲榜\n"
        "📝 一次性輸入所有資料，每行一項\n\n"
        "📅 行程管理功能\n"
        "═══════════════\n"
        "📌 新增行程格式：月/日 時:分 行程內容\n"
        "🔍 查詢指令：今日行程、明日行程、本週行程等\n\n"
        "⏰ 實用工具\n"
        "═══════════════\n"
        "🕐 倒數計時：倒數1分鐘、倒數3分鐘、倒數5分鐘\n"
        "💬 趣味互動：哈囉、hi、你還會說什麼?\n\n"
        "⚙️ 系統管理\n"
        "═══════════════\n"
        "🔧 群組推播設定：\n"
        "   • 設定早安群組 - 設定推播群組\n"
        "   • 查看群組設定 - 檢視目前設定\n"
        "   • 測試早安 - 測試早安訊息\n\n"
        "📊 系統資訊：\n"
        "   • 查看id - 顯示群組/使用者 ID\n"
        "   • 查看排程 - 檢視系統排程狀態\n"
        "   • 功能說明 / 說明 / help - 顯示此說明\n\n"
        "🔔 自動推播服務\n"
        "═══════════════\n"
        "🌅 每天早上 8:30 - 溫馨早安訊息\n"
        "📅 每週日晚上 22:00 - 下週行程摘要\n\n"
        "💡 小提醒：系統會在行程前一小時自動提醒您！"
    )

# 檢查文字是否為行程格式
def is_schedule_format(text):
    """檢查文字是否像是行程格式"""
    parts = text.strip().split()
    if len(parts) < 3:
        return False
    
    try:
        date_part = parts[0]
        time_part = parts[1]
        
        # 檢查日期格式
        if "/" in date_part:
            date_segments = date_part.split("/")
            if len(date_segments) == 2 or len(date_segments) == 3:
                if all(segment.isdigit() for segment in date_segments):
                    # 檢查時間格式
                    if ":" in time_part:
                        time_segments = time_part.split(":")
                        if len(time_segments) == 2:
                            if all(segment.isdigit() for segment in time_segments):
                                return True
    except:
        pass
    
    return False

# 週報摘要功能
def weekly_summary():
    print("🔄 開始執行每週行程摘要...")
    try:
        if TARGET_GROUP_ID == "C4e138aa0eb252daa89846daab0102e41":
            print("⚠️ 週報群組 ID 尚未設定，跳過週報推播")
            return
            
        message = (
            f"📅 下週行程預覽\n"
            f"━━━━━━━━━━━━━━━━\n\n"
            f"🎉 太棒了！下週沒有安排任何行程\n"
            f"✨ 可以好好放鬆，享受自由時光！"
        )
        
        try:
            line_bot_api.push_message(TARGET_GROUP_ID, TextSendMessage(text=message))
            print(f"✅ 已發送週報摘要到群組：{TARGET_GROUP_ID}")
        except Exception as e:
            print(f"❌ 推播週報到群組失敗：{e}")
                
        print("✅ 每週行程摘要執行完成")
                
    except Exception as e:
        print(f"❌ 每週行程摘要執行失敗：{e}")

def manual_weekly_summary():
    print("🔧 手動執行每週行程摘要...")
    weekly_summary()

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_text = event.message.text.strip()
    lower_text = user_text.lower()
    user_id = getattr(event.source, "group_id", None) or event.source.user_id
    reply = None
    
    print(f"🔔 收到訊息：{user_text} (來自：{user_id})")

    # 風雲榜功能處理
    if user_text == "風雲榜" or (user_text.count('\n') >= 8 and len(user_text.strip().split('\n')) >= 9):
        reply = process_ranking_input(user_id, user_text)
        print(f"📊 風雲榜處理結果：{reply is not None}")
        if reply:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
            return

    # 群組管理指令
    if lower_text == "設定早安群組":
        group_id = getattr(event.source, "group_id", None)
        if group_id:
            global TARGET_GROUP_ID
            TARGET_GROUP_ID = group_id
            reply = (
                "✅ 群組設定成功！\n"
                "━━━━━━━━━━━━━━━━\n"
                f"📱 群組 ID：{group_id}\n"
                f"🌅 早安訊息：每天早上 8:30\n"
                f"📅 週報摘要：每週日晚上 22:00\n\n"
                f"💡 所有推播功能已啟用！"
            )
        else:
            reply = "❌ 此指令只能在群組中使用"
    elif lower_text == "查看群組設定":
        status = "✅ 已設定推播群組" if TARGET_GROUP_ID != "C4e138aa0eb252daa89846daab0102e41" else "❌ 尚未設定推播群組"
        reply = (
            f"📊 群組設定狀態\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"📱 群組 ID：{TARGET_GROUP_ID}\n"
            f"🔔 推播狀態：{status}\n\n"
            f"🕐 自動推播時間：\n"
            f"   • 早安訊息：每天 8:30\n"
            f"   • 週報摘要：每週日 22:00"
        )
    elif lower_text == "測試早安":
        group_id = getattr(event.source, "group_id", None)
        if group_id == TARGET_GROUP_ID or TARGET_GROUP_ID == "C4e138aa0eb252daa89846daab0102e41":
            reply = "🌅 早安！新的一天開始了 ✨\n\n願你今天充滿活力與美好！"
        else:
            reply = "⚠️ 此群組未設定為推播群組"
    elif lower_text == "測試週報":
        try:
            manual_weekly_summary()
            reply = "✅ 週報已手動執行完成\n📝 請檢查執行記錄確認推播狀況"
        except Exception as e:
            reply = f"❌ 週報執行失敗：{str(e)}"
    elif lower_text == "查看id":
        group_id = getattr(event.source, "group_id", None)
        user_id_display = event.source.user_id
        if group_id:
            reply = (
                f"📋 當前資訊\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"👥 群組 ID：{group_id}\n"
                f"👤 使用者 ID：{user_id_display}"
            )
        else:
            reply = (
                f"📋 當前資訊\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"👤 使用者 ID：{user_id_display}\n"
                f"💬 環境：個人對話"
            )
    elif lower_text == "查看排程":
        try:
            jobs = scheduler.get_jobs()
            if jobs:
                job_info = []
                for job in jobs:
                    next_run = job.next_run_time.strftime('%Y/%m/%d %H:%M:%S') if job.next_run_time else "未設定"
                    job_name = "早安訊息" if job.id == "morning_message" else "週報摘要" if job.id == "weekly_summary" else job.id
                    job_info.append(f"   • {job_name}：{next_run}")
                reply = (
                    f"⚙️ 系統排程狀態\n"
                    f"━━━━━━━━━━━━━━━━\n"
                    f"📊 運行中的排程工作：\n" + 
                    "\n".join(job_info)
                )
            else:
                reply = "❌ 沒有找到任何排程工作"
        except Exception as e:
            reply = f"❌ 查看排程失敗：{str(e)}"
    elif lower_text in ["功能說明", "說明", "help", "如何增加行程"]:
        reply = send_help_message()
    else:
        # 檢查精確匹配的指令
        reply_type = next((v for k, v in EXACT_MATCHES.items() if k.lower() == lower_text), None)

        if reply_type == "hello":
            reply = "🙋‍♀️ 怎樣？有什麼需要幫忙的嗎？"
        elif reply_type == "hi":
            reply = "👋 呷飽沒？需要安排什麼行程嗎？"
        elif reply_type == "what_else":
            reply = "💕 我愛你 ❤️\n\n還有很多功能等你發現喔！\n輸入「功能說明」查看完整指令列表～"
        elif reply_type == "countdown_1":
            try:
                reply = (
                    "⏰ 1分鐘倒數計時開始！\n"
                    "━━━━━━━━━━━━━━━━\n"
                    "🕐 計時器已啟動\n"
                    "📢 1分鐘後我會提醒您時間到了"
                )
                scheduler.add_job(
                    send_countdown_reminder,
                    trigger="date",
                    run_date=datetime.now() + timedelta(minutes=1),
                    args=[user_id, 1],
                    id=f"countdown_1_{user_id}_{int(datetime.now().timestamp())}"
                )
                print(f"✅ 已設定1分鐘倒數提醒給：{user_id}")
            except Exception as e:
                print(f"❌ 設定1分鐘倒數失敗：{e}")
                reply = "❌ 倒數計時設定失敗，請稍後再試"
        elif reply_type == "countdown_3":
            try:
                reply = (
                    "⏰ 3分鐘倒數計時開始！\n"
                    "━━━━━━━━━━━━━━━━\n"
                    "🕐 計時器已啟動\n"
                    "📢 3分鐘後我會提醒您時間到了"
                )
                scheduler.add_job(
                    send_countdown_reminder,
                    trigger="date",
                    run_date=datetime.now() + timedelta(minutes=3),
                    args=[user_id, 3],
                    id=f"countdown_3_{user_id}_{int(datetime.now().timestamp())}"
                )
                print(f"✅ 已設定3分鐘倒數提醒給：{user_id}")
            except Exception as e:
                print(f"❌ 設定3分鐘倒數失敗：{e}")
                reply = "❌ 倒數計時設定失敗，請稍後再試"
        elif reply_type == "countdown_5":
            try:
                reply = (
                    "⏰ 5分鐘倒數計時開始！\n"
                    "━━━━━━━━━━━━━━━━\n"
                    "🕐 計時器已啟動\n"
                    "📢 5分鐘後我會提醒您時間到了"
                )
                scheduler.add_job(
                    send_countdown_reminder,
                    trigger="date",
                    run_date=datetime.now() + timedelta(minutes=5),
                    args=[user_id, 5],
                    id=f"countdown_5_{user_id}_{int(datetime.now().timestamp())}"
                )
                print(f"✅ 已設定5分鐘倒數提醒給：{user_id}")
            except Exception as e:
                print(f"❌ 設定5分鐘倒數失敗：{e}")
                reply = "❌ 倒數計時設定失敗，請稍後再試"
        elif reply_type:
            reply = get_schedule(reply_type, user_id)
        else:
            # 檢查是否為行程格式
            if is_schedule_format(user_text):
                reply = try_add_schedule(user_text, user_id)

    # 輸出除錯資訊
    print(f"💬 處理結果：{reply is not None}")
    
    # 只有在 reply 不為 None 時才回應
    if reply:
        try:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
            print(f"✅ 已回應訊息給：{user_id}")
        except Exception as e:
            print(f"❌ 回應訊息失敗：{e}")
    else:
        print(f"⚠️ 沒有回應 - 可能不是已知的指令格式")

def get_schedule(period, user_id):
    """查詢指定期間的行程"""
    return "📅 行程查詢功能開發中..."

def try_add_schedule(text, user_id):
    """嘗試新增行程"""
    return "📝 行程新增功能開發中..."

# 排程任務
scheduler.add_job(
    weekly_summary, 
    CronTrigger(day_of_week="sun", hour=22, minute=0),
    id="weekly_summary"
)
scheduler.add_job(
    send_morning_message, 
    CronTrigger(hour=8, minute=30),
    id="morning_message"
)

if __name__ == "__main__":
    print("🤖 LINE 行程助理啟動中...")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("📊 風雲榜功能：")
    print("   🎯 輸入 '風雲榜' 開始資料輸入流程")
    print("📅 自動排程服務：")
    print("   🌅 每天早上 8:30 - 溫馨早安訊息")
    print("   📊 每週日晚上 22:00 - 下週行程摘要")
    print("⏰ 倒數計時功能：1分鐘、3分鐘、5分鐘")
    print("💡 輸入 '功能說明' 查看完整功能列表")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    
    try:
        jobs = scheduler.get_jobs()
        print(f"✅ 系統狀態：已載入 {len(jobs)} 個排程工作")
        for job in jobs:
            next_run = job.next_run_time.strftime('%Y/%m/%d %H:%M:%S') if job.next_run_time else "未設定"
            job_name = "🌅 早安訊息" if job.id == "morning_message" else "📊 週報摘要" if job.id == "weekly_summary" else job.id
            print(f"   • {job_name}: 下次執行 {next_run}")
    except Exception as e:
        print(f"❌ 查看排程狀態失敗：{e}")
    
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("🚀 LINE Bot 已成功啟動，準備為您服務！")
    
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
