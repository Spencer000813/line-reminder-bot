import os
import json
import re
import traceback
import threading
import time
from datetime import datetime, timedelta
from flask import Flask, request, abort

import gspread
from google.oauth2.service_account import Credentials

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR, EVENT_JOB_MISSED

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

# 初始化 Flask 與 APScheduler
app = Flask(__name__)

# 配置 APScheduler 使其更穩定
scheduler = BackgroundScheduler(
    timezone='Asia/Taipei',  # 明確設定時區
    job_defaults={
        'coalesce': False,
        'max_instances': 3,
        'misfire_grace_time': 300  # 5分鐘的容錯時間
    }
)

# 添加排程器事件監聽器
def job_listener(event):
    if event.exception:
        print(f"❌ 排程任務執行失敗：{event.job_id} - {event.exception}")
        print(f"詳細錯誤：{traceback.format_exc()}")
    else:
        print(f"✅ 排程任務執行成功：{event.job_id}")

scheduler.add_listener(job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR | EVENT_JOB_MISSED)
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
ranking_data = {}  # 風雲榜資料暫存

# 倒數計時狀態追蹤
countdown_status = {}  # 追蹤倒數計時狀態

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

# 風雲榜功能函數（保持不變）
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
                "1️⃣ 同學姓名 (用逗號分隔，支援 , 或 ，)\n"
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
                "📝 請確保包含所有9項資料：\n"
                "1. 同學姓名\n2. 實驗三或傳心練習\n3. 練習日期\n"
                "4. 階段\n5. 喜歡吃\n6. 不喜歡吃\n"
                "7. 喜歡做的事\n8. 不喜歡做的事\n9. 小老師\n\n"
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
        return f"❌ 處理資料失敗：{str(e)}\n請檢查資料格式後重試"

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
            f"📊 已記錄 {len(student_names)} 位同學的資料：\n\n"
            f"👥 同學姓名：{', '.join(student_names)}\n"
            f"📚 實驗三或傳心練習：{common_data[0]}\n"
            f"📅 練習日期：{common_data[1]}\n"
            f"🎯 階段：{common_data[3]}\n"
            f"🍎 喜歡吃：{common_data[4]}\n"
            f"🚫 不喜歡吃：{common_data[5]}\n"
            f"❤️ 喜歡做的事：{common_data[6]}\n"
            f"💔 不喜歡做的事：{common_data[7]}\n"
            f"👨‍🏫 小老師：{common_data[8]}\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"✅ 總共新增了 {len(student_names)} 行資料到Google Sheets\n"
            f"📋 每位同學都有獨立的一行記錄"
        )
        
        return success_message
        
    except Exception as e:
        print(f"❌ 寫入工作表2失敗：{e}")
        return f"❌ 寫入工作表2失敗：{str(e)}\n請檢查工作表權限或重試"

# 倒數計時功能 - 加強版
def send_countdown_reminder(user_id, minutes, job_id):
    """發送倒數計時提醒"""
    try:
        current_time = datetime.now().strftime('%Y/%m/%d %H:%M:%S')
        print(f"🔔 開始發送倒數提醒 - 時間：{current_time}, 用戶：{user_id}, 分鐘：{minutes}")
        
        message = (
            f"⏰ 時間到！\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"🔔 {minutes}分鐘倒數計時結束\n"
            f"✨ 該繼續下一個任務了！\n"
            f"📅 提醒時間：{current_time}"
        )
        
        # 推送訊息
        line_bot_api.push_message(user_id, TextSendMessage(text=message))
        print(f"✅ {minutes}分鐘倒數提醒已成功發送給：{user_id}")
        
        # 更新狀態
        if job_id in countdown_status:
            countdown_status[job_id]['status'] = 'completed'
            countdown_status[job_id]['completed_at'] = current_time
        
    except Exception as e:
        error_msg = f"❌ 推播{minutes}分鐘倒數提醒失敗：{e}"
        print(error_msg)
        print(f"詳細錯誤：{traceback.format_exc()}")
        
        # 更新狀態為失敗
        if job_id in countdown_status:
            countdown_status[job_id]['status'] = 'failed'
            countdown_status[job_id]['error'] = str(e)

