@echo off
cd /d "C:\Users\Gustavo Henrique\social-monitor-2"

echo [%date% %time%] === Social Monitor start ===

call run_youtube.bat
echo [%date% %time%] YouTube done.

call run_facebook.bat
echo [%date% %time%] Facebook done.

call run_trends.bat
echo [%date% %time%] Trends done.

call run_tiktok.bat
echo [%date% %time%] TikTok WL done.

call run_tiktok_male.bat
echo [%date% %time%] TikTok Male done.

echo [%date% %time%] === All tasks complete ===
