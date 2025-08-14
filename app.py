import os
import json
import random
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
ranking_data = {}  # 風雲榜資料暫存

# 🆕 抽籤功能 - 抽籤名單
LOTTERY_NAMES = ["奕君", "小嫺", "嘉憶", "惠華"]

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

# 🆕 抽籤功能
def process_lottery(command):
    """處理抽籤指令"""
    try:
        # 解析抽籤指令
        if command.startswith("抽") and len(command) == 2:
            number_str = command[1]
            if number_str.isdigit():
                number = int(number_str)
                
                # 檢查抽籤數量是否有效 (限制最多抽3位)
                if number < 1 or number > 3:
                    return "請輸入抽1到抽3"
                
                # 進行抽籤
                selected = random.sample(LOTTERY_NAMES, number)
                
                # 簡潔輸出，直接顯示名字
                return "、".join(selected)
                
        return None
        
    except Exception as e:
        print(f"❌ 抽籤處理失敗：{e}")
        return "抽籤系統發生錯誤"

# 🆕 新增：檢查並發送待發送的行程提醒
def check_and_send_pending_reminders():
    """檢查並發送待發送的行程提醒"""
    try:
        print("🔍 檢查待發送的行程提醒...")
        
        all_rows = sheet.get_all_values()
        if len(all_rows) <= 1:
            return
            
        now = datetime.now()
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
                    
                # 解析行程時間
                schedule_dt = datetime.strptime(f"{date_str} {time_str}", "%Y/%m/%d %H:%M")
                
                # 檢查是否到了發送時間（前後2分鐘內）
                time_diff = abs((now - schedule_dt).total_seconds())
                
                if time_diff <= 120:  # 2分鐘內
                    print(f"📤 發送提醒: {content} 給 {user_id}")
                    
                    try:
                        # 發送推播
                        line_bot_api.push_message(user_id, TextSendMessage(text=content))
                        
                        # 🎯 重點：只有推播成功才更新狀態
                        sheet.update_cell(i, 5, f"已發送 {now.strftime('%H:%M')}")
                        sent_count += 1
                        print(f"✅ 提醒已發送並更新狀態: {content}")
                        
                    except Exception as push_error:
                        print(f"❌ 推播失敗: {push_error}")
                        # 推播失敗時標記為失敗，不標記為已發送
                        sheet.update_cell(i, 5, f"發送失敗 {now.strftime('%H:%M')}")
                        
            except Exception as row_error:
                print(f"❌ 處理第{i}行資料失敗: {row_error}")
                continue
        
        if sent_count > 0:
            print(f"📊 行程提醒檢查完成: 成功發送 {sent_count} 項")
            
    except Exception as e:
        print(f"❌ 檢查待發送行程提醒失敗：{e}")

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

def is_valid_ranking_format(text):
    """檢查是否為有效的風雲榜格式"""
    try:
        # 檢查是否為單一觸發詞
        if text.strip() == "風雲榜":
            return True
            
        # 檢查是否為9行資料格式
        lines = text.strip().split('\n')
        if len(lines) != 9:
            return False
            
        # 檢查每行是否都有內容
        for line in lines:
            if not line.strip():
                return False
                
        # 基本格式檢查通過
        return True
        
    except:
        return False

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
        
        # 檢查是否為正確的9行資料格式
        lines = text.strip().split('\n')
        if len(lines) == 9:
            return process_batch_ranking_data(user_id, lines)
        
        # 如果不是正確格式，返回None (將被忽略)
        return None
        
    except Exception as e:
        print(f"❌ 處理風雲榜輸入失敗：{e}")
        return None

def process_batch_ranking_data(user_id, lines):
    """處理批量風雲榜資料"""
    try:
        # 提取並清理資料
        data = [line.strip() for line in lines]
        
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
        print(f"❌ 處理批量資料失敗：{e}")
        return None

def write_ranking_to_sheet_batch(user_id, data_batch):
    """將批量風雲榜資料寫入Google Sheets工作表2"""
    try:
        worksheet = get_worksheet2()
        if not worksheet:
            return None
        
        # 解析同學姓名（可能有多個，用逗號分隔）
        student_names_str = data_batch["data"][0]
        student_names = [name.strip() for name in student_names_str.split(",") if name.strip()]
        
        if not student_names:
            return None
        
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
        
        # 只返回簡單的成功訊息
        return "✅ 已成功寫入工作表2"
        
    except Exception as e:
        print(f"❌ 寫入工作表2失敗：{e}")
        return None

