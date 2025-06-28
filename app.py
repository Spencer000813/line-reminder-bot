# 自動群組識別和設定功能

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

# 自動群組管理
TARGET_GROUP_ID = None  # 將在第一次使用時自動設定
ACTIVE_GROUPS = set()   # 記錄所有活躍的群組

# 風雲榜功能相關變數
RANKING_SPREADSHEET_ID = "1LkPCLbaw5wmPao9g2mMEMRT7eklteR-6RLaJNYP8OQA"
WORKSHEET_NAME = "工作表2"
ranking_data = {}

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

# 自動群組管理函數
def auto_register_group(group_id):
    """自動註冊群組為活躍群組"""
    global TARGET_GROUP_ID, ACTIVE_GROUPS
    
    if group_id:
        ACTIVE_GROUPS.add(group_id)
        
        # 如果還沒有設定主要群組，自動設定為第一個群組
        if TARGET_GROUP_ID is None:
            TARGET_GROUP_ID = group_id
            print(f"🎯 自動設定主要群組ID：{group_id}")
            return True
    return False

def get_primary_group():
    """取得主要群組ID，如果沒有則使用第一個活躍群組"""
    global TARGET_GROUP_ID, ACTIVE_GROUPS
    
    if TARGET_GROUP_ID:
        return TARGET_GROUP_ID
    elif ACTIVE_GROUPS:
        TARGET_GROUP_ID = list(ACTIVE_GROUPS)[0]
        print(f"🎯 使用第一個活躍群組作為主要群組：{TARGET_GROUP_ID}")
        return TARGET_GROUP_ID
    return None

def send_to_all_groups(message):
    """發送訊息到所有活躍群組"""
    success_count = 0
    for group_id in ACTIVE_GROUPS:
        try:
            line_bot_api.push_message(group_id, TextSendMessage(text=message))
            success_count += 1
            print(f"✅ 訊息已發送到群組：{group_id}")
        except Exception as e:
            print(f"❌ 發送到群組 {group_id} 失敗：{e}")
    
    return success_count

# 修改後的發送早安訊息
def send_morning_message():
    try:
        primary_group = get_primary_group()
        if primary_group:
            message = "🌅 早安！新的一天開始了 ✨\n\n願你今天充滿活力與美好！"
            line_bot_api.push_message(primary_group, TextSendMessage(text=message))
            print(f"✅ 早安訊息已發送到主要群組: {primary_group}")
        else:
            print("⚠️ 沒有找到活躍的群組，跳過早安訊息")
    except Exception as e:
        print(f"❌ 發送早安訊息失敗：{e}")

