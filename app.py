import os
import json
import logging
from datetime import datetime, timedelta
from flask import Flask, request, abort

import gspread
from google.oauth2.service_account import Credentials

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.executors.pool import ThreadPoolExecutor
import pytz

# 更新為 LINE Bot SDK v3
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    PushMessageRequest,
    TextMessage
)

# 設定日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 初始化 Flask
app = Flask(__name__)

# 設定正確的時區
TAIWAN_TZ = pytz.timezone('Asia/Taipei')

# 設定執行器和任務預設值
executors = {
    'default': ThreadPoolExecutor(20),
}

job_defaults = {
    'coalesce': False,
    'max_instances': 3,
    'misfire_grace_time': 30  # 允許 30 秒的延遲執行
}

# 確保調度器配置正確，明確指定時區
scheduler = BackgroundScheduler(
    executors=executors,
    job_defaults=job_defaults,
    timezone=TAIWAN_TZ
)
scheduler.start()

logger.info("🔧 APScheduler 已啟動")

# LINE 機器人驗證資訊
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

# 檢查環境變數
if not LINE_CHANNEL_ACCESS_TOKEN:
    logger.error("❌ LINE_CHANNEL_ACCESS_TOKEN 未設定")
if not LINE_CHANNEL_SECRET:
    logger.error("❌ LINE_CHANNEL_SECRET 未設定")

# 使用 v3 API 初始化
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# Google Sheets 授權
try:
    SERVICE_ACCOUNT_INFO = json.loads(os.getenv("GOOGLE_CREDENTIALS_JSON"))
    SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
    credentials = Credentials.from_service_account_info(SERVICE_ACCOUNT_INFO, scopes=SCOPES)
    gc = gspread.authorize(credentials)
    spreadsheet_id = os.getenv("GOOGLE_SPREADSHEET_ID")
    sheet = gc.open_by_key(spreadsheet_id).sheet1
    logger.info("✅ Google Sheets 連接成功")
except Exception as e:
    logger.error(f"❌ Google Sheets 連接失敗：{e}")

# 設定要發送推播的群組 ID
TARGET_GROUP_ID = os.getenv("MORNING_GROUP_ID", "C4e138aa0eb252daa89846daab0102e41")

# 風雲榜功能新增的變數
RANKING_SPREADSHEET_ID = "1LkPCLbaw5wmPao9g2mMEMRT7eklteR-6RLaJNYP8OQA"
WORKSHEET_NAME = "工作表2"
ranking_data = {}  # 風雲榜資料暫存

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

# 增強的推播功能與錯誤處理
def send_line_message(user_id, message, message_type="推播"):
    """發送 LINE 訊息並記錄詳細日誌"""
    try:
        if not LINE_CHANNEL_ACCESS_TOKEN:
            logger.error("LINE_CHANNEL_ACCESS_TOKEN 未設定")
            return False
            
        logger.info(f"🚀 準備發送{message_type}給用戶: {user_id}")
        logger.info(f"📝 訊息內容: {message}")
        
        # 發送訊息
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.push_message(
                PushMessageRequest(
                    to=user_id,
                    messages=[TextMessage(text=message)]
                )
            )
        
        logger.info(f"✅ {message_type}發送成功: {user_id}")
        return True
        
    except Exception as e:
        logger.error(f"❌ LINE API 錯誤: {str(e)}")
        logger.error(f"❌ 用戶ID: {user_id}")
        
        # 記錄詳細錯誤
        import traceback
        logger.error(f"詳細錯誤: {traceback.format_exc()}")
        
        return False

