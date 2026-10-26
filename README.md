# ADIT — Trình chỉnh sửa video kiểu CapCut (Giai đoạn 1 + AI Giai đoạn 2)

ADIT là một trình chỉnh sửa video chạy local, giao diện giống CapCut ở
các tính năng cơ bản: thư viện media, xem trước, bảng thuộc tính và
dải timeline ở phía dưới. **Giai đoạn 1 là chỉnh sửa thủ công.
Giai đoạn 2 đã làm xong: AI theo yêu cầu, sửa trực tiếp trên timeline
khi bạn yêu cầu, kèm Quản lý model và Phiên âm local.** Chưa có
hiệu ứng/transition cầu kỳ — phần đó người dùng đã dặn để sau.

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

## Thao tác mượt kiểu CapCut (mới)

- **Kéo clip trên timeline:** bấm giữ một clip và kéo ngang để đổi
  vị trí bắt đầu trên cùng track, trong lúc kéo có hiển thị thời gian
  trực tiếp; chỉ khi thả chuột mới lưu một lần qua API. Kéo vào vị trí
  chồng clip khác thì server từ chối và clip trở lại chỗ cũ.
- **Thu phóng timeline:** thanh trượt và nút +/− đổi số pixel/giây
  (10–200) cho dải timeline mà không tải lại trang.
- **Bấm thước thời gian để di chuyển playhead:** playhead và mốc
  thời gian hiện rõ. Khung xem trước lúc này là **xem trước đại diện
  (proxy), chưa phải bản render timeline**: nếu vị trí đó có clip
  video/ảnh thì hiện đúng file nguồn của clip đó ở thời gian nguồn
  tương ứng; nếu là khoảng trống thì hiện khung đen kèm mốc thời gian.
  Muốn xem đúng timeline đã ghép thì bấm "Xem trước nhanh".
- **Sửa thuộc tính và xóa clip tại chỗ:** mọi thao tác gọi API JSON và
  cập nhật giao diện tại chỗ, không tải lại trang.
- **Sóng âm (waveform):** clip nhạc và clip video có tiếng sẽ hiện sóng
  âm trong khối timeline. Sóng được tạo một lần bằng FFmpeg (giải mã
  PCM mono rồi tính đỉnh theo từng khoảng) và lưu cache cạnh file
  media (`<tên>.waveform.json`), lần sau dùng lại cache nếu file chưa
  đổi. Nếu tạo sóng thất bại thì khối timeline vẫn hiện bình thường,
  không có sóng, và không chặn việc chỉnh sửa.
- **Xem trước nhanh:** nút "Xem trước nhanh" render bản nháp 540×960
  (preset veryfast) và phát ngay trong trình phát, kèm trạng thái
  "Đang render bản nháp…". Đường xuất video chính không thay đổi.
  Ảnh thu nhỏ đã tạo cũng được tái dùng, không tạo lại mỗi lần mở.
- **Chỉnh sửa toàn cục (thật, không phải AI):** ở bảng bên phải, lưu
  rồi áp dụng khi xuất video: "Làm màu đẹp hơn" (eq:
  contrast=1.08, brightness=0.03, saturation=1.12), "Âm lượng ổn định"
  (loudnorm một lần: I=-16, TP=-1.5, LRA=11 trên bản mix cuối),
  "Video nét hơn" (unsharp=5:5:0.6:5:5:0.0, không phải AI). Có nút đặt
  lại về mặc định, và kết quả xuất ghi rõ chỉnh toàn cục nào đã áp.
  Các tính năng cần model AI như Retouch face, làm giọng rõ hơn bằng
  AI, làm video nét hơn bằng AI, gợi ý thông minh, AI clipper thì
  **chưa có** và chỉ được ghi chú là giai đoạn sau, không có nút nào
  giả vờ chạy chúng.

## AI — Ollama local miễn phí là mặc định

ADIT **không đóng gói binary Ollama hay model vào repo** (quá nặng).
Thay vào đó, app đi kèm script cài đặt:

1. Chạy một lần trên Windows (PowerShell, trong thư mục ADIT):
   `powershell -ExecutionPolicy Bypass -File scripts\setup_ollama_windows.ps1`
   (hoặc bấm đúp `scripts\setup_ollama_windows.bat`).
   Script kiểm tra đã có `ollama` chưa, nếu chưa thì cài bằng winget
   khi có winget, nếu không có winget thì chỉ in hướng dẫn tải từ
   https://ollama.com/download rồi dừng — không tự tải lén. Trước khi
   tải model, script hỏi bạn xác nhận, vì model nặng khoảng 2 GB.
