@echo off
REM =====================================================================
REM ADIT — Đóng gói thành file .exe chạy trên Windows (PyInstaller).
REM
REM CHỈ CHẠY ĐƯỢC TRÊN WINDOWS. Không thể build file .exe Windows trên
REM máy Linux, và repo không kèm sẵn file .exe đã build.
REM
REM Cách dùng: bấm đúp file này trong thư mục scripts/ của ADIT
REM (hoặc chạy từ terminal: scripts\build_windows.bat). Script sẽ:
REM   1. Tạo/dùng .venv, cài requirements.txt và pyinstaller.
REM   2. Chạy: pyinstaller --clean --noconfirm adit.spec
REM   3. In ra thư mục kết quả: dist\ADIT\  (file chạy: ADIT.exe)
REM
REM Chạy file đã đóng gói: bấm đúp dist\ADIT\ADIT.exe — không cần cài
REM Python nữa. Nhưng vẫn cần FFmpeg: hoặc FFmpeg đã có trong PATH,
REM hoặc đặt ffmpeg.exe ngay cạnh ADIT.exe trong dist\ADIT\.
REM Để dừng app đã đóng gói: đóng cửa sổ của nó (hoặc Ctrl+C trong đó).
REM =====================================================================
chcp 65001 >nul 2>&1
cd /d "%~dp0.."
echo [ADIT] Dang dong goi ADIT thanh file .exe (PyInstaller)...

REM --- Python ------------------------------------------------------------
set "PY=python"
where python >nul 2>&1
if errorlevel 1 (
    where py >nul 2>&1
    if errorlevel 1 (
        echo [LOI] Khong tim thay Python. Hay cai Python 3.10 tro len truoc.
        pause
        exit /b 1
    )
    set "PY=py -3"
)

REM --- Venv + dependencies ----------------------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo [ADIT] Dang tao moi truong ao .venv...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo [LOI] Tao .venv that bai.
        pause
        exit /b 1
    )
)
call ".venv\Scripts\activate.bat"
if errorlevel 1 (
    echo [LOI] Khong kich hoat duoc .venv.
    pause
    exit /b 1
)
echo [ADIT] Dang cai requirements.txt va pyinstaller...
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
    echo [LOI] Cai dat that bai. Hay kiem tra mang roi chay lai.
    pause
    exit /b 1
)

REM --- Build ---------------------------------------------------------------
echo [ADIT] Dang chay pyinstaller adit.spec...
pyinstaller --clean --noconfirm adit.spec
if errorlevel 1 (
    echo [LOI] Build that bai. Hay xem log pyinstaller o tren.
    pause
    exit /b 1
)

echo.
echo [ADIT] Build xong!
echo [ADIT] File chay: dist\ADIT\ADIT.exe
echo [ADIT] Bam dup dist\ADIT\ADIT.exe de chay (khong can Python).
echo [ADIT] Luu y: van can FFmpeg — hoac co trong PATH, hoac dat
echo [ADIT] ffmpeg.exe ngay canh ADIT.exe trong dist\ADIT\.
pause
