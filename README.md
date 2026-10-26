# ADIT — Trình chỉnh sửa video kiểu CapCut (MVP, Giai đoạn 1)

ADIT là một trình chỉnh sửa video chạy local, giao diện giống CapCut ở
các tính năng cơ bản: thư viện media, xem trước, bảng thuộc tính và
dải timeline ở phía dưới. **Bản này là MVP Giai đoạn 1: chỉ có chỉnh
sửa thủ công. Chưa có AI.** Tab AI trong giao diện chỉ là một ghi chú
"Giai đoạn 2", không gọi bất kỳ model nào, không dùng API key nào.

## ADIT làm được gì (MVP)

- **Thư viện media:** tải lên video, ảnh, nhạc vào thư mục của dự án
  (file gốc của bạn không bao giờ bị sửa hay di chuyển). Ảnh thu nhỏ
  cho video (cắt 1 khung hình bằng FFmpeg) và ảnh (Pillow).
- **Timeline:** thêm clip vào track, di chuyển clip (đổi track / vị trí
  bắt đầu), sắp xếp lại các clip trên một track, cắt đầu nguồn
  (trim), tách clip tại một vị trí, xóa clip. Tổng thời lượng được
  tính từ model timeline, không đoán.
- **Chữ:** thêm/sửa chữ với nội dung, cỡ chữ, màu và vị trí
  (giữa/trên/dưới); chữ được vẽ thành ảnh PNG trong suốt bằng Pillow
  rồi phủ lên video khi xuất.
- **Hiệu ứng từng clip:** mờ dần vào/ra/cả hai, zoom vào/ra, tốc độ
  0.5–2.0. Tất cả đều ảnh hưởng thật đến file xuất bằng FFmpeg, không
  chỉ là nhãn hiển thị.
- **Âm thanh:** âm lượng từng clip, tắt tiếng từng clip, nhạc nền
  riêng với âm lượng tối đa 0.30.
- **Xuất video:** FFmpeg render ra MP4 H.264/AAC, mặc định dọc
  1080×1920 30fps, có thêm bản nháp 540×960 cho nhanh. Xuất thất bại
  sẽ báo rõ lỗi FFmpeg, không bao giờ báo thành công khi không có file.
- **Lưu/mở dự án:** dự án lưu thành `projects/default/project.json`,
  mở lại là xuất tiếp được từ đúng timeline đó.

## ADIT chưa làm được (nói rõ để khỏi kỳ vọng quá)

Đây là MVP, **không phải bản sao CapCut đầy đủ**: không có template,
không có kho hiệu ứng, không có keyframe, không có masking nhiều lớp,
không có transition ngoài hiệu ứng mờ dần, không có đồng bộ cloud,
không có tài khoản. Clip video/ảnh/chữ trên cùng một track không được
chồng lên nhau (clip nhạc thì được trộn nên có thể chồng). Chưa có
xem trước trực tiếp trên timeline: trình phát sẽ phát bản xuất gần
nhất. Bản MVP chạy dạng web local, **chưa đóng gói thành app desktop
(Tauri/Electron)** — đó là việc của giai đoạn sau.

## Chạy trên Windows

Yêu cầu: Python 3.10 trở lên, FFmpeg đã thêm vào PATH (kiểm tra bằng
`ffmpeg -version` trong PowerShell).

```powershell
cd D:\ADIT
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python server.py
```

Sau đó mở trình duyệt tại http://127.0.0.1:8000

- Tải file lên ở cột trái, bấm "Thêm vào timeline".
- Bấm vào một clip trên timeline để sửa thuộc tính ở cột phải.
- Bấm "Xuất bản nháp" để xem nhanh, "Xuất video" để xuất bản chính
  1080×1920. File xuất nằm trong `projects\default\output\`.
- Muốn ghi đè file xuất cũ thì tick "Ghi đè file xuất cũ", nếu không
  app sẽ báo file đã tồn tại thay vì lặng lẽ ghi đè.

Chạy trên Linux/macOS cũng tương tự, chỉ khác lệnh kích hoạt venv
(`source .venv/bin/activate`).

## Chạy test

```bash
python -m py_compile timeline.py media.py render.py server.py
python -m unittest discover -s tests -v
```

Test render dùng media mẫu do FFmpeg/Pillow tự tạo và kiểm chứng bằng
FFprobe ở kích thước nháp nhỏ, không render 1080×1920 trong test.

## Cấu trúc thư mục

```text
server.py            # server HTTP chuẩn thư viện Python, API JSON + phục vụ UI
timeline.py          # model timeline: thêm/sửa/xóa/tách/sắp xếp, kiểm chứng
media.py             # nhập media, thăm dò FFprobe, ảnh thu nhỏ
render.py            # xuất video bằng FFmpeg (track chính, overlay, trộn nhạc)
static/              # giao diện: xem trước trên, thuộc tính phải, timeline dưới
tests/               # test model timeline + test render thật bằng FFmpeg
projects/default/    # dự án đang mở: media/, project.json, output/
PLAN.md              # lộ trình Giai đoạn 2 (AI) — chưa làm
```

## An toàn và bản quyền

- App không sửa file gốc, không xóa file của bạn, không gọi mạng ra
  ngoài trừ trình duyệt của chính bạn mở trang local.
- Chỉ dùng media mà bạn có quyền sử dụng. App không tự tải nhạc, ảnh
  hay video từ mạng về.