# 🆕 新增：檢查並發送待發送的行程提醒
def check_and_send_pending_reminders():
    """檢查並發送Google Sheets中標記為'待發送'的行程提醒"""
    try:
        logger.info("🔍 開始檢查待發送的行程提醒...")
        
        # 獲取所有行程資料
        all_rows = sheet.get_all_values()
        if len(all_rows) <= 1:  # 只有標題行或空表
            logger.info("📭 沒有行程資料需要檢查")
            return
            
        current_time = datetime.now(TAIWAN_TZ)
        processed_count = 0
        sent_count = 0
        
        # 從第2行開始檢查（跳過標題行）
        for i, row in enumerate(all_rows[1:], start=2):
            if len(row) < 5:
                continue
                
            try:
                date_str, time_str, content, user_id, status = row[:5]
                
                # 只處理標記為 "待發送" 的行程
                if status != "待發送":
                    continue
                    
                processed_count += 1
                
                # 解析行程時間
                schedule_dt = datetime.strptime(f"{date_str} {time_str}", "%Y/%m/%d %H:%M")
                schedule_dt = TAIWAN_TZ.localize(schedule_dt) if schedule_dt.tzinfo is None else schedule_dt.astimezone(TAIWAN_TZ)
                
                # 檢查是否到了發送時間（允許2分鐘的容錯範圍）
                time_diff = (current_time - schedule_dt).total_seconds()
                
                if -120 <= time_diff <= 120:  # 前後2分鐘內
                    logger.info(f"📤 準備發送行程提醒: {content} (用戶: {user_id})")
                    
                    # 發送推播訊息
                    message = f"⏰ 行程提醒\n\n📅 {schedule_dt.strftime('%m/%d %H:%M')}\n📝 {content}\n\n時間到了！記得要準時喔 🔔\n📍 {current_time.strftime('%H:%M:%S')}"
                    
                    success = send_line_message(user_id, message, "行程提醒")
                    
                    if success:
                        # 更新狀態為 "已發送"
                        sheet.update_cell(i, 5, "已發送")
                        sent_count += 1
                        logger.info(f"✅ 行程提醒發送成功並更新狀態: {content}")
                    else:
                        logger.error(f"❌ 行程提醒發送失敗: {content}")
                        
            except Exception as e:
                logger.error(f"❌ 處理第{i}行資料時發生錯誤: {e}")
                continue
        
        if processed_count > 0:
            logger.info(f"📊 待發送行程檢查完成: 處理了 {processed_count} 項，成功發送 {sent_count} 項")
        else:
            logger.info("📭 目前沒有待發送的行程提醒")
            
    except Exception as e:
        logger.error(f"❌ 檢查待發送行程提醒失敗：{e}")
        import traceback
        logger.error(f"詳細錯誤：{traceback.format_exc()}")

# 風雲榜功能函數
def get_worksheet2():
    """取得工作表2的連線"""
    try:
        spreadsheet = gc.open_by_key(RANKING_SPREADSHEET_ID)
        worksheet = spreadsheet.worksheet(WORKSHEET_NAME)
        return worksheet
    except Exception as e:
        logger.error(f"❌ 連接工作表2失敗：{e}")
        return None

def process_ranking_input(user_id, text):
    """處理風雲榜輸入"""
    try:
        # 如果是觸發詞，顯示使用說明和範例
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
        
        # 檢查是否為多行資料輸入
        lines = text.strip().split('\n')
        if len(lines) >= 9:  # 至少要有9行資料
            return process_batch_ranking_data(user_id, lines)
        
        # 如果不是風雲榜格式，返回None讓其他功能處理
        return None
        
    except Exception as e:
        logger.error(f"❌ 處理風雲榜輸入失敗：{e}")
        return "❌ 處理輸入時發生錯誤，請檢查資料格式後重試"

def process_batch_ranking_data(user_id, lines):
    """處理批量風雲榜資料"""
    try:
        # 確保至少有9行資料
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
        
        # 提取並清理資料
        data = [line.strip() for line in lines[:9]]  # 只取前9行
        
        # 驗證資料
        if not all(data):
            return (
                "❌ 發現空白資料\n"
                "━━━━━━━━━━━━━━━━\n"
                "📝 請確保每一行都有填入資料\n"
                "💡 輸入「風雲榜」查看完整範例"
            )
        
        # 建立資料結構
        ranking_data_batch = {
            "data": [
                data[0],  # 同學姓名
                data[1],  # 實驗三或傳心練習
                data[2],  # 練習日期
                "",       # 空白欄位
                data[3],  # 階段
                data[4],  # 喜歡吃
                data[5],  # 不喜歡吃
                data[6],  # 喜歡做的事
                data[7],  # 不喜歡做的事
                data[8]   # 小老師
            ]
        }
        
        # 直接寫入工作表
        return write_ranking_to_sheet_batch(user_id, ranking_data_batch)
        
    except Exception as e:
        logger.error(f"❌ 處理批量資料失敗：{e}")
        return f"❌ 處理資料失敗：{str(e)}\n請檢查資料格式後重試"

