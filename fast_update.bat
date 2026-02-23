@echo off
setlocal
cls

echo ========================================================
echo       🚀 High-Performance Local Update & Test
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
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ Python is not installed or not in PATH.
    pause
    exit /b 1
)
echo ✅ Dependencies OK.
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
pip install -q -r requirements.txt
if %errorlevel% neq 0 (
    echo ❌ Failed to install dependencies.
    pause
    exit /b 1
)
echo.

:: 4. Aggregate & Test
echo [4/5] Running Aggregator & Local Engine...
python aggregator.py && python local_test.py
if %errorlevel% neq 0 (
    echo ❌ Aggregation or Testing failed.
    pause
    exit /b 1
)
echo.

:: 5. Deploy
echo [5/5] Deploying Results...
if exist real_delay_passed.txt (
    if not exist tested_configs mkdir tested_configs
    move /Y real_delay_passed.txt tested_configs\fast_servers.txt >nul
    echo ✅ fast_servers.txt saved to 'tested_configs' folder.
) else (
    echo ⚠️ No results file found.
)

echo.
echo ========================================================
echo       ✅ Process Finished Successfully
echo ========================================================
pause