def threading_countdown_reminder(user_id, minutes, delay_seconds):
    """使用 threading 作為備用方案"""
    def timer_function():
        time.sleep(delay_seconds)
        try:
            current_time = datetime.now().strftime('%Y/%m/%d %H:%M:%S')
            message = (
                f"⏰ 時間到！(Threading版)\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"🔔 {minutes}分鐘倒數計時結束\n"
                f"✨ 該繼續下一個任務了！\n"
                f"📅 提醒時間：{current_time}"
            )
            line_bot_api.push_message(user_id, TextSendMessage(text=message))
            print(f"✅ Threading版 {minutes}分鐘倒數提醒已發送給：{user_id}")
        except Exception as e:
            print(f"❌ Threading版倒數提醒失敗：{e}")
    
    thread = threading.Thread(target=timer_function)
    thread.daemon = True
    thread.start()
    return thread

def handle_countdown_request(user_id, minutes, event):
    """處理倒數計時請求 - 雙重保險版"""
    try:
        current_time = datetime.now()
        job_id = f"countdown_{minutes}_{user_id}_{int(current_time.timestamp())}"
        run_time = current_time + timedelta(minutes=minutes)
        
        print(f"🕐 設定倒數計時：{minutes}分鐘")
        print(f"   當前時間：{current_time.strftime('%Y/%m/%d %H:%M:%S')}")
        print(f"   執行時間：{run_time.strftime('%Y/%m/%d %H:%M:%S')}")
        print(f"   Job ID：{job_id}")
        
        # 記錄倒數計時狀態
        countdown_status[job_id] = {
            'user_id': user_id,
            'minutes': minutes,
            'start_time': current_time.strftime('%Y/%m/%d %H:%M:%S'),
            'end_time': run_time.strftime('%Y/%m/%d %H:%M:%S'),
            'status': 'running'
        }
        
        # 方法1：APScheduler
        try:
            scheduler.add_job(
                send_countdown_reminder,
                trigger="date",
                run_date=run_time,
                args=[user_id, minutes, job_id],
                id=job_id,
                misfire_grace_time=300,  # 5分鐘容錯
                coalesce=True
            )
            
            # 確認任務已添加
            job = scheduler.get_job(job_id)
            if job:
                print(f"✅ APScheduler 任務已成功添加")
                scheduler_success = True
            else:
                print(f"❌ APScheduler 任務添加失敗")
                scheduler_success = False
        except Exception as e:
            print(f"❌ APScheduler 設定失敗：{e}")
            scheduler_success = False
        
        # 方法2：Threading 作為備用
        delay_seconds = minutes * 60
        thread = threading_countdown_reminder(user_id, minutes, delay_seconds)
        print(f"✅ Threading 備用倒數已啟動")
        
        # 準備回應訊息
        status_msg = "🎯 雙重保險模式：\n"
        if scheduler_success:
            status_msg += "   ✅ APScheduler 已設定\n"
        else:
            status_msg += "   ❌ APScheduler 設定失敗\n"
        status_msg += "   ✅ Threading 備用已啟動"
        
        return (
            f"⏰ {minutes}分鐘倒數計時開始！\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"🕐 計時器已啟動\n"
            f"📢 {minutes}分鐘後我會提醒您時間到了\n"
            f"🎯 執行時間：{run_time.strftime('%H:%M:%S')}\n\n"
            f"{status_msg}\n\n"
            f"💡 使用「查看倒數」檢視狀態"
        )
            
    except Exception as e:
        print(f"❌ 設定倒數計時失敗：{e}")
        print(f"詳細錯誤：{traceback.format_exc()}")
        return f"❌ 倒數計時設定失敗：{str(e)}"