def write_ranking_to_sheet_batch(user_id, data_batch):
    """將批量風雲榜資料寫入Google Sheets工作表2"""
    try:
        worksheet = get_worksheet2()
        if not worksheet:
            return "❌ 無法連接到工作表2"
        
        # 解析同學姓名（可能有多個，用逗號分隔）
        student_names_str = data_batch["data"][0]
        student_names = [name.strip() for name in student_names_str.split(",") if name.strip()]
        
        if not student_names:
            return "❌ 沒有找到有效的同學姓名"
        
        # 準備其他共用的資料 (B到J欄，除了A欄姓名)
        common_data = [
            data_batch["data"][1],   # B欄：實驗三或傳心練習
            data_batch["data"][2],   # C欄：練習日期
            "",                      # D欄：空白
            data_batch["data"][4],   # E欄：階段
            data_batch["data"][5],   # F欄：喜歡吃
            data_batch["data"][6],   # G欄：不喜歡吃
            data_batch["data"][7],   # H欄：喜歡做的事
            data_batch["data"][8],   # I欄：不喜歡做的事
            data_batch["data"][9]    # J欄：小老師
        ]
        
        # 為每個同學姓名創建一行資料
        rows_to_add = []
        for student_name in student_names:
            row_data = [student_name] + common_data  # A欄放單個姓名，B~J欄放共用資料
            rows_to_add.append(row_data)
        
        # 批量寫入多行資料
        worksheet.append_rows(rows_to_add)
        
        # 格式化成功訊息
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
        logger.error(f"❌ 寫入工作表2失敗：{e}")
        return f"❌ 寫入工作表2失敗：{str(e)}\n請檢查工作表權限或重試"

def write_ranking_to_sheet(user_id, user_session):
    """將風雲榜資料寫入Google Sheets工作表2"""
    try:
        worksheet = get_worksheet2()
        if not worksheet:
            return "❌ 無法連接到工作表2"
        
        # 解析同學姓名（可能有多個，用逗號分隔）
        student_names_str = user_session["data"][0]
        student_names = [name.strip() for name in student_names_str.split(",") if name.strip()]
        
        if not student_names:
            return "❌ 沒有找到有效的同學姓名"
        
        # 準備其他共用的資料 (B到J欄，除了A欄姓名)
        common_data = [
            user_session["data"][1],  # B欄：實驗三或傳心練習
            user_session["data"][2],  # C欄：練習日期
            "",                       # D欄：空白
            user_session["data"][4],  # E欄：階段
            user_session["data"][5],  # F欄：喜歡吃
            user_session["data"][6],  # G欄：不喜歡吃
            user_session["data"][7],  # H欄：喜歡做的事
            user_session["data"][8],  # I欄：不喜歡做的事
            user_session["data"][9]   # J欄：小老師
        ]
        
        # 為每個同學姓名創建一行資料
        rows_to_add = []
        for student_name in student_names:
            row_data = [student_name] + common_data  # A欄放單個姓名，B~J欄放共用資料
            rows_to_add.append(row_data)
        
        # 批量寫入多行資料
        worksheet.append_rows(rows_to_add)
        
        # 清理使用者的輸入狀態
        del ranking_data[user_id]
        
        # 格式化成功訊息
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
        logger.error(f"❌ 寫入工作表2失敗：{e}")
        # 清理使用者的輸入狀態
        if user_id in ranking_data:
            del ranking_data[user_id]
        return f"❌ 寫入工作表2失敗：{str(e)}\n請檢查工作表權限或重試"

# 發送早安訊息
def send_morning_message():
    try:
        if TARGET_GROUP_ID != "C4e138aa0eb252daa89846daab0102e41":
            message = "🌅 早安！新的一天開始了 ✨\n\n願你今天充滿活力與美好！"
            success = send_line_message(TARGET_GROUP_ID, message, "早安訊息")
            if success:
                logger.info(f"✅ 早安訊息已發送到群組: {TARGET_GROUP_ID}")
            else:
                logger.error(f"❌ 早安訊息發送失敗")
        else:
            logger.warning("⚠️ 推播群組 ID 尚未設定")
    except Exception as e:
        logger.error(f"❌ 發送早安訊息失敗：{e}")

# 延遲後推播倒數訊息
def send_countdown_reminder(user_id, minutes):
    """發送倒數計時結束提醒"""
    try:
        current_time = datetime.now(TAIWAN_TZ)
        message = f"⏰ 時間到！{minutes}分鐘倒數計時結束 🔔\n\n時間過得真快呢！\n📅 {current_time.strftime('%H:%M:%S')}"
        
        success = send_line_message(user_id, message, f"{minutes}分鐘倒數提醒")
        if success:
            logger.info(f"✅ {minutes}分鐘倒數提醒已發送給：{user_id}")
        else:
            logger.error(f"❌ {minutes}分鐘倒數提醒發送失敗")
        
    except Exception as e:
        logger.error(f"❌ 推播{minutes}分鐘倒數提醒失敗：{e}")
        # 如果推播失敗，記錄詳細錯誤
        import traceback
        logger.error(f"詳細錯誤：{traceback.format_exc()}")

