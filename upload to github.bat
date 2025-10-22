@echo off
cd /d "%~dp0"
echo ===============================
echo 🚀 Uploading updates to GitHub...
echo ===============================

echo.
echo 🔍 Current changes:
echo -------------------------------
git status --short > temp_git_status.txt
type temp_git_status.txt
echo -------------------------------

:: Count how many files were modified/added/deleted
for /f %%A in ('find /v /c "" ^< temp_git_status.txt') do set fileCount=%%A
del temp_git_status.txt >nul 2>&1

echo 📊 Total affected files: %fileCount%
echo.

set /p confirm=Do you want to upload these changes to GitHub? (y/n): 
if /i "%confirm%"=="y" (
    echo.
    echo 🧱 Staging all modified files...
    git add .

    :: Generate a clean and safe commit message
    for /f "tokens=1-4 delims=/ " %%a in ("%date%") do set commitdate=%%a-%%b-%%c
    for /f "tokens=1-2 delims=: " %%a in ("%time%") do set committime=%%a-%%b
    set commitmsg=Auto update on %commitdate%_%committime%

    :: Fallback in case message is empty
    if "%commitmsg%"=="" set commitmsg=Auto update manual

    echo 📝 Creating Commit: "%commitmsg%"
    git commit -m "%commitmsg%"

    echo.
    echo ⬆️ Pushing changes to GitHub...
    git push origin main

    echo.
    echo ✅ All changes have been successfully uploaded to GitHub!
) else (
    echo ❌ Upload canceled.
)

echo.
echo Press any key to close...
pause >nul
