# 修復後的倒數提醒函數
def send_countdown_reminder(target_id, minutes):
    """發送倒數提醒訊息"""
    try:
        if minutes == 1:
            message = "⏰ 時間到！1分鐘倒數計時結束 🔔"
        else:
            message = f"⏰ 時間到！{minutes}分鐘倒數計時結束"
        
        line_bot_api.push_message(target_id, TextSendMessage(text=message))
        print(f"✅ {minutes}分鐘倒數提醒已發送給：{target_id}")
    except Exception as e:
        print(f"❌ 推播{minutes}分鐘倒數提醒失敗：{e}")
        print(f"目標ID: {target_id}")

# 修復倒數計時設定部分 - 以1分鐘為例
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
        
        # 注意：這裡移除了 is_group 參數，只傳遞 target_id 和 minutes
        scheduler.add_job(
            send_countdown_reminder,
            trigger="date",
            run_date=countdown_time,
            args=[target_id, 1],  # 只傳遞兩個參數
            id=job_id
        )
        
        print(f"✅ 已設定1分鐘倒數提醒，執行時間：{countdown_time.strftime('%Y/%m/%d %H:%M:%S')}")
        print(f"📋 排程ID：{job_id}")
        print(f"🎯 目標用戶/群組：{target_id} ({'群組' if is_group else '個人'})")
        
    except Exception as e:
        print(f"❌ 設定1分鐘倒數失敗：{e}")
        reply = "❌ 倒數計時設定失敗，請稍後再試"

# 類似地修復3分鐘和5分鐘的倒數計時
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
            args=[target_id, 3],  # 只傳遞兩個參數
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
            args=[target_id, 5],  # 只傳遞兩個參數
            id=job_id
        )
        print(f"✅ 已設定5分鐘倒數提醒：{countdown_time.strftime('%Y/%m/%d %H:%M:%S')}")
    except Exception as e:
        print(f"❌ 設定5分鐘倒數失敗：{e}")
        reply = "❌ 倒數計時設定失敗，請稍後再試"