def get_active_countdowns(user_id):
    """查看用戶當前的倒數計時"""
    try:
        # 檢查 APScheduler 的任務
        jobs = scheduler.get_jobs()
        scheduler_countdowns = []
        
        for job in jobs:
            if job.id.startswith(f"countdown_") and user_id in job.id:
                parts = job.id.split("_")
                if len(parts) >= 3:
                    minutes = parts[1]
                    if job.next_run_time:
                        remaining_time = job.next_run_time - datetime.now()
                        if remaining_time.total_seconds() > 0:
                            remaining_minutes = int(remaining_time.total_seconds() / 60)
                            remaining_seconds = int(remaining_time.total_seconds() % 60)
                            scheduler_countdowns.append({
                                'job_id': job.id,
                                'minutes': minutes,
                                'remaining': f"{remaining_minutes}:{remaining_seconds:02d}",
                                'end_time': job.next_run_time.strftime('%H:%M:%S')
                            })
        
        # 檢查狀態記錄
        user_status = {k: v for k, v in countdown_status.items() if v['user_id'] == user_id}
        
        message = "⏰ 倒數計時狀態報告\n━━━━━━━━━━━━━━━━\n\n"
        
        if scheduler_countdowns:
            message += "📊 APScheduler 活躍任務：\n"
            for countdown in scheduler_countdowns:
                message += f"🕐 {countdown['minutes']}分鐘倒數 - 剩餘 {countdown['remaining']} (結束: {countdown['end_time']})\n"
            message += "\n"
        
        if user_status:
            message += "📋 狀態記錄：\n"
            for job_id, status in user_status.items():
                status_icon = "🟢" if status['status'] == 'running' else "✅" if status['status'] == 'completed' else "❌"
                message += f"{status_icon} {status['minutes']}分鐘倒數 - {status['status']} (開始: {status['start_time']})\n"
                if status['status'] == 'failed' and 'error' in status:
                    message += f"   錯誤：{status['error']}\n"
            message += "\n"
        
        if not scheduler_countdowns and not user_status:
            message += "📋 目前沒有進行中的倒數計時\n"
        
        # 添加系統狀態
        message += f"🔧 系統狀態：\n"
        message += f"   • APScheduler 運行中：{'✅' if scheduler.running else '❌'}\n"
        message += f"   • 總排程任務數：{len(scheduler.get_jobs())}\n"
        message += f"   • 目前時間：{datetime.now().strftime('%H:%M:%S')}"
        
        return message
            
    except Exception as e:
        print(f"❌ 查看倒數計時失敗：{e}")
        return f"❌ 查看倒數計時狀態失敗：{str(e)}"

def cancel_countdown(user_id):
    """取消用戶的所有倒數計時"""
    try:
        jobs = scheduler.get_jobs()
        cancelled_count = 0
        
        for job in jobs:
            if job.id.startswith(f"countdown_") and user_id in job.id:
                scheduler.remove_job(job.id)
                cancelled_count += 1
                print(f"✅ 已取消倒數計時：{job.id}")
                
                # 更新狀態
                if job.id in countdown_status:
                    countdown_status[job.id]['status'] = 'cancelled'
        
        if cancelled_count > 0:
            return f"✅ 已取消 {cancelled_count} 個 APScheduler 倒數計時\n💡 Threading 備用倒數無法取消，但會自動忽略"
        else:
            return "📋 沒有找到 APScheduler 的倒數計時任務"
            
    except Exception as e:
        print(f"❌ 取消倒數計時失敗：{e}")
        return f"❌ 取消倒數計時失敗：{str(e)}"

def test_countdown(user_id, seconds=10):
    """測試用的短時間倒數計時"""
    try:
        job_id = f"test_countdown_{user_id}_{int(datetime.now().timestamp())}"
        run_time = datetime.now() + timedelta(seconds=seconds)
        
        def test_reminder(user_id, seconds):
            try:
                message = f"🧪 測試倒數完成！{seconds}秒測試計時結束\n時間：{datetime.now().strftime('%H:%M:%S')}"
                line_bot_api.push_message(user_id, TextSendMessage(text=message))
                print(f"✅ 測試倒數提醒已發送給：{user_id}")
            except Exception as e:
                print(f"❌ 測試倒數提醒失敗：{e}")
        
        # APScheduler 版本
        scheduler.add_job(
            test_reminder,
            trigger="date",
            run_date=run_time,
            args=[user_id, seconds],
            id=job_id,
            misfire_grace_time=30
        )
        
        # Threading 備用版本
        def threading_test():
            time.sleep(seconds)
            try:
                message = f"🧪 Threading測試倒數完成！{seconds}秒\n時間：{datetime.now().strftime('%H:%M:%S')}"
                line_bot_api.push_message(user_id, TextSendMessage(text=message))
                print(f"✅ Threading測試倒數提醒已發送給：{user_id}")
            except Exception as e:
                print(f"❌ Threading測試倒數提醒失敗：{e}")
        
        thread = threading.Thread(target=threading_test)
        thread.daemon = True
        thread.start()
        
        return f"🧪 {seconds}秒測試倒數開始！\n🎯 雙重保險：APScheduler + Threading\n⏰ 預計時間：{run_time.strftime('%H:%M:%S')}"
        
    except Exception as e:
        print(f"❌ 測試倒數設定失敗：{e}")
        return f"❌ 測試倒數失敗：{str(e)}"

