@echo off
REM =====================================================================
REM ADIT — Chạy ADIT bằng một cú bấm đúp (Windows, không cần build).
REM
REM Cách dùng: bấm đúp file này trong thư mục scripts/ của ADIT
REM (hoặc chạy từ terminal: scripts\run_adit.bat). Script sẽ:
REM   1. Về đúng thư mục gốc của ADIT.
REM   2. Kiểm tra Python, Pillow, FFmpeg và báo rõ bằng tiếng Việt
REM      nếu thiếu cái gì (thay vì báo lỗi khó hiểu).
REM   3. Khởi động server ADIT trong một cửa sổ riêng.
REM   4. Chờ tới khi server trả lời ở http://127.0.0.1:8000 rồi mới
REM      mở trình duyệt (không đoán thời gian chờ cố định).
REM   5. Giữ cửa sổ này mở và dặn bạn đừng đóng cửa sổ server.
REM Để dừng ADIT: đóng cửa sổ "ADIT Server" hoặc bấm Ctrl+C trong đó.
REM =====================================================================
chcp 65001 >nul 2>&1
cd /d "%~dp0.."
echo [ADIT] Dang khoi dong ADIT...

REM --- 1. Tim Python ---------------------------------------------------
set "PY=python"
set "PYARGS="
where python >nul 2>&1
if errorlevel 1 (
    where py >nul 2>&1
    if errorlevel 1 (
        echo [LOI] Khong tim thay Python.
        echo Hay cai Python 3.10 tro len tu https://www.python.org/downloads/
        echo (khi cai nho tick "Add python.exe to PATH"), roi chay lai file nay.
        pause
        exit /b 1
    )
    set "PY=py"
    set "PYARGS=-3"
)
REM Neu co .venv thi dung Python trong .venv (uu tien hon Python he thong).
if exist ".venv\Scripts\python.exe" (
    set "PY=.venv\Scripts\python.exe"
    set "PYARGS="
)

REM --- 2. Kiem tra Pillow, thieu thi cai mot lan ------------------------
%PY% %PYARGS% -c "import PIL" >nul 2>&1
if errorlevel 1 (
    echo [ADIT] Chua co thu vien Pillow, dang cai dat (chi mot lan)...
    %PY% %PYARGS% -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [LOI] Cai dat thu vien that bai. Hay kiem tra mang roi chay lai.
        pause
        exit /b 1
    )
)

REM --- 3. Kiem tra FFmpeg -------------------------------------------------
where ffmpeg >nul 2>&1
if errorlevel 1 (
    if exist "ffmpeg.exe" (
        set "PATH=%CD%;%PATH%"
    ) else (
        echo [LOI] Khong tim thay FFmpeg.
        echo Hay cai FFmpeg va them vao PATH (kiem tra bang lenh ffmpeg -version),
        echo hoac dat file ffmpeg.exe ngay trong thu muc ADIT, roi chay lai.
        pause
        exit /b 1
    )
)

REM --- 4. Khoi dong server trong cua so rieng ----------------------------
echo [ADIT] Dang khoi dong server...
start "ADIT Server" %PY% %PYARGS% server.py

REM --- 5. Cho toi khi server tra loi, roi moi mo trinh duyet ------------
set /a TRY=0
:waitloop
powershell -NoProfile -Command "try { $null = Invoke-WebRequest -Uri 'http://127.0.0.1:8000/' -UseBasicParsing -TimeoutSec 2; exit 0 } catch { exit 1 }" >nul 2>&1
if not errorlevel 1 goto server_up
set /a TRY+=1
if %TRY% GEQ 30 goto server_timeout
timeout /t 1 /nobreak >nul
goto waitloop

:server_up
start http://127.0.0.1:8000
echo.
echo [ADIT] ADIT dang chay tai http://127.0.0.1:8000/
echo [ADIT] Server dang chay — dung dong cua so "ADIT Server".
echo [ADIT] De dung ADIT: dong cua so "ADIT Server" hoac bam Ctrl+C trong do.
echo [ADIT] Cua so nay co the de mo, khong can lam gi them.
pause
exit /b 0

:server_timeout
echo [LOI] Server khong phan hoi sau 30 giay.
echo Hay xem cua so "ADIT Server" co bao loi gi khong, roi chay lai file nay.
pause
exit /b 1
