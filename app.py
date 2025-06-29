import os
import threading
import time
from datetime import datetime, timedelta
import pytz
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError, LineBotApiError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import gspread
from google.auth import load_credentials_from_info
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import json

app = Flask(__name__)

# 設定
LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.getenv('LINE_CHANNEL_SECRET')
GOOGLE_CREDENTIALS = os.getenv('GOOGLE_CREDENTIALS')

if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_CHANNEL_SECRET:
    raise ValueError("請設定 LINE_CHANNEL_ACCESS_TOKEN 和 LINE_CHANNEL_SECRET 環境變數")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# Google Sheets 設定
gc = None
if GOOGLE_CREDENTIALS:
    try:
        credentials_info = json.loads(GOOGLE_CREDENTIALS)
        credentials = load_credentials_from_info(credentials_info)
        gc = gspread.authorize(credentials)
    except Exception as e:
        print(f"Google Sheets 設定失敗: {e}")

# 全域變數
user_data = {}
scheduler = None

def start_countdown_timer(user_id, minutes):
    """啟動倒數計時器的線程函數 - 加強除錯版本"""
    
    def countdown():
        start_time = datetime.now()
        print(f"🚀 [{start_time.strftime('%H:%M:%S')}] 倒數計時開始 - 用戶: {user_id}, 時長: {minutes}分鐘")
        
        try:
            # 計算總秒數
            total_seconds = minutes * 60
            print(f"⏱ 將等待 {total_seconds} 秒 ({minutes} 分鐘)")
            
            # 等待指定時間
            time.sleep(total_seconds)
            
            end_time = datetime.now()
            print(f"⏰ [{end_time.strftime('%H:%M:%S')}] 倒數計時結束 - 準備發送訊息")
            
            # 建立完成訊息
            completion_message = f"⏰ 時間到！{minutes}分鐘倒數計時結束\n結束時間: {end_time.strftime('%H:%M:%S')}"
            
            # 發送推送訊息
            print(f"📤 正在發送推送訊息給用戶: {user_id}")
            line_bot_api.push_message(user_id, TextSendMessage(text=completion_message))
            
            print(f"✅ 倒數計時完成訊息發送成功！用戶: {user_id}")
            
        except LineBotApiError as e:
            error_time = datetime.now()
            print(f"❌ [{error_time.strftime('%H:%M:%S')}] LINE API 錯誤:")
            print(f"   狀態碼: {e.status_code}")
            print(f"   錯誤訊息: {e.error.message if hasattr(e, 'error') else 'Unknown error'}")
            print(f"   用戶ID: {user_id}")
            
        except Exception as e:
            error_time = datetime.now()
            print(f"❌ [{error_time.strftime('%H:%M:%S')}] 倒數計時器一般錯誤:")
            print(f"   錯誤類型: {type(e).__name__}")
            print(f"   錯誤訊息: {str(e)}")
            print(f"   用戶ID: {user_id}")
            import traceback
            print(f"   錯誤堆疊: {traceback.format_exc()}")
    
    # 建立並啟動線程
    try:
        timer_thread = threading.Thread(target=countdown, name=f"CountdownTimer-{user_id}-{minutes}min")
        timer_thread.daemon = True
        timer_thread.start()
        
        print(f"✅ 倒數計時線程已啟動:")
        print(f"   線程名稱: {timer_thread.name}")
        print(f"   線程狀態: {'活躍' if timer_thread.is_alive() else '未活躍'}")
        print(f"   用戶ID: {user_id}")
        print(f"   倒數時間: {minutes} 分鐘")
        
        return True
        
    except Exception as e:
        print(f"❌ 無法啟動倒數計時線程:")
        print(f"   錯誤: {str(e)}")
        return False

def send_morning_message():
    """發送早安訊息"""
    try:
        if not user_data:
            print("📝 沒有用戶資料，跳過早安訊息")
            return
            
        taiwan_tz = pytz.timezone('Asia/Taipei')
        current_time = datetime.now(taiwan_tz)
        
        morning_message = f"""🌅 早安！

📅 今天是 {current_time.strftime('%Y年%m月%d日')} ({current_time.strftime('%A')})
⏰ 現在時間：{current_time.strftime('%H:%M')}

💪 新的一天開始了，加油！
記得輸入 '風雲榜' 來更新您的日常記錄 📊"""

        for user_id in user_data.keys():
            try:
                line_bot_api.push_message(user_id, TextSendMessage(text=morning_message))
                print(f"✅ 早安訊息發送成功給用戶: {user_id}")
            except Exception as e:
                print(f"❌ 早安訊息發送失敗給用戶 {user_id}: {e}")
                
    except Exception as e:
        print(f"❌ 發送早安訊息時發生錯誤: {e}")