# 診斷系統狀態
def get_system_diagnosis():
    """取得系統診斷資訊"""
    try:
        now = datetime.now()
        diagnosis = f"🔧 系統診斷報告\n━━━━━━━━━━━━━━━━\n\n"
        
        # 時間資訊
        diagnosis += f"⏰ 時間資訊：\n"
        diagnosis += f"   • 系統時間：{now.strftime('%Y/%m/%d %H:%M:%S')}\n"
        diagnosis += f"   • 時區：{now.astimezone().tzinfo}\n\n"
        
        # APScheduler 狀態
        diagnosis += f"📊 APScheduler 狀態：\n"
        diagnosis += f"   • 運行狀態：{'✅ 運行中' if scheduler.running else '❌ 已停止'}\n"
        diagnosis += f"   • 總任務數：{len(scheduler.get_jobs())}\n"
        
        # 列出所有任務
        jobs = scheduler.get_jobs()
        if jobs:
            diagnosis += f"   • 任務列表：\n"
            for job in jobs:
                next_run = job.next_run_time.strftime('%H:%M:%S') if job.next_run_time else "未設定"
                diagnosis += f"     - {job.id}: {next_run}\n"
        else:
            diagnosis += f"   • 無排程任務\n"
        
        diagnosis += f"\n"
        
        # 倒數計時狀態
        diagnosis += f"📋 倒數計時記錄：\n"
        if countdown_status:
            for job_id, status in countdown_status.items():
                diagnosis += f"   • {job_id}: {status['status']}\n"
        else:
            diagnosis += f"   • 無倒數計時記錄\n"
        
        diagnosis += f"\n💡 如果 APScheduler 無法正常運作，系統會使用 Threading 作為備用方案。"
        
        return diagnosis
        
    except Exception as e:
        return f"❌ 系統診斷失敗：{str(e)}"

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

# 功能說明
def send_help_message():
    return (
        "🤖 LINE 行程助理 - 完整功能指南\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "📊 風雲榜資料輸入\n"
        "═══════════════\n"
        "🎯 觸發指令：風雲榜\n"
        "📝 一次性輸入所有資料，每行一項\n"
        "💡 同學姓名用逗號分隔，系統會自動建立多筆記錄\n"
        "✅ 資料將自動寫入Google工作表2\n\n"
        "📅 行程管理功能\n"
        "═══════════════\n"
        "📌 新增行程格式：月/日 時:分 行程內容\n"
        "🔍 查詢指令：今日行程、明日行程、本週行程等\n\n"
        "⏰ 倒數計時工具 (雙重保險)\n"
        "═══════════════\n"
        "🕐 基本倒數指令：\n"
        "   • 倒數3分鐘 / 倒數計時 / 開始倒數\n"
        "   • 倒數5分鐘\n"
        "   • 倒數X分鐘 (X可為1-60)\n\n"
        "🔧 倒數管理指令：\n"
        "   • 查看倒數 - 檢視進行中的倒數計時\n"
        "   • 取消倒數 - 取消所有倒數計時\n"
        "   • 測試倒數 - 10秒測試倒數\n"
        "   • 系統診斷 - 查看詳細系統狀態\n\n"
        "💬 趣味互動：\n"
        "   • 哈囉 / hi - 打個招呼\n"
        "   • 你還會說什麼? - 驚喜回應\n\n"
        "⚙️ 系統管理\n"
        "═══════════════\n"
        "🔧 群組推播設定：\n"
        "   • 設定早安群組 - 設定推播群組\n"
        "   • 查看群組設定 - 檢視目前設定\n"
        "   • 測試早安 - 測試早安訊息\n"
        "   • 測試週報 - 手動執行週報\n\n"
        "📊 系統資訊：\n"
        "   • 查看id - 顯示群組/使用者 ID\n"
        "   • 查看排程 - 檢視系統排程狀態\n"
        "   • 系統診斷 - 詳細系統診斷報告\n"
        "   • 功能說明 / 說明 / help - 顯示此說明\n\n"
        "🔔 自動推播服務\n"
        "═══════════════\n"
        "🌅 每天早上 8:30 - 溫馨早安訊息\n"
        "📅 每週日晚上 22:00 - 下週行程摘要\n\n"
        "💡 小提醒：\n"
        "   • 倒數計時使用雙重保險機制 (APScheduler + Threading)\n"
        "   • 系統會在行程前一小時自動提醒您！\n"
        "   • 如遇問題請使用「系統診斷」檢查狀態"
    )

