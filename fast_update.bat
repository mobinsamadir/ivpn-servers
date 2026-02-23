@echo off
setlocal
chcp 65001 >nul
cls

echo ========================================================
echo       🚀 High-Performance Local Update ^& Test
echo ========================================================
echo.

:: 1. Dependency Check
echo [1/5] Checking System Dependencies...
git --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ Git is not installed or not in PATH.
    pause
    exit /b 1
)

:: Python Detection Strategy
python --version >nul 2>&1
if %errorlevel% equ 0 (
    set PYTHON_CMD=python
) else (
    py --version >nul 2>&1
    if %errorlevel% equ 0 (
        set PYTHON_CMD=py
    ) else (
        echo ❌ Python is not installed or not in PATH.
        pause
        exit /b 1
    )
)
echo ✅ Python found: %PYTHON_CMD%
echo.

:: 2. Sync
echo [2/5] Syncing with Repository...
git pull origin main
if %errorlevel% neq 0 (
    echo ⚠️ Git pull failed. Continuing with local files...
)
echo.

:: 3. Install
echo [3/5] Installing Python Dependencies...
%PYTHON_CMD% -m pip install -q -r requirements.txt
if %errorlevel% neq 0 (
    echo ❌ Failed to install dependencies.
    pause
    exit /b 1
)
echo.

:: 4. Aggregate & Test
echo [4/5] Running Local Engine...
%PYTHON_CMD% local_test.py
if %errorlevel% neq 0 (
    echo ❌ Local Engine failed.
    pause
    exit /b 1
)
echo.

:: 5. Deploy
echo [5/5] Deploying Results...

:: Capture SSID for Commit Message
set SSID=Unknown
for /f "tokens=2 delims=:" %%A in ('netsh wlan show interfaces ^| findstr "SSID" ^| findstr /v "BSSID"') do set SSID=%%A
if not "%SSID%"=="Unknown" set SSID=%SSID:~1%

if exist real_delay_passed.txt (
    if not exist tested_configs mkdir tested_configs
    move /Y real_delay_passed.txt tested_configs\fast_servers.txt >nul
    echo ✅ fast_servers.txt saved to 'tested_configs' folder.
) else (
    echo ⚠️ No results file found.
)

echo.
echo [Git Sync]
echo ☁️  Pushing results to GitHub...
if exist local_reports\*.txt git add local_reports\*.txt
if exist tested_configs\*.txt git add tested_configs\*.txt
git add README.md
git commit -m "🔄 Local Audit Sync: %DATE% %TIME% [SSID: %SSID%]"
git push origin main

echo.
echo ========================================================
echo       ✅ Process Finished Successfully
echo ========================================================
pause