# 美化的功能說明 (已更新包含風雲榜)
def send_help_message():
    return (
        "🤖 LINE 行程助理 - 完整功能指南\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "📊 風雲榜資料輸入\n"
        "═══════════════\n"
        "🎯 觸發指令：風雲榜\n"
        "📝 一次性輸入所有資料，每行一項：\n"
        "✨ 範例格式：\n"
        "   奕君,惠華,小嫺,嘉憶,曉汎\n"
        "   離世傳心練習\n"
        "   6/25\n"
        "   傳心\n"
        "   9\n"
        "   10\n"
        "   10\n"
        "   10\n"
        "   嘉憶家的莎莉\n"
        "💡 同學姓名用逗號分隔，系統會自動建立多筆記錄\n"
        "✅ 資料將自動寫入Google工作表2\n\n"
        "📅 行程管理功能\n"
        "═══════════════\n"
        "📌 新增行程格式：\n"
        "   月/日 時:分 行程內容\n\n"
        "✨ 新增範例：\n"
        "   • 7/1 14:00 餵小鳥\n"
        "   • 2025/7/15 16:30 客戶會議\n"
        "   • 12/25 09:00 聖誕節聚餐\n\n"
        "🔍 查詢行程指令：\n"
        "   • 今日行程 - 查看今天的所有安排\n"
        "   • 明日行程 - 查看明天的計劃\n"
        "   • 本週行程 - 本週完整行程表\n"
        "   • 下週行程 - 下週所有安排\n"
        "   • 本月行程 - 本月份行程總覽\n"
        "   • 下個月行程 - 下月份規劃\n"
        "   • 明年行程 - 明年度安排\n\n"
        "⏰ 實用工具\n"
        "═══════════════\n"
        "🕐 倒數計時功能：\n"
        "   • 倒數3分鐘 / 倒數計時 / 開始倒數\n"
        "   • 倒數5分鐘\n\n"
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
        "   • 功能說明 / 說明 / help - 顯示此說明\n\n"
        "🔔 自動推播服務\n"
        "═══════════════\n"
        "🌅 每天早上 8:30 - 溫馨早安訊息\n"
        "📅 每週日晚上 22:00 - 下週行程摘要\n"
        "⏰ 每分鐘檢查 - 自動行程提醒推播\n\n"
        "💡 小提醒：系統會在行程前一小時自動提醒您！"
    )

# 美化的週報推播
def weekly_summary():
    logger.info("🔄 開始執行每週行程摘要...")
    try:
        # 檢查是否已設定群組 ID
        if TARGET_GROUP_ID == "C4e138aa0eb252daa89846daab0102e41":
            logger.warning("⚠️ 週報群組 ID 尚未設定，跳過週報推播")
            return
            
        all_rows = sheet.get_all_values()[1:]
        now = datetime.now(TAIWAN_TZ)  # 使用台灣時區
        
        # 計算下週一到下週日的範圍
        days_until_next_monday = (7 - now.weekday()) % 7
        if days_until_next_monday == 0:  # 如果今天是週一
            days_until_next_monday = 7   # 取下週一
            
        start = now + timedelta(days=days_until_next_monday)
        end = start + timedelta(days=6)
        start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        end = end.replace(hour=23, minute=59, second=59, microsecond=999999)
        
        logger.info(f"📊 查詢時間範圍：{start.strftime('%Y/%m/%d %H:%M')} 到 {end.strftime('%Y/%m/%d %H:%M')}")
        
        user_schedules = {}

        for row in all_rows:
            if len(row) < 5:
                continue
            try:
                date_str, time_str, content, user_id, _ = row
                dt = datetime.strptime(f"{date_str} {time_str}", "%Y/%m/%d %H:%M")
                # 確保比較時使用正確的時區
                dt = TAIWAN_TZ.localize(dt) if dt.tzinfo is None else dt.astimezone(TAIWAN_TZ)
                if start <= dt <= end:
                    user_schedules.setdefault(user_id, []).append((dt, content))
            except Exception as e:
                logger.error(f"❌ 處理行程資料失敗：{e}")
                continue

        logger.info(f"📈 找到 {len(user_schedules)} 位使用者有下週行程")
        
        if not user_schedules:
            # 如果沒有行程，也發送提醒
            message = (
                f"📅 下週行程預覽\n"
                f"🗓️ {start.strftime('%m/%d')} - {end.strftime('%m/%d')}\n"
                f"━━━━━━━━━━━━━━━━\n\n"
                f"🎉 太棒了！下週沒有安排任何行程\n"
                f"✨ 可以好好放鬆，享受自由時光！"
            )
        else:
            # 整理所有使用者的行程到一個訊息中
            message = (
                f"📅 下週行程預覽\n"
                f"🗓️ {start.strftime('%m/%d')} - {end.strftime('%m/%d')}\n"
                f"━━━━━━━━━━━━━━━━\n\n"
            )
            
            # 按日期排序所有行程
            all_schedules = []
            for user_id, items in user_schedules.items():
                for dt, content in items:
                    all_schedules.append((dt, content, user_id))
            
            all_schedules.sort()  # 按時間排序
            
            current_date = None
            for dt, content, user_id in all_schedules:
                # 如果是新的日期，加上日期標題
                if current_date != dt.date():
                    current_date = dt.date()
                    weekday_names = ["一", "二", "三", "四", "五", "六", "日"]
                    weekday = weekday_names[dt.weekday()]
                    message += f"\n📆 {dt.strftime('%m/%d')} (週{weekday})\n"
                    message += "─────────────────────\n"
                
                # 顯示時間和內容
                message += f"🕐 {dt.strftime('%H:%M')} │ {content}\n"
            
            message += "\n💡 記得提前準備，祝您一週順利！"
        
        try:
            success = send_line_message(TARGET_GROUP_ID, message, "週報摘要")
            if success:
                logger.info(f"✅ 已發送週報摘要到群組：{TARGET_GROUP_ID}")
            else:
                logger.error(f"❌ 週報摘要發送失敗")
        except Exception as e:
            logger.error(f"❌ 推播週報到群組失敗：{e}")
                
        logger.info("✅ 每週行程摘要執行完成")
                
    except Exception as e:
        logger.error(f"❌ 每週行程摘要執行失敗：{e}")