# 修改後的倒數提醒函數
def send_countdown_reminder(target_id, minutes, is_group=False):
    try:
        if minutes == 1:
            message = "⏰ 時間到！1分鐘倒數計時結束 🔔"
        else:
            message = f"⏰ 時間到！{minutes}分鐘倒數計時結束"
        
        line_bot_api.push_message(target_id, TextSendMessage(text=message))
        print(f"✅ {minutes}分鐘倒數提醒已發送給：{target_id} (群組: {is_group})")
    except Exception as e:
        print(f"❌ 推播{minutes}分鐘倒數提醒失敗：{e}")
        print(f"目標ID: {target_id}")
        print(f"是否為群組: {is_group}")

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_text = event.message.text.strip()
    lower_text = user_text.lower()
    
    # 自動識別和記錄群組
    if hasattr(event.source, 'group_id') and event.source.group_id:
        # 在群組中，自動註冊群組
        group_id = event.source.group_id
        is_new_group = auto_register_group(group_id)
        target_id = group_id
        is_group = True
        user_id = group_id  # 用於一般功能
        
        print(f"📱 群組訊息 - 群組ID: {target_id}, 發送者: {event.source.user_id}")
        if is_new_group:
            print(f"🆕 新群組已自動註冊：{group_id}")
            
    elif hasattr(event.source, 'room_id') and event.source.room_id:
        # 在聊天室中
        room_id = event.source.room_id
        auto_register_group(room_id)  # 聊天室也視為群組
        target_id = room_id
        is_group = True
        user_id = room_id
        print(f"🏠 聊天室訊息 - 聊天室ID: {target_id}, 發送者: {event.source.user_id}")
    else:
        # 私人對話
        target_id = event.source.user_id
        is_group = False
        user_id = event.source.user_id
        print(f"👤 私人訊息 - 用戶ID: {target_id}")
    
    reply = None

    # 風雲榜功能處理 - 優先處理
    if user_text == "風雲榜" or (user_text.count('\n') >= 8 and len(user_text.strip().split('\n')) >= 9):
        reply = process_ranking_input(user_id, user_text)
        if reply:
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
            return

    # 群組管理指令 - 簡化版
    if lower_text == "群組狀態" or lower_text == "查看群組":
        primary_group = get_primary_group()
        reply = (
            f"📊 群組管理狀態\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"👥 主要群組：{primary_group or '未設定'}\n"
            f"📱 活躍群組數量：{len(ACTIVE_GROUPS)}\n"
            f"🔔 推播狀態：{'✅ 已啟用' if primary_group else '❌ 未啟用'}\n\n"
            f"🕐 自動推播時間：\n"
            f"   • 早安訊息：每天 8:30\n"
            f"   • 週報摘要：每週日 22:00\n\n"
            f"💡 機器人會自動記住在哪些群組中使用"
        )
    elif lower_text == "設為主要群組":
        if is_group:
            global TARGET_GROUP_ID
            TARGET_GROUP_ID = target_id
            reply = (
                "✅ 主要群組設定成功！\n"
                "━━━━━━━━━━━━━━━━\n"
                f"📱 群組 ID：{target_id}\n"
                f"🌅 早安訊息：每天早上 8:30\n"
                f"📅 週報摘要：每週日晚上 22:00\n\n"
                f"💡 所有推播功能已啟用！"
            )
        else:
            reply = "❌ 此指令只能在群組中使用"
    elif lower_text == "測試早安":
        if is_group and target_id == get_primary_group():
            reply = "🌅 早安！新的一天開始了 ✨\n\n願你今天充滿活力與美好！"
        elif is_group:
            reply = "⚠️ 此群組不是主要推播群組\n💡 輸入「設為主要群組」可設定為推播群組"
        else:
            reply = "❌ 請在群組中使用此功能"
    elif lower_text == "測試週報":
        try:
            manual_weekly_summary()
            reply = "✅ 週報已手動執行完成\n📝 請檢查執行記錄確認推播狀況"
        except Exception as e:
            reply = f"❌ 週報執行失敗：{str(e)}"
    elif lower_text == "查看id":
        user_id_display = event.source.user_id
        if is_group:
            reply = (
                f"📋 當前資訊\n"
                f"━━━━━━━━━━━━━━━━\n"
                f"👥 {'群組' if hasattr(event.source, 'group_id') else '聊天室'} ID：{target_id}\n"
                f"👤 使用者 ID：{user_id_display}\n"
                f"🎯 推播目標：{target_id}\n"
                f"⭐ 主要群組：{'是' if target_id == get_primary_group() else '否'}"
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
        # 處理其他指令
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
                
                countdown_time = datetime.now() + timedelta(minutes=1)
                job_id = f"countdown_1_{target_id}_{int(datetime.now().timestamp())}"
                
                scheduler.add_job(
                    send_countdown_reminder,
                    trigger="date",
                    run_date=countdown_time,
                    args=[target_id, 1, is_group],
                    id=job_id
                )
                
                print(f"✅ 已設定1分鐘倒數提醒，執行時間：{countdown_time.strftime('%Y/%m/%d %H:%M:%S')}")
                print(f"📋 排程ID：{job_id}")
                print(f"🎯 目標用戶/群組：{target_id} (群組: {is_group})")
                
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
                countdown_time = datetime.now() + timedelta(minutes=3)
                job_id = f"countdown_3_{target_id}_{int(datetime.now().timestamp())}"
                
                scheduler.add_job(
                    send_countdown_reminder,
                    trigger="date",
                    run_date=countdown_time,
                    args=[target_id, 3, is_group],
                    id=job_id
                )
                print(f"✅ 已設定3分鐘倒數提醒：{countdown_time.strftime('%Y/%m/%d %H:%M:%S')}")
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
                countdown_time = datetime.now() + timedelta(minutes=5)
                job_id = f"countdown_5_{target_id}_{int(datetime.now().timestamp())}"
                
                scheduler.add_job(
                    send_countdown_reminder,
                    trigger="date",
                    run_date=countdown_time,
                    args=[target_id, 5, is_group],
                    id=job_id
                )
                print(f"✅ 已設定5分鐘倒數提醒：{countdown_time.strftime('%Y/%m/%d %H:%M:%S')}")
            except Exception as e:
                print(f"❌ 設定5分鐘倒數失敗：{e}")
                reply = "❌ 倒數計時設定失敗，請稍後再試"
        elif reply_type:
            reply = get_schedule(reply_type, user_id)
        else:
            # 檢查是否為行程格式
            if is_schedule_format(user_text):
                reply = try_add_schedule(user_text, user_id)

    # 只有在 reply 不為 None 時才回應
    if reply:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))