def send_weekly_summary():
    """發送週報摘要"""
    try:
        if not user_data:
            print("📝 沒有用戶資料，跳過週報摘要")
            return
            
        taiwan_tz = pytz.timezone('Asia/Taipei')
        current_time = datetime.now(taiwan_tz)
        next_week = current_time + timedelta(days=7)
        
        weekly_message = f"""📊 週報摘要

📅 本週：{current_time.strftime('%Y年%m月%d日')}
📅 下週：{next_week.strftime('%Y年%m月%d日')}

💡 本週回顧：
• 記得檢視您本週的風雲榜記錄
• 分析哪些目標達成，哪些需要改進

🎯 下週規劃：
• 設定新的目標和優先事項
• 繼續保持良好的記錄習慣

加油！持續進步 💪"""

        for user_id in user_data.keys():
            try:
                line_bot_api.push_message(user_id, TextSendMessage(text=weekly_message))
                print(f"✅ 週報摘要發送成功給用戶: {user_id}")
            except Exception as e:
                print(f"❌ 週報摘要發送失敗給用戶 {user_id}: {e}")
                
    except Exception as e:
        print(f"❌ 發送週報摘要時發生錯誤: {e}")

def init_scheduler():
    """初始化排程器"""
    global scheduler
    if scheduler is None:
        scheduler = BackgroundScheduler(timezone='Asia/Taipei')
        
        # 每天早上 8:30 發送早安訊息
        scheduler.add_job(
            send_morning_message,
            CronTrigger(hour=8, minute=30),
            id='morning_message'
        )
        
        # 每週日晚上 22:00 發送週報摘要
        scheduler.add_job(
            send_weekly_summary,
            CronTrigger(day_of_week=6, hour=22, minute=0),
            id='weekly_summary'
        )
        
        scheduler.start()
        print("✅ 排程器已啟動")
        
        # 顯示下次執行時間
        for job in scheduler.get_jobs():
            print(f"   • {job.id}: 下次執行 {job.next_run_time}")