# 手動觸發週報（用於測試）
def manual_weekly_summary():
    logger.info("🔧 手動執行每週行程摘要...")
    weekly_summary()

# 🆕 排程任務 - 新增每分鐘檢查待發送行程的任務
scheduler.add_job(
    weekly_summary, 
    CronTrigger(day_of_week="sun", hour=22, minute=0, timezone=TAIWAN_TZ),
    id="weekly_summary"
)
scheduler.add_job(
    send_morning_message, 
    CronTrigger(hour=8, minute=30, timezone=TAIWAN_TZ),
    id="morning_message"
)

# 🆕 關鍵新增：每分鐘檢查待發送的行程提醒
scheduler.add_job(
    check_and_send_pending_reminders,
    CronTrigger(second=0, timezone=TAIWAN_TZ),  # 每分鐘的第0秒執行
    id="check_pending_reminders"
)

logger.info("🔔 自動行程提醒檢查器已啟動 - 每分鐘檢查一次")

# 指令對應表 - 保持與原版本一致的倒數計時觸發詞
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
    "倒數3分鐘": "countdown_3",
    "倒數5分鐘": "countdown_5",
    "哈囉": "hello",
    "hi": "hi",
    "你還會說什麼?": "what_else"
}

# 檢查文字是否為行程格式
def is_schedule_format(text):
    """檢查文字是否像是行程格式"""
    parts = text.strip().split()
    if len(parts) < 2:
        return False
    
    # 檢查前兩個部分是否像日期時間格式
    try:
        date_part, time_part = parts[0], parts[1]
        
        # 檢查日期格式 (M/D 或 YYYY/M/D)
        if "/" in date_part:
            date_segments = date_part.split("/")
            if len(date_segments) == 2 or len(date_segments) == 3:
                # 檢查是否都是數字
                if all(segment.isdigit() for segment in date_segments):
                    # 檢查時間格式 (HH:MM)，但允許沒有空格的情況
                    if ":" in time_part:
                        # 找到冒號的位置，提取時間部分
                        colon_index = time_part.find(":")
                        if colon_index > 0:
                            # 提取時間部分（HH:MM）
                            time_only = time_part[:colon_index+3]  # 包含HH:MM
                            if len(time_only) >= 4:  # 至少要有H:MM或HH:M
                                time_segments = time_only.split(":")
                                if len(time_segments) == 2:
                                    if all(segment.isdigit() for segment in time_segments):
                                        return True
    except:
        pass
    
    return False

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_text = event.message.text.strip()
    lower_text = user_text.lower()
    user_id = getattr(event.source, "group_id", None) or event.source.user_id
    reply = None  # 預設不回應
    
    logger.info(f"📨 收到訊息 - 用戶: {user_id}, 內容: {user_text}")
    
    # 檢查風雲榜功能
    ranking_reply = process_ranking_input(user_id, user_text)
    if ranking_reply:
        reply = ranking_reply
    
    # 檢查是否為確切匹配的指令
    elif user_text in EXACT_MATCHES:
        command = EXACT_MATCHES[user_text]
        
        if command in ["today", "tomorrow", "this_week", "next_week", "this_month", "next_month", "next_year"]:
            reply = get_schedule_by_period(user_id, command)
        elif command in ["countdown_3", "countdown_5"]:
            minutes = int(command.split("_")[1])
            reply = f"⏰ 開始 {minutes} 分鐘倒數計時！\n時間到我會通知你 🔔"
            
            # 生成唯一的 job ID
            current_time = datetime.now(TAIWAN_TZ)
            job_id = f"countdown_{user_id}_{int(current_time.timestamp())}"
            
            try:
                # 計算提醒時間，使用台灣時區
                reminder_time = current_time + timedelta(minutes=minutes)
                
                scheduler.add_job(
                    send_countdown_reminder,
                    'date',
                    run_date=reminder_time,
                    args=[user_id, minutes],
                    id=job_id,
                    timezone=TAIWAN_TZ
                )
                logger.info(f"✅ 倒數計時任務已設定：{minutes}分鐘，Job ID: {job_id}, 執行時間: {reminder_time}")
            except Exception as e:
                logger.error(f"❌ 設定倒數計時失敗：{e}")
                reply += f"\n⚠️ 提醒設定可能失敗，請重試"
        elif command == "hello":
            reply = "哈囉！👋 我是你的行程助理！\n\n輸入「功能說明」查看我能做什麼 😊"
        elif command == "hi":
            reply = "Hi there! 🌟\n\n我是LINE行程助理，隨時為您服務！\n輸入「help」看看我的功能吧 ✨"
        elif command == "what_else":
            reply = "我還會很多呢！ 😄\n\n📅 管理你的行程\n⏰ 設定提醒通知\n📊 處理風雲榜資料\n🌅 每日早安問候\n📈 週報推播\n\n還想知道更多嗎？輸入「功能說明」吧！"
    
    # 檢查其他指令
    elif any(keyword in lower_text for keyword in ["功能說明", "說明", "help"]):
        reply = send_help_message()
    elif "設定早安群組" in user_text:
        reply = handle_set_morning_group(user_id, user_text)
    elif "查看群組設定" in user_text:
        reply = f"📊 目前設定：\n群組ID: {TARGET_GROUP_ID}\n\n💡 如需修改，請使用「設定早安群組」指令"
    elif "測試早安" in user_text:
        send_morning_message()
        reply = "🧪 測試早安訊息已發送！"
    elif "測試週報" in user_text:
        manual_weekly_summary()
        reply = "📊 手動週報已執行！"
    elif "查看id" in lower_text:
        reply = f"🆔 您的ID資訊：\n{user_id}"
    elif "查看排程" in user_text:
        jobs = scheduler.get_jobs()
        if jobs:
            job_info = []
            for job in jobs:
                next_run = job.next_run_time.strftime('%Y-%m-%d %H:%M:%S %Z') if job.next_run_time else 'None'
                job_info.append(f"• {job.id}: {next_run}")
            reply = f"⚙️ 系統排程狀態：\n" + "\n".join(job_info)
        else:
            reply = "⚙️ 系統排程狀態：\n目前沒有排程任務"
    
    # 檢查是否為行程格式
    elif is_schedule_format(user_text):
        reply = add_schedule(user_id, user_text)
    
    # 如果有回應訊息，就發送
    if reply:
        try:
            with ApiClient(configuration) as api_client:
                line_bot_api = MessagingApi(api_client)
                line_bot_api.reply_message(
                    ReplyMessageRequest(
                        reply_token=event.reply_token,
                        messages=[TextMessage(text=reply)]
                    )
                )
            logger.info(f"✅ 回應訊息已送出給用戶: {user_id}")
        except Exception as e:
            logger.error(f"❌ 回應訊息失敗: {e}")

