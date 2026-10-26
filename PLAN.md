# ADIT — Lộ trình

## Giai đoạn 1 — MVP chỉnh sửa thủ công (ĐÃ LÀM)

Trình chỉnh sửa kiểu CapCut ở các tính năng cơ bản: thư viện media,
timeline, cắt/tách/sắp xếp, chữ, hiệu ứng cơ bản (mờ dần, zoom, tốc
độ), âm lượng, nhạc nền, xuất video bằng FFmpeg. Chạy dạng web local,
chưa đóng gói desktop.

## Giai đoạn 2 — AI hỗ trợ theo yêu cầu (CHƯA LÀM, chỉ là kế hoạch)

- Khung chat AI trong app: người dùng gõ yêu cầu bằng tiếng Việt,
  AI sửa trực tiếp trên timeline, ví dụ đoạn nào xấu thì làm
  animation cho đẹp ngay trên đoạn đó.
- **Cùng một bộ quyền cho mọi nhà cung cấp AI.** Dù là Ollama local,
  Codex, Claude hay API trả phí khác, AI đều chỉ được: đọc timeline,
  đề xuất các thao tác timeline đã cho phép, và áp dụng sau khi đã
  qua kiểm chứng (không chồng clip trái quy tắc, không đọc quá cuối
  nguồn) — và luôn có undo về trạng thái trước đó. AI không được tự
  xóa file gốc, không chạy lệnh hệ thống, không truy cập ra ngoài
  thư mục dự án.
- Model trả phí thông minh hơn chỉ khác ở chỗ **hiểu ý người dùng
  nhanh hơn, ít hỏi lại hơn** — không phải ở quyền được cấp.
- Tiện ích AI kiểu CreatorUtils (tham khảo ý tưởng, không sao chép
  app): phiên âm local, tự chia chapter, tóm tắt video, gợi ý tiêu
  đề/mô tả/hashtag.
- Đóng gói desktop (Tauri/Electron) để thành app cài đặt được, thay
  vì chạy bằng lệnh `python server.py`.

## Giai đoạn sau nữa (chưa chốt)

Template, preset hiệu ứng lưu sẵn, keyframe, transition nâng cao,
đồng bộ cloud/tài khoản — chỉ làm khi Giai đoạn 1 và 2 đã ổn định và
người dùng yêu cầu.