2. Model mặc định: **qwen2.5:3b-instruct** (nhỏ, hợp máy yếu).
   Sau khi tải xong, script kiểm tra bằng `ollama list` và một câu hỏi thử.
3. Nếu Ollama chưa chạy nền, chạy thêm `ollama serve`, rồi mở ADIT.
   Trong giao diện, dòng trạng thái AI sẽ báo "Ollama local đã sẵn sàng"
   hay "chưa kết nối được" — bạn luôn biết AI miễn phí có dùng được không.
   Không cần API key cho đường này.

## AI — kết nối AI trả phí của riêng bạn để hiểu ý nhanh hơn

Nếu muốn chất lượng hiểu ý tốt hơn, bạn tự kết nối AI trả phí của mình:
trong bảng AI, chọn nhà cung cấp OpenAI tương thích hoặc Anthropic,
nhập tên model, base URL (nếu khác mặc định) và API key — hoặc đặt biến
môi trường `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` trước khi chạy server.
Key chỉ dùng trong phiên làm việc đó, **không bao giờ được ghi vào file
repo, project.json hay log** (log AI ở `projects/default/ai.log` đã lược
key). **Mọi nhà cung cấp đều có cùng một bộ quyền**: AI chỉ được đề
xuất các thao tác timeline trong danh sách cho phép (cắt, tách, xóa,
di chuyển, sắp xếp lại, tốc độ, âm lượng, chữ, mờ dần, nhạc nền), mọi
đề xuất đều qua kiểm chứng của server, và luôn hoàn tác được. Model
trả phí thông minh hơn chỉ khác ở chỗ hiểu ý bạn nhanh hơn, ít hỏi lại
hơn — không phải ở quyền được cấp.

Cách dùng AI sửa timeline: chọn một clip trên timeline (không bắt buộc),
gõ yêu cầu bằng tiếng Việt, bấm "Hỏi AI". AI trả về danh sách thao
tác bằng tiếng Việt để bạn xem trước. Mặc định **không áp dụng gì cho
tới khi bạn bấm "Áp dụng"**. Nếu bạn tick "Tự áp dụng ngay khi AI trả
về" thì kế hoạch đã qua kiểm chứng sẽ áp dụng thẳng lên timeline —
đó là cách "AI edit trực tiếp trên đó" hoạt động, và vẫn hoàn tác được
bằng nút "Hoàn tác" (server lưu bản sao `project.json.bak` trước khi áp).
Nếu AI lỗi (không có Ollama, thiếu key, model trả JSON sai), giao diện
báo rõ lỗi, không bao giờ báo thành công giả hay áp dụng nửa vời:
một kế hoạch có thao tác không hợp lệ sẽ bị từ chối toàn bộ.

Về riêng tư: với Ollama local, mọi thứ ở lại trên máy bạn. Với API trả
phí, chỉ bản tóm tắt timeline (không phải file media) và câu lệnh của
bạn được gửi tới nhà cung cấp bạn đã chọn.

## Quản lý model + Phiên âm local

Bảng "Quản lý model AI + Phiên âm local" trong giao diện:

- **Danh sách model:** model Ollama (qua API `/api/tags` khi Ollama chạy)
  và model Whisper (chỉ các thư mục faster-whisper trong thư mục cache
  Hugging Face; các model khác trong cùng cache, ví dụ voice Piper, sẽ
  không hiện và không xóa được từ ADIT). Hiển thị tên, nguồn và dung
  lượng khi có.
- **Tải model:** Ollama qua `ollama pull <tên>` (tên chỉ nhận chữ, số,
  chấm, gạch ngang, gạch dưới, gạch chéo và tag sau dấu hai chấm; tên lạ
  bị từ chối), Whisper qua faster-whisper (chỉ các cỡ tiny/base/small/
  medium/large-v3...). Thành công chỉ được báo sau khi kiểm chứng model
  đã thực sự xuất hiện trong danh sách.