def write_ranking_to_sheet(user_id, user_session):
    """將風雲榜資料寫入Google Sheets工作表2"""
    try:
        worksheet = get_worksheet2()
        if not worksheet:
            return None
        
        # 解析同學姓名（可能有多個，用逗號分隔）
        student_names_str = user_session["data"][0]
        student_names = [name.strip() for name in student_names_str.split(",") if name.strip()]
        
        if not student_names:
            return None
        
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
        
        # 只返回簡單的成功訊息
        return "✅ 已成功寫入工作表2"
        
    except Exception as e:
        print(f"❌ 寫入工作表2失敗：{e}")
        # 清理使用者的輸入狀態
        if user_id in ranking_data:
            del ranking_data[user_id]
        return None

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
        line_bot_api.push_message(user_id, TextSendMessage(text=f"⏰ 時間到！{minutes}分鐘倒數計時結束"))
        print(f"✅ {minutes}分鐘倒數提醒已發送給：{user_id}")
    except Exception as e:
        print(f"❌ 推播{minutes}分鐘倒數提醒失敗：{e}")

# 美化的功能說明 (🆕 已更新包含1分鐘倒數)
def send_help_message():
    return (
        "🤖 LINE 行程助理 - 完整功能指南\n"
        "━━━━━━━━━━━━━━━━\n\n"
        "🎲 抽籤功能\n"
        "═══════════════\n"
        "🎯 參與名單：奕君、小嫺、嘉憶、惠華\n"
        "🎪 抽籤指令：\n"
        "   • 抽1 - 抽出1位同學\n"
        "   • 抽2 - 抽出2位同學\n"
        "   • 抽3 - 抽出3位同學\n"
        "💡 直接顯示抽中的名字\n\n"
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
        "   • 倒數1分鐘 - 快速1分鐘倒數\n"
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
    print("🔄 開始執行每週行程摘要...")
    try:
        # 檢查是否已設定群組 ID
        if TARGET_GROUP_ID == "C4e138aa0eb252daa89846daab0102e41":
            print("⚠️ 週報群組 ID 尚未設定，跳過週報推播")
            return
            
        all_rows = sheet.get_all_values()[1:]
        now = datetime.now()
        
        # 計算下週一到下週日的範圍
        days_until_next_monday = (7 - now.weekday()) % 7
        if days_until_next_monday == 0:  # 如果今天是週一
            days_until_next_monday = 7   # 取下週一
            
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
            line_bot_api.push_message(TARGET_GROUP_ID, TextSendMessage(text=message))
            print(f"✅ 已發送週報摘要到群組：{TARGET_GROUP_ID}")
        except Exception as e:
            print(f"❌ 推播週報到群組失敗：{e}")
                
        print("✅ 每週行程摘要執行完成")
                
    except Exception as e:
        print(f"❌ 每週行程摘要執行失敗：{e}")

# 手動觸發週報（用於測試）
def manual_weekly_summary():
    print("🔧 手動執行每週行程摘要...")
    weekly_summary()

# 🆕 排程任務 - 新增行程提醒檢查
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

# 🆕 關鍵新增：每分鐘檢查待發送的行程提醒
scheduler.add_job(
    check_and_send_pending_reminders,
    CronTrigger(minute="*"),  # 每分鐘執行
    id="pending_reminders"
)

# 🆕 指令對應表 (新增倒數1分鐘)
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
    "倒數1分鐘": "countdown_1",  # 🆕 新增1分鐘倒數
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

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_text = event.message.text.strip()
    lower_text = user_text.lower()
    user_id = getattr(event.source, "group_id", None) or event.source.user_id
    reply = None  # 預設不回應

    # 🆕 抽籤功能處理 - 優先處理
    if user_text.startswith("抽") and len(user_text) == 2:
        reply = process_lottery(user_text)
        if reply:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
            return

    # 風雲榜功能處理 - 優先處理，並且只在有效格式時處理
    if is_valid_ranking_format(user_text):
        reply = process_ranking_input(user_id, user_text)
        # 只有當 reply 不是 None 時才回應
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
            f"   • 週報摘要：每週日 22:00\n"
            f"   • 行程提醒：每分鐘檢查"
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
    elif lower_text == "檢查行程" or lower_text == "測試提醒":
        try:
            check_and_send_pending_reminders()
            reply = "✅ 行程提醒檢查已手動執行\n📝 請查看日誌確認處理結果"
        except Exception as e:
            reply = f"❌ 行程檢查失敗：{str(e)}"
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
                    job_name = "早安訊息" if job.id == "morning_message" else "週報摘要" if job.id == "weekly_summary" else "行程提醒檢查" if job.id == "pending_reminders" else job.id
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
        reply_type = next((v for k, v in EXACT_MATCHES.items() if k.lower() == lower_text), None)

        if reply_type == "hello":
            reply = "🙋‍♀️ 怎樣？有什麼需要幫忙的嗎？"
        elif reply_type == "hi":
            reply = "👋 呷飽沒？需要安排什麼行程嗎？"
        elif reply_type == "what_else":
            reply = "💕 我愛你 ❤️\n\n還有很多功能等你發現喔！\n輸入「功能說明」查看完整指令列表～"
        # 🆕 新增1分鐘倒數處理
        elif reply_type == "countdown_1":
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
                id=f"countdown_1_{user_id}_{datetime.now().timestamp()}"
            )
        elif reply_type == "countdown_3":
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
                id=f"countdown_3_{user_id}_{datetime.now().timestamp()}"
            )
        elif reply_type == "countdown_5":
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
                id=f"countdown_5_{user_id}_{datetime.now().timestamp()}"
            )
        elif reply_type:
            reply = get_schedule(reply_type, user_id)
        else:
            # 檢查是否為行程格式
            if is_schedule_format(user_text):
                reply = try_add_schedule(user_text, user_id)
            # 如果不是行程格式，就不回應（reply 保持 None）

    # 只有在 reply 不為 None 時才回應
    if reply:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

