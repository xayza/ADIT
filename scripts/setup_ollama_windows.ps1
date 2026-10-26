# ADIT — Cài đặt Ollama local trên Windows (chạy một lần, miễn phí).
#
# Script này KHÔNG tự ý tải gì khi bạn chưa đồng ý:
#  - Nếu máy chưa có `ollama`, script thử cài bằng winget (nếu có winget);
#    nếu không có winget, script chỉ in hướng dẫn tải từ trang chính thức
#    của Ollama rồi dừng lại, không tự tải file cài đặt.
#  - Trước khi tải model, script hỏi bạn xác nhận, vì model nặng khoảng 2 GB.
#  - Script không đóng gói binary hay model vào repo ADIT (quá nặng).
#
# Cách chạy (PowerShell, trong thư mục ADIT):
#   powershell -ExecutionPolicy Bypass -File scripts\setup_ollama_windows.ps1
# Hoặc bấm đúp file scripts\setup_ollama_windows.bat
#
# Sau khi xong: Ollama chạy nền, mở ADIT (python server.py) là AI
# miễn phí dùng được ngay, không cần API key.

param(
    [string]$Model = "qwen2.5:3b-instruct"
)

$ErrorActionPreference = "Stop"

Write-Host "ADIT — Cài đặt Ollama local"
Write-Host "Model mặc định: $Model (nhỏ, hợp máy yếu, khoảng 2 GB)."
Write-Host ""

# 1. Kiểm tra ollama đã có chưa.
$ollama = Get-Command ollama -ErrorAction SilentlyContinue
if (-not $ollama) {
    Write-Host "Chưa thấy lệnh 'ollama' trên máy."
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        Write-Host "Đang cài Ollama bằng winget..."
        winget install Ollama.Ollama --accept-source-agreements --accept-package-agreements
        # Cập nhật PATH trong phiên này từ PATH của máy.
        $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
            [System.Environment]::GetEnvironmentVariable("Path", "User")
        $ollama = Get-Command ollama -ErrorAction SilentlyContinue
    }
    if (-not $ollama) {
        Write-Host ""
        Write-Host "Không cài tự động được. Bạn làm thủ công 2 bước sau rồi chạy lại script này:"
        Write-Host "  1. Tải Ollama tại https://ollama.com/download (chọn Windows) và cài đặt."
        Write-Host "  2. Đóng rồi mở lại PowerShell, chạy lại script này."
        exit 1
    }
}

Write-Host "Đã có Ollama: $(ollama --version)"
Write-Host ""

# 2. Hỏi xác nhận trước khi tải model (khoảng 2 GB).
$answer = Read-Host "Tải model $Model về máy (khoảng 2 GB)? Nhập Y để đồng ý, phím khác để dừng"
if ($answer -notmatch '^[Yy]') {
    Write-Host "Đã dừng theo ý bạn. Khi nào muốn tải thì chạy lại script này."
    exit 0
}

ollama pull $Model
Write-Host ""
Write-Host "Model đã có trong máy:"
ollama list
Write-Host ""

# 3. Kiểm tra nhanh bằng một câu hỏi nhỏ.
Write-Host "Kiểm tra nhanh Ollama..."
$test = ollama run $Model "Tra loi dung mot tu: OK"
Write-Host "Ollama trả về: $test"
Write-Host ""
Write-Host "Xong! Nếu Ollama chưa chạy nền, chạy thêm lệnh: ollama serve"
Write-Host "Sau đó mở ADIT (python server.py), chọn nhà cung cấp Ollama là AI dùng được ngay, miễn phí."