- **Xóa model:** Ollama qua `ollama delete`, Whisper chỉ xóa thư mục
  trong thư mục cache an toàn, cả hai đều cần tick ô xác nhận trong giao
  diện và chỉ áp dụng cho model đã liệt kê. Xóa xong cũng kiểm chứng
  model đã thực sự biến mất.
- **Phiên âm local:** chọn một file video/nhạc trong dự án, chọn model
  Whisper (mặc định tiny cho máy yếu), bấm "Phiên âm local". Phiên âm
  chạy hoàn toàn local bằng faster-whisper sau khi đã tải model, không
  cần mạng cho bước này, và lưu `projects/default/transcript.txt` +
  `transcript.json` (kèm timestamp từng đoạn), không sửa file gốc.
  Nếu chưa cài faster-whisper hoặc chưa tải model Whisper, giao diện báo
  rõ bước tiếp theo (cài từ requirements-optional.txt rồi tải model),
  không bao giờ tạo bản ghi giả.
- **Trợ giúp từ bản ghi (kiểu CreatorUtils, tham khảo ý tưởng, không sao
  chép app):** từ bản ghi đã có, dùng AI đã chọn (mặc định Ollama local)
  để tạo chapter theo thời gian, tóm tắt video, và gợi ý tiêu đề / mô tả
  / hashtag. Các trợ giúp này **chỉ tạo chữ gợi ý để bạn sao chép và sửa**,
  không tự sửa timeline.

## ADIT chưa làm được (nói rõ để khỏi kỳ vọng quá)

Đây là MVP, **không phải bản sao CapCut đầy đủ**: không có template,
không có kho hiệu ứng, không có keyframe, không có masking nhiều lớp,
không có transition ngoài hiệu ứng mờ dần, không có đồng bộ cloud,
không có tài khoản. Clip video/ảnh/chữ trên cùng một track không được
chồng lên nhau (clip nhạc thì được trộn nên có thể chồng). Chưa có
render timeline trực tiếp bằng GPU: trình phát phát bản xuất gần nhất,
còn khi bấm thước thời gian thì chỉ hiện khung hình đại diện của clip
tại vị trí đó (xem mục "Thao tác mượt" ở trên). Bản này chạy dạng web local, **chưa đóng gói thành app desktop
(Tauri/Electron)** — đó là việc của giai đoạn sau. Hiệu ứng/transition
cầu kỳ (xfade, blur/glow/glitch...) đã được người dùng dặn để sau, chưa
làm trong bản này. Đường API trả phí thật (OpenAI/Anthropic) đã viết xong
code nhưng **chưa được kiểm chứng với key thật** — kiểm chứng thật cần
key của người dùng và chỉ nên làm trên máy của người dùng.

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
python -m py_compile timeline.py media.py render.py server.py ai_service.py model_service.py tests/test_smooth.py
python -m unittest discover -s tests -v
```

Test render dùng media mẫu do FFmpeg/Pillow tự tạo và kiểm chứng bằng
FFprobe ở kích thước nháp nhỏ, không render 1080×1920 trong test.

## Cấu trúc thư mục

```text
server.py            # server HTTP chuẩn thư viện Python, API JSON + phục vụ UI
timeline.py          # model timeline: thêm/sửa/xóa/tách/sắp xếp, kiểm chứng
ai_service.py        # AI Giai đoạn 2: provider, kế hoạch, kiểm chứng, hoàn tác
model_service.py     # Quản lý model Ollama/Whisper + phiên âm local
scripts/             # setup_ollama_windows.ps1/.bat (cài Ollama, không đóng gói binary)
media.py             # nhập media, thăm dò FFprobe, ảnh thu nhỏ
render.py            # xuất video bằng FFmpeg (track chính, overlay, trộn nhạc)
static/              # giao diện: xem trước trên, thuộc tính phải, timeline dưới
tests/               # test timeline + render thật + AI + model (đều dùng mock)
projects/default/    # dự án đang mở: media/, project.json, output/, transcript.*
PLAN.md              # lộ trình: Giai đoạn 2 đã làm (trừ kiểm chứng API trả phí thật)
```

## An toàn và bản quyền

- App không sửa file gốc, không xóa file của bạn, không gọi mạng ra
  ngoài trừ trình duyệt của chính bạn mở trang local.
- Chỉ dùng media mà bạn có quyền sử dụng. App không tự tải nhạc, ảnh
  hay video từ mạng về.