def handle_set_morning_group(user_id, text):
    """處理設定早安群組"""
    global TARGET_GROUP_ID
    if user_id.startswith("C"):  # 群組ID以C開頭
        TARGET_GROUP_ID = user_id
        logger.info(f"✅ 早安群組已設定為: {TARGET_GROUP_ID}")
        return "✅ 早安群組已設定成功！\n🌅 每天早上8:30會推播早安訊息"
    else:
        return "❌ 請在群組中使用此指令"

def get_schedule_by_period(user_id, period):
    """根據時間期間獲取行程"""
    try:
        all_rows = sheet.get_all_values()[1:]
        now = datetime.now(TAIWAN_TZ)  # 使用台灣時區
        
        # 設定時間範圍
        if period == "today":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = now.replace(hour=23, minute=59, second=59, microsecond=999999)
            title = "📅 今日行程"
        elif period == "tomorrow":
            tomorrow = now + timedelta(days=1)
            start = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
            end = tomorrow.replace(hour=23, minute=59, second=59, microsecond=999999)
            title = "📅 明日行程"
        elif period == "this_week":
            start = now - timedelta(days=now.weekday())
            start = start.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=6, hours=23, minutes=59, seconds=59, microseconds=999999)
            title = "📅 本週行程"
        elif period == "next_week":
            days_until_next_monday = (7 - now.weekday()) % 7
            if days_until_next_monday == 0:
                days_until_next_monday = 7
            start = now + timedelta(days=days_until_next_monday)
            start = start.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=6, hours=23, minutes=59, seconds=59, microseconds=999999)
            title = "📅 下週行程"
        elif period == "this_month":
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            if now.month == 12:
                end = datetime(now.year + 1, 1, 1, tzinfo=TAIWAN_TZ) - timedelta(microseconds=1)
            else:
                end = datetime(now.year, now.month + 1, 1, tzinfo=TAIWAN_TZ) - timedelta(microseconds=1)
            title = "📅 本月行程"
        elif period == "next_month":
            if now.month == 12:
                start = datetime(now.year + 1, 1, 1, tzinfo=TAIWAN_TZ)
                end = datetime(now.year + 1, 2, 1, tzinfo=TAIWAN_TZ) - timedelta(microseconds=1)
            else:
                start = datetime(now.year, now.month + 1, 1, tzinfo=TAIWAN_TZ)
                if now.month == 11:
                    end = datetime(now.year + 1, 1, 1, tzinfo=TAIWAN_TZ) - timedelta(microseconds=1)
                else:
                    end = datetime(now.year, now.month + 2, 1, tzinfo=TAIWAN_TZ) - timedelta(microseconds=1)
            title = "📅 下個月行程"
        elif period == "next_year":
            start = datetime(now.year + 1, 1, 1, tzinfo=TAIWAN_TZ)
            end = datetime(now.year + 2, 1, 1, tzinfo=TAIWAN_TZ) - timedelta(microseconds=1)
            title = "📅 明年行程"
        
        # 查詢行程
        schedules = []
        for row in all_rows:
            if len(row) < 5:
                continue
            try:
                date_str, time_str, content, row_user_id, _ = row
                if row_user_id == user_id:
                    dt = datetime.strptime(f"{date_str} {time_str}", "%Y/%m/%d %H:%M")
                    dt = TAIWAN_TZ.localize(dt) if dt.tzinfo is None else dt.astimezone(TAIWAN_TZ)
                    if start <= dt <= end:
                        schedules.append((dt, content))
            except Exception as e:
                logger.warning(f"⚠️ 解析行程資料失敗: {e}")
                continue
        
        # 格式化回應
        if not schedules:
            return f"{title}\n━━━━━━━━━━━━━━━━\n\n🎉 這段時間沒有安排行程\n✨ 可以好好放鬆一下！"
        
        schedules.sort()
        message = f"{title}\n━━━━━━━━━━━━━━━━\n\n"
        
        current_date = None
        for dt, content in schedules:
            if current_date != dt.date():
                current_date = dt.date()
                weekday_names = ["一", "二", "三", "四", "五", "六", "日"]
                weekday = weekday_names[dt.weekday()]
                message += f"\n📆 {dt.strftime('%m/%d')} (週{weekday})\n"
                message += "─────────────────────\n"
            message += f"🕐 {dt.strftime('%H:%M')} │ {content}\n"
        
        return message
        
    except Exception as e:
        logger.error(f"❌ 查詢行程失敗：{e}")
        return "❌ 查詢行程時發生錯誤"

