@echo off
echo Starting Local Test...
python local_test.py
if errorlevel 1 (
    echo.
    echo ❌ Test failed or script error.
) else (
    echo.
    echo ✅ Test finished.
)
pause
