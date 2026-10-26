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

## Giai đoạn sau nữa (chưa chốt)

Template, preset hiệu ứng lưu sẵn, keyframe, transition nâng cao
(xfade, blur/glow/glitch...), đồng bộ cloud/tài khoản — chỉ làm khi
Giai đoạn 1 và 2 đã ổn định và người dùng yêu cầu. Riêng thư viện
hiệu ứng/transition cầu kỳ đã được người dùng dặn hoãn lại: làm
CapCut thuần + AI trước, chưa cần hiệu ứng cầu kỳ.