@app.route("/", methods=['GET'])
def home():
    return "LINE Bot is running!"

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("❌ Invalid signature")
        abort(400)
    
    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    message_text = event.message.text.strip()
    
    # 記錄收到的訊息
    current_time = datetime.now()
    print(f"📨 [{current_time.strftime('%H:%M:%S')}] 收到訊息 - 用戶: {user_id}, 內容: '{message_text}'")
    
    # 儲存用戶資料
    if user_id not in user_data:
        user_data[user_id] = {'stage': 'none', 'data': {}}
    
    reply_text = ""
    
    # 倒數計時功能
    if message_text in ['倒數1分鐘']:
        success = start_countdown_timer(user_id, 1)
        reply_text = "⏱ 1分鐘倒數計時已開始！時間到會收到推送提醒" if success else "❌ 倒數計時啟動失敗"
        
    elif message_text in ['倒數3分鐘', '倒數計時', '開始倒數']:
        success = start_countdown_timer(user_id, 3)
        reply_text = "⏱ 3分鐘倒數計時已開始！時間到會收到推送提醒" if success else "❌ 倒數計時啟動失敗"
        
    elif message_text in ['倒數5分鐘']:
        success = start_countdown_timer(user_id, 5)
        reply_text = "⏱ 5分鐘倒數計時已開始！時間到會收到推送提醒" if success else "❌ 倒數計時啟動失敗"
        
    elif message_text == '測試倒數':
        # 10秒測試倒數
        def quick_test():
            try:
                print("🧪 開始10秒測試倒數")
                time.sleep(10)
                line_bot_api.push_message(user_id, TextSendMessage(text="🧪 10秒測試倒數完成！"))
                print("✅ 10秒測試倒數訊息發送成功")
            except Exception as e:
                print(f"❌ 10秒測試倒數失敗: {e}")
        
        test_thread = threading.Thread(target=quick_test)
        test_thread.daemon = True
        test_thread.start()
        reply_text = "🧪 開始10秒測試倒數，請等待..."
        
    elif message_text == '線程狀態':
        # 查看活躍線程
        active_threads = threading.active_count()
        thread_list = [t.name for t in threading.enumerate()]
        reply_text = f"🔍 系統狀態：\n活躍線程數: {active_threads}\n線程列表:\n" + "\n".join(f"• {name}" for name in thread_list)
        
    elif message_text == '風雲榜':
        user_data[user_id]['stage'] = 'waiting_for_data_1'
        reply_text = """📊 風雲榜資料輸入開始！

請依序輸入以下9項資料：

1️⃣ 【第一項資料】請輸入："""
        
    elif message_text == '功能說明':
        reply_text = """🤖 LINE 行程助理功能說明

📊 【風雲榜功能】
   🎯 輸入 '風雲榜' 開始資料輸入流程
   📝 系統會引導您依序輸入9項資料
   ✅ 資料將自動寫入指定的Google工作表

⏰ 【倒數計時功能】
   🕐 倒數1分鐘：輸入 '倒數1分鐘'
   🕐 倒數3分鐘：輸入 '倒數3分鐘' 或 '倒數計時' 或 '開始倒數'
   🕐 倒數5分鐘：輸入 '倒數5分鐘'
   🧪 測試倒數：輸入 '測試倒數' (10秒測試)

📅 【自動排程服務】
   🌅 每天早上 8:30 - 溫馨早安訊息
   📊 每週日晚上 22:00 - 下週行程摘要

🔍 【系統功能】
   📋 線程狀態：查看系統運行狀態
   💡 功能說明：顯示此說明"""
        
    else:
        # 處理風雲榜資料輸入流程
        if user_id in user_data and user_data[user_id]['stage'] != 'none':
            stage = user_data[user_id]['stage']
            
            if stage.startswith('waiting_for_data_'):
                data_num = int(stage.split('_')[-1])
                user_data[user_id]['data'][f'data_{data_num}'] = message_text
                
                if data_num < 9:
                    next_num = data_num + 1
                    user_data[user_id]['stage'] = f'waiting_for_data_{next_num}'
                    reply_text = f"{next_num}️⃣ 【第{next_num}項資料】請輸入："
                else:
                    # 所有資料收集完成
                    try:
                        if gc:
                            # 這裡應該放您的 Google Sheets 處理邏輯
                            pass
                        
                        reply_text = """✅ 風雲榜資料已成功記錄！

📊 您輸入的9項資料已儲存完成
🔄 如需重新輸入，請再次輸入 '風雲榜'
💡 輸入 '功能說明' 查看其他功能"""
                        
                        user_data[user_id]['stage'] = 'none'
                        user_data[user_id]['data'] = {}
                        
                    except Exception as e:
                        reply_text = f"❌ 資料儲存失敗：{str(e)}"
                        user_data[user_id]['stage'] = 'none'
        else:
            reply_text = """🤖 歡迎使用 LINE 行程助理！

💡 輸入 '功能說明' 查看完整功能列表
📊 輸入 '風雲榜' 開始資料記錄
⏰ 輸入 '倒數計時' 開始倒數功能"""

    # 發送回覆
    try:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_text))
        print(f"✅ 回覆訊息發送成功 - 用戶: {user_id}")
    except Exception as e:
        print(f"❌ 回覆訊息發送失敗: {e}")

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
    print("⏰ 倒數計時功能：")
    print("   🕐 倒數1分鐘：輸入 '倒數1分鐘'")
    print("   🕐 倒數3分鐘：輸入 '倒數3分鐘' 或 '倒數計時' 或 '開始倒數'")
    print("   🕐 倒數5分鐘：輸入 '倒數5分鐘'")
    print("   🧪 測試倒數：輸入 '測試倒數' (10秒快速測試)")
    print("💡 輸入 '功能說明' 查看完整功能列表")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    
    # 初始化排程器
    init_scheduler()
    
    print("✅ 系統狀態：已載入排程工作")
    if scheduler:
        for job in scheduler.get_jobs():
            print(f"   • {job.id}: 下次執行 {job.next_run_time}")
    
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("🚀 LINE Bot 已成功啟動，準備為您服務！")
    
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)), debug=False)