def get_schedule(period, user_id):
    try:
        all_rows = sheet.get_all_values()[1:]
        now = datetime.now()
        schedules = []

        # 定義期間名稱和表情符號
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

        # 按時間排序
        schedules.sort()
        
        # 格式化輸出
        result = (
            f"{info['emoji']} {info['name']}\n"
            f"━━━━━━━━━━━━━━━━\n\n"
        )
        
        current_date = None
        weekday_names = ["一", "二", "三", "四", "五", "六", "日"]
        
        for dt, content in schedules:
            # 如果是新的日期，加上日期標題
            if current_date != dt.date():
                current_date = dt.date()
                if len(schedules) > 1 and period in ["this_week", "next_week", "this_month", "next_month", "next_year"]:
                    weekday = weekday_names[dt.weekday()]
                    result += f"📆 {dt.strftime('%m/%d')} (週{weekday})\n"
                    result += "─────────────────────\n"
            
            # 顯示時間和內容
            result += f"🕐 {dt.strftime('%H:%M')} │ {content}\n"
            
            # 在多日期顯示時添加空行
            if len(schedules) > 1 and period in ["this_week", "next_week", "this_month", "next_month", "next_year"]:
                # 檢查下一個行程是否是不同日期
                current_index = schedules.index((dt, content))
                if current_index < len(schedules) - 1:
                    next_dt, _ = schedules[current_index + 1]
                    if next_dt.date() != dt.date():
                        result += "\n"

        # 添加友善的結尾
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
            
            # 處理時間和內容可能沒有空格分隔的情況
            time_part = None
            content = None
            
            # 尋找時間格式 HH:MM
            if ":" in time_and_content:
                colon_index = time_and_content.find(":")
                if colon_index >= 1:
                    # 找到時間的開始位置
                    time_start = max(0, colon_index - 2)
                    while time_start < colon_index and not time_and_content[time_start].isdigit():
                        time_start += 1
                    
                    # 找到時間的結束位置（冒號後2位數字）
                    time_end = colon_index + 3
                    if time_end <= len(time_and_content):
                        potential_time = time_and_content[time_start:time_end]
                        # 驗證時間格式
                        if ":" in potential_time:
                            time_segments = potential_time.split(":")
                            if len(time_segments) == 2 and all(seg.isdigit() for seg in time_segments):
                                time_part = potential_time
                                content = time_and_content[time_end:].strip()
                                
                                # 如果沒有內容，可能是因為時間和內容之間沒有空格
                                if not content:
                                    content = time_and_content[time_end:].strip()
            
            # 如果無法解析時間，返回格式錯誤
            if not time_part or not content:
                return (
                    "❌ 時間格式錯誤\n"
                    "━━━━━━━━━━━━━━━━\n"
                    "📝 正確格式：月/日 時:分 行程內容\n\n"
                    "✅ 範例：\n"
                    "   • 7/1 14:00 開會\n"
                    "   • 12/25 09:30 聖誕聚餐"
                )
            
            # 如果日期格式是 M/D，自動加上當前年份
            if date_part.count("/") == 1:
                date_part = f"{datetime.now().year}/{date_part}"
            
            dt = datetime.strptime(f"{date_part} {time_part}", "%Y/%m/%d %H:%M")
            
            # 檢查日期是否為過去時間
            if dt < datetime.now():
                return (
                    "❌ 無法新增過去的時間\n"
                    "━━━━━━━━━━━━━━━━\n"
                    "⏰ 請確認日期和時間是否正確\n"
                    "💡 只能安排未來的行程喔！"
                )
            
            # 🆕 修改：新增行程時同時新增提醒
            # 新增主要行程
            sheet.append_row([
                dt.strftime("%Y/%m/%d"),
                dt.strftime("%H:%M"),
                content,
                user_id,
                ""
            ])
            
            # 🆕 新增提醒行程（行程前1小時）
            reminder_dt = dt - timedelta(hours=1)
            if reminder_dt > datetime.now():
                reminder_content = f"⏰ 溫馨提醒：一小時後有「{content}」"
                sheet.append_row([
                    reminder_dt.strftime("%Y/%m/%d"),
                    reminder_dt.strftime("%H:%M"),
                    reminder_content,
                    user_id,
                    "待發送"
                ])
                print(f"✅ 已新增提醒行程: {reminder_content} at {reminder_dt}")
            
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
    print("🎲 抽籤功能：")
    print("   🎯 抽籤名單：奕君、小嫺、嘉憶、惠華")
    print("   🎪 抽籤指令：抽1、抽2、抽3")
    print("   💡 直接顯示抽中的名字")
    print("📊 風雲榜功能：")
    print("   🎯 輸入 '風雲榜' 查看使用說明")
    print("   📝 完全吻合9行格式時才會處理")
    print("   ✅ 成功寫入後回應：已成功寫入工作表2")
    print("   ❌ 不吻合格式直接忽略，不回應錯誤訊息")
    print("📅 自動排程服務：")
    print("   🌅 每天早上 8:30 - 溫馨早安訊息")
    print("   📊 每週日晚上 22:00 - 下週行程摘要")
    print("   ⏰ 每分鐘檢查 - 自動行程提醒推播")
    print("⏰ 倒數計時功能：")
    print("   🕐 倒數1分鐘：輸入 '倒數1分鐘'")  # 🆕 新增啟動訊息
    print("   🕐 倒數3分鐘：輸入 '倒數3分鐘' 或 '倒數計時' 或 '開始倒數'")
    print("   🕐 倒數5分鐘：輸入 '倒數5分鐘'")
    print("🔧 測試指令：")
    print("   📝 檢查行程 / 測試提醒 - 手動檢查待發送行程")
    print("💡 輸入 '功能說明' 查看完整功能列表")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    
    # 顯示目前排程狀態
    try:
        jobs = scheduler.get_jobs()
        print(f"✅ 系統狀態：已載入 {len(jobs)} 個排程工作")
        for job in jobs:
            next_run = job.next_run_time.strftime('%Y/%m/%d %H:%M:%S') if job.next_run_time else "未設定"
            job_name = "🌅 早安訊息" if job.id == "morning_message" else "📊 週報摘要" if job.id == "weekly_summary" else "⏰ 行程提醒檢查" if job.id == "pending_reminders" else job.id
            print(f"   • {job_name}: 下次執行 {next_run}")
    except Exception as e:
        print(f"❌ 查看排程狀態失敗：{e}")
    
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("🚀 LINE Bot 已成功啟動，準備為您服務！")
    
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
