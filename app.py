# 修正 send_countdown_reminder 函數
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

# 修正倒數1分鐘的處理邏輯（在 handle_message 函數中）
elif reply_type == "countdown_1":
    try:
        # 立即回應用戶
        reply = (
            "⏰ 1分鐘倒數計時開始！\n"
            "━━━━━━━━━━━━━━━━\n"
            "🕐 計時器已啟動\n"
            "📢 1分鐘後我會提醒您時間到了"
        )
        
        # 直接添加排程任務，1分鐘後執行
        countdown_time = datetime.now() + timedelta(minutes=1)
        job_id = f"countdown_1_{user_id}_{int(datetime.now().timestamp())}"
        
        scheduler.add_job(
            send_countdown_reminder,
            trigger="date",
            run_date=countdown_time,
            args=[user_id, 1],
            id=job_id
        )
        
        print(f"✅ 已設定1分鐘倒數提醒，執行時間：{countdown_time.strftime('%Y/%m/%d %H:%M:%S')}")
        print(f"📋 排程ID：{job_id}")
        print(f"🎯 目標用戶/群組：{user_id}")
        
    except Exception as e:
        print(f"❌ 設定1分鐘倒數失敗：{e}")
        reply = "❌ 倒數計時設定失敗，請稍後再試"