# 更新後的功能說明
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
        "⚙️ 群組管理 (自動化)\n"
        "═══════════════\n"
        "🔄 自動功能：\n"
        "   • 機器人會自動記住使用的群組\n"
        "   • 第一次使用的群組自動成為主要群組\n\n"
        "🔧 手動指令：\n"
        "   • 群組狀態 - 查看目前設定\n"
        "   • 設為主要群組 - 設定為推播群組\n"
        "   • 測試早安 - 測試早安訊息\n"
        "   • 測試週報 - 手動執行週報\n\n"
        "📊 系統資訊：\n"
        "   • 查看id - 顯示群組/使用者 ID\n"
        "   • 查看排程 - 檢視系統排程狀態\n"
        "   • 功能說明 - 顯示此說明\n\n"
        "🔔 自動推播服務\n"
        "═══════════════\n"
        "🌅 每天早上 8:30 - 溫馨早安訊息\n"
        "📅 每週日晚上 22:00 - 下週行程摘要\n\n"
        "💡 小提醒：\n"
        "• 機器人會自動記住在哪個群組中使用\n"
        "• 不需要手動輸入群組ID\n"
        "• 系統會在行程前一小時自動提醒"
    )

# 修改週報摘要，使用主要群組
def weekly_summary():
    print("🔄 開始執行每週行程摘要...")
    try:
        primary_group = get_primary_group()
        if not primary_group:
            print("⚠️ 沒有設定主要群組，跳過週報推播")
            return
            
        all_rows = sheet.get_all_values()[1:]
        now = datetime.now()
        
        # 計算下週一到下週日的範圍
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
            line_bot_api.push_message(primary_group, TextSendMessage(text=message))
            print(f"✅ 已發送週報摘要到主要群組：{primary_group}")
        except Exception as e:
            print(f"❌ 推播週報到群組失敗：{e}")
                
        print("✅ 每週行程摘要執行完成")
                
    except Exception as e:
        print(f"❌ 每週行程摘要執行失敗：{e}")

def manual_weekly_summary():
    print("🔧 手動執行每週行程摘要...")
    weekly_summary()

# 在啟動時顯示狀態
if __name__ == "__main__":
    print("🤖 LINE 行程助理啟動中...")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("🆕 自動群組管理功能：")
    print("   🎯 機器人會自動記住在哪些群組中使用")
    print("   📱 第一次使用的群組自動成為主要推播群組")
    print("   🔄 不需要手動輸入群組ID")
    print("📊 風雲榜功能：")
    print("   🎯 輸入 '風雲榜' 開始資料輸入流程")
    print("📅 自動排程服務：")
    print("   🌅 每天早上 8:30 - 溫馨早安訊息")
    print("   📊 每週日晚上 22:00 - 下週行程摘要")
    print("⏰ 倒數計時功能：1分鐘、3分鐘、5分鐘")
    print("💡 輸入 '功能說明' 查看完整功能列表")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("🚀 LINE Bot 已成功啟動，準備自動管理群組！")
    
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