# 週報推播功能
def weekly_summary():
    print("🔄 開始執行每週行程摘要...")
    try:
        if TARGET_GROUP_ID == "C4e138aa0eb252daa89846daab0102e41":
            print("⚠️ 週報群組 ID 尚未設定，跳過週報推播")
            return
            
        all_rows = sheet.get_all_values()[1:]
        now = datetime.now()
        
        days_until_next_monday = (7 - now.weekday()) % 7
        if days_until_next_monday == 0:
            days_until_next_monday = 7
            
        start = now + timedelta(days=days_until_next_monday)
        end = start + timedelta(days=6)
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        end = end.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        print(f"📊 查詢時間範圍：{start.strftime('%Y/%m/%d %H:%M')} 到 {end.strftime('%Y/%m/%d %H:%M')}")
        
        user_schedules = {}

        for row in all_rows:
            if len(row) < 5:
                continue
            try:
                date_str, time_str, content, user_id, _ = row
                dt = datetime.strptime(f"{date_str} {time_str}", "%Y/%m/%d %H:%M")
                if start <= dt <= end:
                    user_schedules.setdefault(user_id, []).append((dt, content))
            except Exception as e:
                print(f"❌ 處理行程資料失敗：{e}")
                continue

        print(f"📈 找到 {len(user_schedules)} 位使用者有下週行程")
        
        if not user_schedules:
            message = (
                f"📅 下週行程預覽\n"
                f"🗓️ {start.strftime('%m/%d')} - {end.strftime('%m/%d')}\n"
                f"━━━━━━━━━━━━━━━━\n\n"
                f"🎉 太棒了！下週沒有安排任何行程\n"
                f"✨ 可以好好放鬆，享受自由時光！"
            )
        else:
            message = (
                f"📅 下週行程預覽\n"
                f"🗓️ {start.strftime('%m/%d')} - {end.strftime('%m/%d')}\n"
                f"━━━━━━━━━━━━━━━━\n\n"
            )
            
            all_schedules = []
            for user_id, items in user_schedules.items():
                for dt, content in items:
                    all_schedules.append((dt, content, user_id))
            
            all_schedules.sort()
            
            current_date = None
            for dt, content, user_id in all_schedules:
                if current_date != dt.date():
                    current_date = dt.date()
                    weekday_names = ["一", "二", "三", "四", "五", "六", "日"]
                    weekday = weekday_names[dt.weekday()]
                    message += f"\n📆 {dt.strftime('%m/%d')} (週{weekday})\n"
                    message += "─────────────────────\n"
                
                message += f"🕐 {dt.strftime('%H:%M')} │ {content}\n"
            
            message += "\n💡 記得提前準備，祝您一週順利！"
        
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

# 排程任務
scheduler.add_job(
    weekly_summary, 
    CronTrigger(day_of_week="sun", hour=22, minute=0, timezone='Asia/Taipei'),
    id="weekly_summary"
)
scheduler.add_job(
    send_morning_message, 
    CronTrigger(hour=8, minute=30, timezone='Asia/Taipei'),
    id="morning_message"
)

# 指令對應表
EXACT_MATCHES = {
    "今日行程": "today",
    "明日行程": "tomorrow", 
    "本週行程": "this_week",
    "下週行程": "next_week",
    "本月行程": "this_month",
    "下個月行程": "next_month",
    "明年行程": "next_year",
    "哈囉": "hello",
    "hi": "hi", 
    "你還會說什麼?": "what_else"
}

