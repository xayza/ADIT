# =====================================================================
# ADIT — Chạy ADIT bằng PowerShell (tương đương scripts/run_adit.bat).
#
# Cách dùng (chọn một trong hai):
#   - Chuột phải vào file này -> "Run with PowerShell", hoặc
#   - Từ terminal trong thư mục ADIT:
#       powershell -ExecutionPolicy Bypass -File scripts\run_adit.ps1
#
# Script sẽ: kiểm tra Python, Pillow, FFmpeg (báo rõ bằng tiếng Việt
# nếu thiếu), khởi động server trong một cửa sổ riêng, chờ tới khi
# server trả lời ở http://127.0.0.1:8000 rồi mới mở trình duyệt.
# Để dừng ADIT: đóng cửa sổ server hoặc bấm Ctrl+C trong đó.
# =====================================================================
Set-Location (Split-Path -Parent $PSScriptRoot)
Write-Host "[ADIT] Dang khoi dong ADIT..."

# --- 1. Tìm Python ------------------------------------------------------
$py = $null
$pyArgs = @()
if (Get-Command python -ErrorAction SilentlyContinue) { $py = "python" }
elseif (Get-Command py -ErrorAction SilentlyContinue) { $py = "py"; $pyArgs = @("-3") }
if (-not $py) {
    Write-Host "[LOI] Khong tim thay Python."
    Write-Host "Hay cai Python 3.10 tro len tu https://www.python.org/downloads/ (khi cai nho tick 'Add python.exe to PATH'), roi chay lai script nay."
    Read-Host "Nhan Enter de thoat"
    exit 1
}
# Nếu có .venv thì dùng Python trong .venv (ưu tiên hơn Python hệ thống).
if (Test-Path ".venv\Scripts\python.exe") { $py = ".venv\Scripts\python.exe"; $pyArgs = @() }

# --- 2. Kiểm tra Pillow, thiếu thì cài một lần ---------------------------
& $py @pyArgs -c "import PIL" > $null 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "[ADIT] Chua co thu vien Pillow, dang cai dat (chi mot lan)..."
    & $py @pyArgs -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[LOI] Cai dat thu vien that bai. Hay kiem tra mang roi chay lai."
        Read-Host "Nhan Enter de thoat"
        exit 1
    }
}

# --- 3. Kiểm tra FFmpeg ---------------------------------------------------
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    if (Test-Path "ffmpeg.exe") { $env:PATH = "$PWD;$env:PATH" }
    else {
        Write-Host "[LOI] Khong tim thay FFmpeg."
        Write-Host "Hay cai FFmpeg va them vao PATH (kiem tra bang lenh ffmpeg -version), hoac dat file ffmpeg.exe ngay trong thu muc ADIT, roi chay lai."
        Read-Host "Nhan Enter de thoat"
        exit 1
    }
}

# --- 4. Khởi động server trong cửa sổ riêng ------------------------------
Write-Host "[ADIT] Dang khoi dong server..."
Start-Process -FilePath $py -ArgumentList (@pyArgs + @("server.py")) -WorkingDirectory $PWD

# --- 5. Chờ tới khi server trả lời, rồi mới mở trình duyệt --------------
$up = $false
for ($i = 0; $i -lt 30; $i++) {
    try {
        $null = Invoke-WebRequest -Uri "http://127.0.0.1:8000/" -UseBasicParsing -TimeoutSec 2
        $up = $true
        break
    } catch { Start-Sleep -Seconds 1 }
}
if (-not $up) {
    Write-Host "[LOI] Server khong phan hoi sau 30 giay."
    Write-Host "Hay xem cua so server co bao loi gi khong, roi chay lai script nay."
    Read-Host "Nhan Enter de thoat"
    exit 1
}
Start-Process "http://127.0.0.1:8000"
Write-Host ""
Write-Host "[ADIT] ADIT dang chay tai http://127.0.0.1:8000/"
Write-Host "[ADIT] Server dang chay — dung dong cua so server."
Write-Host "[ADIT] De dung ADIT: dong cua so server hoac bam Ctrl+C trong do."
Read-Host "Nhan Enter de dong cua so nay (server van chay trong cua so rieng)"
