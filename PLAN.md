# ADIT — Lộ trình

## Giai đoạn 1 — MVP chỉnh sửa thủ công (ĐÃ LÀM)

Trình chỉnh sửa kiểu CapCut ở các tính năng cơ bản: thư viện media,
timeline, cắt/tách/sắp xếp, chữ, hiệu ứng cơ bản (mờ dần, zoom, tốc
độ), âm lượng, nhạc nền, xuất video bằng FFmpeg. Chạy dạng web local,
chưa đóng gói desktop.

## Giai đoạn 2 — AI hỗ trợ theo yêu cầu (ĐÃ LÀM, trừ kiểm chứng API trả phí thật)

- Khung chat AI trong app: người dùng gõ yêu cầu bằng tiếng Việt,
  AI sửa trực tiếp trên timeline (mặc định xem đề xuất trước rồi bấm
  "Áp dụng"; tick "Tự áp dụng ngay" thì kế hoạch đã kiểm chứng áp
  thẳng lên timeline, vẫn hoàn tác được).
- **Cùng một bộ quyền cho mọi nhà cung cấp AI.** Dù là Ollama local,
  Codex, Claude hay API trả phí khác, AI đều chỉ được: đọc timeline,
  đề xuất các thao tác timeline đã cho phép, và áp dụng sau khi đã
  qua kiểm chứng (không chồng clip trái quy tắc, không đọc quá cuối
  nguồn) — và luôn có undo về trạng thái trước đó. AI không được tự
  xóa file gốc, không chạy lệnh hệ thống, không truy cập ra ngoài
  thư mục dự án.
- Model trả phí thông minh hơn chỉ khác ở chỗ **hiểu ý người dùng
  nhanh hơn, ít hỏi lại hơn** — không phải ở quyền được cấp.
- Ollama là mặc định, miễn phí: script `scripts/setup_ollama_windows.ps1`
  cài Ollama (qua winget nếu có, nếu không chỉ in hướng dẫn) và tải
  model mặc định qwen2.5:3b-instruct sau khi người dùng xác nhận.
  Binary/model không đóng gói vào repo. Trạng thái Ollama hiện rõ
  trong giao diện qua GET /api/ai/status.
- Quản lý model: liệt kê/tải/xóa model Ollama và Whisper (Whisper chỉ
  trong thư mục cache an toàn, cần xác nhận khi xóa, kiểm chứng sau
  khi tải/xóa). Phiên âm local bằng faster-whisper (tùy chọn, mặc định
  tiny), lưu transcript.txt/json trong dự án.
- Tiện ích AI kiểu CreatorUtils (tham khảo ý tưởng, không sao chép
  app): từ bản ghi tạo chapter, tóm tắt video, gợi ý tiêu đề/mô tả/
  hashtag — chỉ tạo chữ gợi ý, không tự sửa timeline.
- Chưa kiểm chứng: đường API trả phí thật (OpenAI/Anthropic) viết xong
  code nhưng chưa chạy với key thật; cần key của người dùng.
- Chưa làm: đóng gói desktop (Tauri/Electron) để thành app cài đặt
  được, thay vì chạy bằng lệnh `python server.py`.

## Thao tác mượt kiểu CapCut (ĐÃ LÀM, sau Giai đoạn 2)

- Kéo clip trên timeline (lưu một lần khi thả chuột, chồng clip thì
  bị từ chối), thu phóng timeline, bấm thước để di chuyển playhead
  với xem trước đại diện (proxy: file nguồn của clip tại vị trí đó,
  hoặc khung đen cho khoảng trống) — chưa phải render timeline trực
  tiếp bằng GPU.
- Waveform cho clip nhạc/video có tiếng, tạo một lần bằng FFmpeg và
  cache cạnh file media; lỗi waveform không chặn timeline.
- Xem trước nhanh bằng bản nháp 540×960, tái dùng thumbnail đã tạo.
- Chỉnh sửa toàn cục bằng FFmpeg thật, không phải AI: eq làm màu đẹp
  hơn, loudnorm ổn định âm lượng, unsharp làm nét hơn; có nút đặt lại.
  Các tính năng cần model AI (retouch face, giọng rõ hơn bằng AI,
  video nét hơn bằng AI, gợi ý thông minh, AI clipper) vẫn chưa có
  và chỉ được ghi chú là giai đoạn sau.
- Chưa làm: transition/ hiệu ứng cầu kỳ (đã dặn hoãn), render
  timeline trực tiếp bằng GPU.

## Chạy như app Windows (ĐÃ LÀM, trừ kiểm chứng trên Windows thật)

- Launcher bấm đúp: `scripts/run_adit.bat` và `scripts/run_adit.ps1`
  kiểm tra Python / Pillow / FFmpeg, dùng `.venv` nếu có, khởi động
  server trong cửa sổ riêng, chờ server trả lời rồi mới mở trình
  duyệt, và giữ cửa sổ mở — không còn cảm giác "đơ" vì server giữ
  dấu nhắc lệnh (đó là hành vi bình thường, README giải thích rõ).
- Server: cờ `--open-browser`, thông báo tiếng Việt khi cổng đã được
  dùng, cảnh báo khi thiếu FFmpeg, tắt sạch bằng Ctrl+C. Khi chạy
  đóng gói (sys.frozen), server dùng thư mục chứa file .exe làm gốc
  để tìm static/ và projects/.
- Đóng gói PyInstaller: `adit.spec` (one-folder, gồm static/ và
  scripts/ làm data, không gồm test hay nội dung projects/) và
  `scripts/build_windows.bat` (tạo .venv, cài pyinstaller, build ra
  `dist/ADIT/ADIT.exe`, không cần Python để chạy exe). FFmpeg vẫn
  cần (PATH hoặc ffmpeg.exe cạnh exe). File .exe **không thể build
  trên máy Linux** và repo không kèm file .exe đã build — phải build
  trên Windows. Chưa kiểm chứng: launcher và file .exe chưa được chạy
  thử trên Windows thật; người dùng cần kiểm tra: bấm đúp run_adit.bat
  → trình duyệt mở → editor tải được → dừng bằng cách đóng cửa sổ.
- Chưa làm: đóng gói Tauri/Electron (lựa chọn riêng ở giai đoạn sau).

## Giai đoạn sau nữa (chưa chốt)

Template, preset hiệu ứng lưu sẵn, keyframe, transition nâng cao
(xfade, blur/glow/glitch...), đồng bộ cloud/tài khoản — chỉ làm khi
Giai đoạn 1 và 2 đã ổn định và người dùng yêu cầu. Riêng thư viện
hiệu ứng/transition cầu kỳ đã được người dùng dặn hoãn lại: làm
CapCut thuần + AI trước, chưa cần hiệu ứng cầu kỳ.
