@echo off
REM ADIT — chạy script cài đặt Ollama (bấm đúp file này cũng được).
powershell -ExecutionPolicy Bypass -File "%~dp0setup_ollama_windows.ps1" %*
pause
