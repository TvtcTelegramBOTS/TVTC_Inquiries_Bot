@echo off
cd /d "%~dp0"
echo ===============================
echo 🚀 رفع التحديثات إلى GitHub...
echo ===============================

echo.
echo 🔍 التغييرات الحالية:
echo -------------------------------
git status --short > temp_git_status.txt
type temp_git_status.txt
echo -------------------------------

:: حساب عدد الأسطر (عدد الملفات المعدّلة/المضافة/المحذوفة)
for /f %%A in ('find /v /c "" ^< temp_git_status.txt') do set fileCount=%%A
del temp_git_status.txt >nul 2>&1

echo 📊 عدد الملفات المتأثرة: %fileCount%
echo.

set /p confirm=هل تريد رفع هذه التغييرات إلى GitHub؟ (y/n): 
if /i "%confirm%"=="y" (
    echo.
    echo 🧱 إضافة الملفات المعدّلة...
    git add .

    for /f "tokens=1-4 delims=/ " %%a in ("%date%") do set commitdate=%%a-%%b-%%c
    for /f "tokens=1-2 delims=: " %%a in ("%time%") do set committime=%%a-%%b
    set commitmsg=Auto update on %commitdate%_%committime%

    echo 📝 إنشاء Commit: "%commitmsg%"
    git commit -m "%commitmsg%"

    echo.
    echo ⬆️ رفع التغييرات إلى GitHub...
    git push origin main

    echo.
    echo ✅ تم رفع جميع التغييرات إلى GitHub بنجاح!
) else (
    echo ❌ تم إلغاء عملية الرفع.
)

echo.
echo اضغط أي مفتاح للإغلاق...
pause >nul
