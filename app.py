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
                
            except Exception as e:
                print(f"❌ 設定1分鐘倒數失敗：{e}")
                reply = "❌ 倒數計時設定失敗，請稍後再試"