def is_schedule_format(text):
    """檢查文字是否像是行程格式"""
    parts = text.strip().split()
    if len(parts) < 2:
        return False
    
    try:
        date_part, time_part = parts[0], parts[1]
        
        if "/" in date_part:
            date_segments = date_part.split("/")
            if len(date_segments) == 2 or len(date_segments) == 3:
                if all(segment.isdigit() for segment in date_segments):
                    if ":" in time_part:
                        colon_index = time_part.find(":")
                        if colon_index > 0:
                            time_only = time_part[:colon_index+3]
                            if len(time_only) >= 4:
                                time_segments = time_only.split(":")
                                if len(time_segments) == 2:
                                    if all(segment.isdigit() for segment in time_segments):
                                        return True
    except:
        pass
    
    return False

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_text = event.message.text.strip()
    lower_text = user_text.lower()
    user_id = getattr(event.source, "group_id", None) or event.source.user_id
    reply = None

    # 風雲榜功能處理
    if user_text == "風雲榜" or (user_text.count('\n') >= 8 and len(user_text.strip().split('\n')) >= 9):
        reply = process_ranking_input(user_id, user_text)
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
                    if job.id == "morning_message":
                        job_name = "早安訊息"
                    elif job.id == "weekly_summary":
                        job_name = "週報摘要"
                    elif job.id.startswith("countdown_"):
                        job_name = f"倒數計時 ({job.id.split('_')[1]}分鐘)"
                    elif job.id.startswith("test_countdown_"):
                        job_name = "測試倒數計時"
                    else:
                        job_name = job.id
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
    elif lower_text == "系統診斷":
        reply = get_system_diagnosis()
    # 倒數計時相關指令
    elif lower_text == "查看倒數":
        reply = get_active_countdowns(user_id)
    elif lower_text == "取消倒數":
        reply = cancel_countdown(user_id)
    elif lower_text == "測試倒數":
        reply = test_countdown(user_id, 10)
    elif lower_text in ["倒數計時", "開始倒數", "倒數3分鐘"]:
        reply = handle_countdown_request(user_id, 3, event)
    elif lower_text == "倒數5分鐘":
        reply = handle_countdown_request(user_id, 5, event)
    elif lower_text.startswith("倒數") and "分鐘" in lower_text:
        try:
            match = re.search(r'倒數(\d+)分鐘', lower_text)
            if match:
                minutes = int(match.group(1))
                if 1 <= minutes <= 60:
                    reply = handle_countdown_request(user_id, minutes, event)
                else:
                    reply = "❌ 倒數時間請設定在1-60分鐘之間"
        except:
            pass
    else:
        # 處理其他指令
        reply_type = next((v for k, v in EXACT_MATCHES.items() if k.lower() == lower_text), None)

        if reply_type == "hello":
            reply = "🙋‍♀️ 怎樣？有什麼需要幫忙的嗎？"
        elif reply_type == "hi":
            reply = "👋 呷飽沒？需要安排什麼行程嗎？"
        elif reply_type == "what_else":
            reply = "💕 我愛你 ❤️\n\n還有很多功能等你發現喔！\n輸入「功能說明」查看完整指令列表～"
        elif reply_type:
            reply = get_schedule(reply_type, user_id)
        else:
            # 檢查是否為行程格式
            if is_schedule_format(user_text):
                reply = try_add_schedule(user_text, user_id)

    # 只有在 reply 不為 None 時才回應
    if reply:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