def add_schedule(user_id, text):
    """新增行程"""
    try:
        parts = text.strip().split()
        if len(parts) < 3:
            return "❌ 行程格式錯誤\n請使用：月/日 時:分 行程內容"
        
        date_part = parts[0]
        time_part = parts[1]
        content = " ".join(parts[2:])
        
        # 解析日期
        if "/" in date_part:
            date_segments = date_part.split("/")
            if len(date_segments) == 2:
                month, day = map(int, date_segments)
                year = datetime.now(TAIWAN_TZ).year
            elif len(date_segments) == 3:
                year, month, day = map(int, date_segments)
            else:
                return "❌ 日期格式錯誤"
        else:
            return "❌ 日期格式錯誤"
        
        # 解析時間
        if ":" in time_part:
            time_segments = time_part.split(":")
            if len(time_segments) == 2:
                hour, minute = map(int, time_segments)
            else:
                return "❌ 時間格式錯誤"
        else:
            return "❌ 時間格式錯誤"
        
        # 建立 datetime 物件，使用台灣時區
        schedule_time = TAIWAN_TZ.localize(datetime(year, month, day, hour, minute))
        current_time = datetime.now(TAIWAN_TZ)
        
        # 檢查是否為過去時間
        if schedule_time < current_time:
            return "❌ 不能設定過去的時間"
        
        # 🆕 寫入 Google Sheets - 行程本身
        date_str = schedule_time.strftime("%Y/%m/%d")
        time_str = schedule_time.strftime("%H:%M")
        
        sheet.append_row([date_str, time_str, content, user_id, "已發送"])
        
        # 🆕 新增提醒行程（行程前一小時）- 標記為 "待發送"
        reminder_time = schedule_time - timedelta(hours=1)
        if reminder_time > current_time:
            reminder_date_str = reminder_time.strftime("%Y/%m/%d")
            reminder_time_str = reminder_time.strftime("%H:%M")
            reminder_content = f"⏰ 溫馨提醒：一小時後有「{content}」"
            
            # 將提醒寫入 Google Sheets，標記為 "待發送"
            sheet.append_row([reminder_date_str, reminder_time_str, reminder_content, user_id, "待發送"])
            
            logger.info(f"✅ 行程提醒已新增到 Google Sheets: {reminder_content}, 提醒時間: {reminder_time}")
        
        return (
            f"✅ 行程新增成功！\n\n"
            f"📅 日期：{schedule_time.strftime('%Y/%m/%d')}\n"
            f"🕐 時間：{schedule_time.strftime('%H:%M')}\n"
            f"📝 內容：{content}\n\n"
            f"⏰ 將在行程前一小時自動提醒您"
        )
        
    except ValueError as e:
        logger.error(f"❌ 日期或時間格式錯誤: {e}")
        return "❌ 日期或時間格式錯誤"
    except Exception as e:
        logger.error(f"❌ 新增行程失敗：{e}")
        return "❌ 新增行程時發生錯誤"

