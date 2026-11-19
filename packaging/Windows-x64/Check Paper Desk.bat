@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist "runtime\python\python.exe" (
    echo The runtime is missing. Extract the complete Windows ZIP first.
    pause
    exit /b 1
)
"%~dp0runtime\python\python.exe" -E -s -B -X utf8 -u "%~dp0diagnose.py"
pause
endlocal