def get_schedule(period, user_id):
    try:
        all_rows = sheet.get_all_values()[1:]
        now = datetime.now()
        schedules = []

        period_info = {
            "today": {"name": "今日行程", "emoji": "📅", "empty_msg": "今天沒有安排任何行程，可以放鬆一下！"},
            "tomorrow": {"name": "明日行程", "emoji": "📋", "empty_msg": "明天目前沒有安排，有個輕鬆的一天！"},
            "this_week": {"name": "本週行程", "emoji": "📊", "empty_msg": "本週沒有特別安排，享受自由的時光！"},
            "next_week": {"name": "下週行程", "emoji": "🗓️", "empty_msg": "下週暫時沒有安排，可以開始規劃了！"},
            "this_month": {"name": "本月行程", "emoji": "📆", "empty_msg": "本月份目前沒有特別安排！"},
            "next_month": {"name": "下個月行程", "emoji": "🗂️", "empty_msg": "下個月還沒有安排，提前規劃很棒！"},
            "next_year": {"name": "明年行程", "emoji": "🎯", "empty_msg": "明年的規劃還是空白，充滿無限可能！"}
        }

        for row in all_rows:
            if len(row) < 5:
                continue
            try:
                date_str, time_str, content, uid, _ = row
                dt = datetime.strptime(f"{date_str.strip()} {time_str.strip()}", "%Y/%m/%d %H:%M")
            except Exception as e:
                print(f"❌ 解析時間失敗：{e}")
                continue

            if user_id.lower() != uid.lower():
                continue

            if (
                (period == "today" and dt.date() == now.date()) or
                (period == "tomorrow" and dt.date() == (now + timedelta(days=1)).date()) or
                (period == "this_week" and dt.isocalendar()[1] == now.isocalendar()[1] and dt.year == now.year) or
                (period == "next_week" and dt.isocalendar()[1] == (now + timedelta(days=7)).isocalendar()[1] and dt.year == (now + timedelta(days=7)).year) or
                (period == "this_month" and dt.year == now.year and dt.month == now.month) or
                (period == "next_month" and (
                    dt.year == (now.year + 1 if now.month == 12 else now.year)
                ) and dt.month == ((now.month % 12) + 1)) or
                (period == "next_year" and dt.year == now.year + 1)
            ):
                schedules.append((dt, content))

        info = period_info.get(period, {"name": "行程", "emoji": "📅", "empty_msg": "目前沒有相關行程"})
        
        if not schedules:
            return (
                f"{info['emoji']} {info['name']}\n"
                f"━━━━━━━━━━━━━━━━\n\n"
                f"🎉 {info['empty_msg']}"
            )

        schedules.sort()
        
        result = (
            f"{info['emoji']} {info['name']}\n"
            f"━━━━━━━━━━━━━━━━\n\n"
        )
        
        current_date = None
        weekday_names = ["一", "二", "三", "四", "五", "六", "日"]
        
        for dt, content in schedules:
            if current_date != dt.date():
                current_date = dt.date()
                if len(schedules) > 1 and period in ["this_week", "next_week", "this_month", "next_month", "next_year"]:
                    weekday = weekday_names[dt.weekday()]
                    result += f"📆 {dt.strftime('%m/%d')} (週{weekday})\n"
                    result += "─────────────────────\n"
            
            result += f"🕐 {dt.strftime('%H:%M')} │ {content}\n"
            
            if len(schedules) > 1 and period in ["this_week", "next_week", "this_month", "next_month", "next_year"]:
                current_index = schedules.index((dt, content))
                if current_index < len(schedules) - 1:
                    next_dt, _ = schedules[current_index + 1]
                    if next_dt.date() != dt.date():
                        result += "\n"

        if len(schedules) > 0:
            result += "\n💡 記得提前準備，祝您順利完成所有安排！"

        return result.rstrip()
        
    except Exception as e:
        print(f"❌ 取得行程失敗：{e}")
        return "❌ 取得行程時發生錯誤，請稍後再試。"