def send_schedule_reminder(user_id, content, schedule_time):
    """發送行程提醒（保留此函數以兼容可能的直接調用）"""
    try:
        current_time = datetime.now(TAIWAN_TZ)
        message = f"⏰ 行程提醒\n\n📅 {schedule_time.strftime('%m/%d %H:%M')}\n📝 {content}\n\n還有一小時就要開始囉！\n📍 {current_time.strftime('%H:%M:%S')}"
        
        success = send_line_message(user_id, message, "行程提醒")
        if success:
            logger.info(f"✅ 行程提醒已發送：{content}")
        else:
            logger.error(f"❌ 行程提醒發送失敗：{content}")
    except Exception as e:
        logger.error(f"❌ 發送行程提醒失敗：{e}")

if __name__ == "__main__":
    # 修復端口綁定問題 - 這是關鍵修復
    port = int(os.environ.get('PORT', 10000))  # Render 預設使用 10000
    host = '0.0.0.0'  # 重要：必須綁定到 0.0.0.0 而不是 localhost
    
    logger.info(f"🚀 LINE Reminder Bot 正在啟動...")
    logger.info(f"📡 監聽地址：{host}:{port}")
    logger.info(f"🌍 時區設定：{TAIWAN_TZ}")
    logger.info(f"⏰ 當前台灣時間：{datetime.now(TAIWAN_TZ)}")
    
    # 檢查重要環境變數
    if LINE_CHANNEL_ACCESS_TOKEN:
        logger.info("✅ LINE_CHANNEL_ACCESS_TOKEN 已設定")
    else:
        logger.error("❌ LINE_CHANNEL_ACCESS_TOKEN 未設定")
        
    if LINE_CHANNEL_SECRET:
        logger.info("✅ LINE_CHANNEL_SECRET 已設定")
    else:
        logger.error("❌ LINE_CHANNEL_SECRET 未設定")
    
    # 🆕 顯示排程狀態
    jobs = scheduler.get_jobs()
    logger.info(f"📋 已設定的排程任務：")
    for job in jobs:
        logger.info(f"   • {job.id}: {job.trigger}")
    
    # 啟動 Flask 應用
    app.run(
        host=host,
        port=port,
        debug=False,  # 生產環境設為 False
        threaded=True  # 啟用多線程支援
    )