def try_add_schedule(text, user_id):
    try:
        parts = text.strip().split()
        if len(parts) >= 2:
            date_part = parts[0]
            time_and_content = " ".join(parts[1:])
            
            time_part = None
            content = None
            
            if ":" in time_and_content:
                colon_index = time_and_content.find(":")
                if colon_index >= 1:
                    time_start = max(0, colon_index - 2)
                    while time_start < colon_index and not time_and_content[time_start].isdigit():
                        time_start += 1
                    
                    time_end = colon_index + 3
                    if time_end <= len(time_and_content):
                        potential_time = time_and_content[time_start:time_end]
                        if ":" in potential_time:
                            time_segments = potential_time.split(":")
                            if len(time_segments) == 2 and all(seg.isdigit() for seg in time_segments):
                                time_part = potential_time
                                content = time_and_content[time_end:].strip()
                                
                                if not content:
                                    content = time_and_content[time_end:].strip()
            
            if not time_part or not content:
                return (
                    "❌ 時間格式錯誤\n"
                    "━━━━━━━━━━━━━━━━\n"
                    "📝 正確格式：月/日 時:分 行程內容\n\n"
                    "✅ 範例：\n"
                    "   • 7/1 14:00 開會\n"
                    "   • 12/25 09:30 聖誕聚餐"
                )
            
            if date_part.count("/") == 1:
                date_part = f"{datetime.now().year}/{date_part}"
            
            dt = datetime.strptime(f"{date_part} {time_part}", "%Y/%m/%d %H:%M")
            
            if dt < datetime.now():
                return (
                    "❌ 無法新增過去的時間\n"
                    "━━━━━━━━━━━━━━━━\n"
                    "⏰ 請確認日期和時間是否正確\n"
                    "💡 只能安排未來的行程喔！"
                )
            
            sheet.append_row([
                dt.strftime("%Y/%m/%d"),
                dt.strftime("%H:%M"),
                content,
                user_id,
                ""
            ])
            
            weekday_names = ["一", "二", "三", "四", "五", "六", "日"]
            weekday = weekday_names[dt.weekday()]
            
            return (
                f"✅ 行程新增成功！\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"📅 日期：{dt.strftime('%Y/%m/%d')} (週{weekday})\n"
                f"🕐 時間：{dt.strftime('%H:%M')}\n"
                f"📝 內容：{content}\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"⏰ 系統會在一小時前自動提醒您！"
            )
    except ValueError as e:
        print(f"❌ 時間格式錯誤：{e}")
        return (
            "❌ 時間格式解析失敗\n"
            "━━━━━━━━━━━━━━━━\n"
            "📝 請使用正確格式：月/日 時:分 行程內容\n\n"
            "✅ 範例：7/1 14:00 開會"
        )
    except Exception as e:
        print(f"❌ 新增行程失敗：{e}")
        return (
            "❌ 新增行程失敗\n"
            "━━━━━━━━━━━━━━━━\n"
            "🔧 系統發生錯誤，請稍後再試\n"
            "💬 如持續發生問題，請聯絡管理員"
        )
    
    return None

if __name__ == "__main__":
    print("🤖 LINE 行程助理啟動中...")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("📊 風雲榜功能：")
    print("   🎯 輸入 '風雲榜' 開始資料輸入流程")
    print("   📝 系統會引導您依序輸入9項資料")
    print("   ✅ 資料將自動寫入指定的Google工作表2")
    print("📅 自動排程服務：")
    print("   🌅 每天早上 8:30 - 溫馨早安訊息")
    print("   📊 每週日晚上 22:00 - 下週行程摘要")
    print("⏰ 倒數計時功能 (雙重保險)：")
    print("   🕐 基本倒數：輸入 '倒數3分鐘' 或 '倒數計時' 或 '開始倒數'")
    print("   🕐 自訂倒數：輸入 '倒數X分鐘' (X可為1-60)")
    print("   🔧 管理功能：'查看倒數' / '取消倒數' / '測試倒數' / '系統診斷'")
    print("   🛡️ 雙重保險：APScheduler + Threading 備用機制")
    print("💡 輸入 '功能說明' 查看完整功能列表")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    
    # 顯示目前排程狀態
    try:
        jobs = scheduler.get_jobs()
        print(f"✅ 系統狀態：")
        print(f"   • APScheduler 運行中：{'✅' if scheduler.running else '❌'}")
        print(f"   • 已載入 {len(jobs)} 個排程工作")
        print(f"   • 時區設定：Asia/Taipei")
        for job in jobs:
            next_run = job.next_run_time.strftime('%Y/%m/%d %H:%M:%S') if job.next_run_time else "未設定"
            job_name = "🌅 早安訊息" if job.id == "morning_message" else "📊 週報摘要" if job.id == "weekly_summary" else job.id
            print(f"   • {job_name}: 下次執行 {next_run}")
    except Exception as e:
        print(f"❌ 查看排程狀態失敗：{e}")
    
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("🚀 LINE Bot 已成功啟動，準備為您服務！")
    print("🧪 測試建議：")
    print("   1. 先執行「測試倒數」確認倒數計時功能")
    print("   2. 使用「系統診斷」檢視詳細系統狀態")
    print("   3. 使用「查看排程」檢視所有排程任務")
    print("   4. 輸入「功能說明」了解所有可用指令")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("🔧 故障排除提示：")
    print("   • 如果倒數計時沒有提醒，請檢查「系統診斷」")
    print("   • APScheduler 失效時會自動啟用 Threading 備用")
    print("   • 雲端環境可能影響排程器運作，雙重保險確保可靠性")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
