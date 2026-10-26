"""ADIT server (Phase 1 manual editor + Phase 2 on-demand AI).

Stdlib-only HTTP server: serves the editor UI from static/ and a JSON
API under /api/. Run:

    python server.py [--port 8000]

then open http://127.0.0.1:8000 in a browser.

The active project lives in projects/default/ next to this file:
media files in media/, the project file as project.json, exports in
output/. Nothing here touches files outside that project folder
except reading the uploaded file the user chose.
"""

import argparse
import errno
import json
import mimetypes
import re
import shutil
import socket
import sys
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

# Frozen (PyInstaller) apps have no usable __file__ for the entry script:
# the exe lives next to static/ and projects/ in the output folder, so
# use the exe directory as ROOT there. In normal runs ROOT is this file's
# directory, unchanged.
if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
else:
    ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import ai_service as ai_mod
import model_service as model_mod
import media as media_mod
import render as render_mod
import timeline as tl

PROJECT_DIR = ROOT / "projects" / "default"
MEDIA_DIR = PROJECT_DIR / "media"
OUTPUT_DIR = PROJECT_DIR / "output"
PROJECT_FILE = PROJECT_DIR / "project.json"
STATIC_DIR = ROOT / "static"


def load_or_new():
    if PROJECT_FILE.exists():
        try:
            return tl.load_project(PROJECT_FILE)
        except Exception:
            pass
    project = tl.new_project()
    PROJECT_DIR.mkdir(parents=True, exist_ok=True)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return project


PROJECT = load_or_new()

# AI state (in memory only — never written to the repo or project.json):
# a pending proposal awaiting the user's "Ap dung", and the AI log file.
AI_LOG = PROJECT_DIR / "ai.log"
PENDING_PLAN = {"plan": None, "command": "", "provider": "", "model": ""}


def save():
    tl.save_project(PROJECT, PROJECT_FILE)


def _log_ai(event):
    try:
        ai_mod.log_ai_event(AI_LOG, event)
    except Exception:
        pass  # logging must never break an edit


def _parse_multipart(body, content_type):
    """Minimal single-file multipart parser. Returns (fields, files)."""
    m = re.search(r"boundary=([^;]+)", content_type or "")
    if not m:
        raise ValueError("multipart upload needs a boundary")
    boundary = m.group(1).strip().strip('"').encode()
    fields, files = {}, {}
    for part in body.split(b"--" + boundary):
        part = part.strip(b"\r\n")
        if not part or part == b"--":
            continue
        head, _, data = part.partition(b"\r\n\r\n")
        header = head.decode("utf-8", "replace")
        name_m = re.search(r'name="([^"]+)"', header)
        file_m = re.search(r'filename="([^"]*)"', header)
        if not name_m:
            continue
        name = name_m.group(1)
        if file_m and file_m.group(1):
            files[name] = (file_m.group(1), data.rstrip(b"\r\n") if data.endswith(b"\r\n") else data)
        else:
            fields[name] = data.decode("utf-8", "replace")
    return fields, files


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # -- helpers ---------------------------------------------------------
    def _send_json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, message, status=400):
        self._send_json({"error": message}, status=status)

    def _read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        return json.loads(raw.decode("utf-8")) if raw else {}

    def _read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def log_message(self, *args):  # keep stdout quiet
        pass

    # -- static ----------------------------------------------------------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        try:
            if path in ("/", "/index.html"):
                return self._serve_static("index.html")
            if path.startswith("/static/"):
                return self._serve_static(path[len("/static/"):])
            if path == "/api/project":
                return self._send_json({
                    "project": PROJECT,
                    "duration": tl.project_duration(PROJECT),
                })
            if path == "/api/ai/status":
                from urllib.parse import parse_qs
                query = parse_qs(urlparse(self.path).query)
                host = (query.get("host") or [None])[0]
                ollama = ai_mod.OllamaProvider(host=host)
                return self._send_json({
                    "default_provider": "ollama",
                    "providers": list(ai_mod.PROVIDER_NAMES),
                    "default_models": ai_mod.DEFAULT_MODELS,
                    "ollama": {"host": ollama.host,
                               "reachable": ollama.status(),
                               "default_model": ollama.model},
                    "has_backup": ai_mod.has_snapshot(PROJECT_DIR),
                    "has_pending": PENDING_PLAN["plan"] is not None,
                })
            if path == "/api/models":
                try:
                    ollama_models = model_mod.list_ollama_models()
                    ollama_error = None
                except ai_mod.AIError as exc:
                    ollama_models, ollama_error = [], str(exc)
                try:
                    import faster_whisper  # noqa: F401
                    fw_available = True
                except ImportError:
                    fw_available = False
                return self._send_json({
                    "ollama": {"reachable": ollama_error is None,
                               "models": ollama_models, "error": ollama_error},
                    "whisper": {"cache_dir": str(model_mod.whisper_cache_dir()),
                                "models": model_mod.list_whisper_models(),
                                "faster_whisper_available": fw_available,
                                "sizes": list(model_mod.WHISPER_SIZES)},
                })
            if path == "/api/transcript":
                try:
                    return self._send_json(model_mod.load_transcript(PROJECT_DIR))
                except FileNotFoundError as exc:
                    return self._send_error_json(str(exc), 404)
            if path.startswith("/api/media-file/"):
                name = unquote(path[len("/api/media-file/"):])
                target = (MEDIA_DIR / name).resolve()
                if not target.is_file() or target.parent != MEDIA_DIR.resolve():
                    return self._send_error_json("media not found", 404)
                return self._serve_file(target)
            if path.startswith("/api/waveform/"):
                # Never blocks the timeline: failures return empty peaks
                # with the reason, so the UI draws the block bare.
                name = unquote(path[len("/api/waveform/"):])
                if "/" in name or "\\" in name:
                    return self._send_error_json("invalid media name", 400)
                target = (MEDIA_DIR / name).resolve()
                if not target.is_file() or target.parent != MEDIA_DIR.resolve():
                    return self._send_error_json("media not found", 404)
                peaks, cached, error = media_mod.waveform_or_empty(target)
                return self._send_json({"filename": name, "peaks": peaks,
                                        "cached": cached, "error": error})
            if path.startswith("/api/thumb/"):
                name = unquote(path[len("/api/thumb/"):])
                target = PROJECT_DIR / "thumbs" / name
                if not target.is_file():
                    return self._send_error_json("thumbnail not found", 404)
                return self._serve_file(target)
            return self._send_error_json("not found", 404)
        except Exception as exc:
            traceback.print_exc()
            return self._send_error_json(str(exc), 500)

    def _serve_static(self, name):
        target = (STATIC_DIR / name).resolve()
        if not target.is_file() or STATIC_DIR.resolve() not in target.parents:
            return self._send_error_json("not found", 404)
        return self._serve_file(target)

    def _serve_file(self, target):
        data = target.read_bytes()
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # -- API -------------------------------------------------------------
    def do_POST(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        try:
            if path == "/api/media/upload":
                return self._upload()
            body = self._read_json()
            if path == "/api/project/save":
                save()
                return self._send_json({"ok": True, "project": PROJECT})
            if path == "/api/project/reset":
                if not body.get("confirm"):
                    return self._send_error_json("reset needs confirm=true")
                PROJECT.clear()
                PROJECT.update(tl.new_project())
                save()
                return self._send_json({"ok": True, "project": PROJECT})
            if path == "/api/clips":
                clip = tl.add_clip(PROJECT, body)
                save()
                return self._send_json({"clip": clip}, 201)
            if path == "/api/global-edits":
                edits = tl.set_global_edits(PROJECT, body)
                save()
                return self._send_json({"global_edits": edits})
            if path == "/api/global-edits/reset":
                edits = tl.reset_global_edits(PROJECT)
                save()
                return self._send_json({"global_edits": edits})
            if path == "/api/music":
                music = tl.set_background_music(
                    PROJECT, body.get("source"), body.get("volume", 0.15))
                save()
                return self._send_json({"background_music": music})
            if path == "/api/models/ollama/pull":
                result = model_mod.pull_ollama_model(body.get("name", ""))
                return self._send_json(result)
            if path == "/api/models/ollama/delete":
                if not body.get("confirm"):
                    return self._send_error_json(
                        "Xóa model cần confirm=true (tick ô xác nhận trong giao diện).")
                result = model_mod.delete_ollama_model(body.get("name", ""))
                return self._send_json(result)
            if path == "/api/models/whisper/download":
                result = model_mod.download_whisper_model(body.get("model", ""))
                return self._send_json(result)
            if path == "/api/models/whisper/delete":
                if not body.get("confirm"):
                    return self._send_error_json(
                        "Xóa model cần confirm=true (tick ô xác nhận trong giao diện).")
                result = model_mod.delete_whisper_model(body.get("name", ""))
                return self._send_json(result)
            if path == "/api/transcribe":
                source = str(body.get("source", "")).strip()
                if not source or "/" in source or "\\" in source:
                    return self._send_error_json(
                        "Chọn một file media đã có trong dự án (chỉ tên file).")
                target = (MEDIA_DIR / source).resolve()
                if not target.is_file() or target.parent != MEDIA_DIR.resolve():
                    return self._send_error_json("File media không có trong dự án.")
                result = model_mod.transcribe_media(
                    target, body.get("model") or "tiny")
                files = model_mod.save_transcript(PROJECT_DIR, result)
                _log_ai({"event": "transcribe", "provider": "faster-whisper-local",
                         "model": body.get("model") or "tiny",
                         "command": source, "operations": [],
                         "applied": False})
                return self._send_json({**result, **files})
            if path == "/api/ai/helpers":
                helper = body.get("helper", "")
                transcript = model_mod.load_transcript(PROJECT_DIR)
                provider = ai_mod.get_provider(body.get("provider") or "ollama", {
                    "model": body.get("model") or None,
                    "host": body.get("host") or body.get("base_url") or None,
                    "base_url": body.get("base_url") or body.get("host") or None,
                    "api_key": body.get("api_key") or None,
                })
                out = ai_mod.generate_helper(provider, helper, transcript["text"])
                _log_ai({"event": "helper", "provider": body.get("provider") or "ollama",
                         "model": provider.model, "command": helper,
                         "operations": [], "applied": False})
                return self._send_json(out)
            if path == "/api/ai/propose":
                return self._ai_propose(body)
            if path == "/api/ai/apply":
                return self._ai_apply(body)
            if path == "/api/ai/cancel":
                PENDING_PLAN.update({"plan": None, "command": "",
                                     "provider": "", "model": ""})
                return self._send_json({"ok": True})
            if path == "/api/ai/undo":
                restored = ai_mod.load_snapshot(PROJECT_DIR)
                PROJECT.clear()
                PROJECT.update(restored)
                save()
                _log_ai({"event": "undo", "provider": "", "model": "",
                         "command": "", "operations": [], "applied": True})
                return self._send_json({"ok": True, "project": PROJECT})
            if path == "/api/export":
                return self._export(body)
            m = re.match(r"^/api/clips/([^/]+)/(split|move)$", path)
            if m:
                clip_id, action = m.groups()
                if action == "split":
                    first, second = tl.split_clip(PROJECT, clip_id, float(body["at"]))
                    save()
                    return self._send_json({"first": first, "second": second})
                clip = tl.move_clip(PROJECT, clip_id, body["track"], body["start"])
                save()
                return self._send_json({"clip": clip})
            if path == "/api/timeline/reorder":
                clips = tl.reorder_track(PROJECT, int(body["track"]), list(body["ids"]))
                save()
                return self._send_json({"clips": clips})
            return self._send_error_json("not found", 404)
        except ai_mod.AIError as exc:
            return self._send_error_json(str(exc), 502)
        except (ValueError, KeyError, FileNotFoundError) as exc:
            return self._send_error_json(str(exc), 400)
        except Exception as exc:
            traceback.print_exc()
            return self._send_error_json(str(exc), 500)

    def _ai_propose(self, body):
        command = str(body.get("command", "")).strip()
        if not command:
            return self._send_error_json("Nhập yêu cầu cho AI trước.")
        provider_name = body.get("provider") or "ollama"
        settings = {
            "model": body.get("model") or None,
            "host": body.get("host") or body.get("base_url") or None,
            "base_url": body.get("base_url") or body.get("host") or None,
            "api_key": body.get("api_key") or None,
        }
        provider = ai_mod.get_provider(provider_name, settings)
        model = provider.model
        plan = provider.propose(command, PROJECT,
                                body.get("selected_clip_id") or None)
        errors = ai_mod.validate_plan(PROJECT, plan)
        descriptions = ai_mod.describe_plan(plan, PROJECT)
        _log_ai({"event": "propose", "provider": provider_name, "model": model,
                 "command": command[:500], "operations": plan.get("operations", []),
                 "valid": not errors, "errors": errors, "applied": False})
        if errors:
            PENDING_PLAN.update({"plan": None, "command": "",
                                 "provider": "", "model": ""})
            return self._send_json({"plan": plan, "descriptions": descriptions,
                                    "valid": False, "errors": errors,
                                    "applied": False})
        if body.get("auto_apply"):
            ai_mod.save_snapshot(PROJECT, PROJECT_DIR)
            summary = ai_mod.apply_plan(PROJECT, plan)
            save()
            _log_ai({"event": "apply", "provider": provider_name, "model": model,
                     "command": command[:500],
                     "operations": plan.get("operations", []), "applied": True})
            return self._send_json({"plan": plan, "descriptions": descriptions,
                                    "valid": True, "applied": True,
                                    "summary": summary, "project": PROJECT})
        PENDING_PLAN.update({"plan": plan, "command": command,
                             "provider": provider_name, "model": model})
        return self._send_json({"plan": plan, "descriptions": descriptions,
                                "valid": True, "applied": False})

    def _ai_apply(self, body):
        plan = body.get("plan") or PENDING_PLAN["plan"]
        if not plan:
            return self._send_error_json(
                "Không có đề xuất nào đang chờ. Hỏi AI trước, rồi bấm Áp dụng.")
        errors = ai_mod.validate_plan(PROJECT, plan)
        if errors:
            return self._send_error_json(
                "Đề xuất không còn hợp lệ với timeline hiện tại: " + "; ".join(errors))
        ai_mod.save_snapshot(PROJECT, PROJECT_DIR)
        summary = ai_mod.apply_plan(PROJECT, plan)
        save()
        _log_ai({"event": "apply", "provider": PENDING_PLAN["provider"],
                 "model": PENDING_PLAN["model"],
                 "command": PENDING_PLAN["command"],
                 "operations": plan.get("operations", []), "applied": True})
        PENDING_PLAN.update({"plan": None, "command": "",
                             "provider": "", "model": ""})
        return self._send_json({"ok": True, "summary": summary,
                                "project": PROJECT})

    def do_PATCH(self):
        m = re.match(r"^/api/clips/([^/]+)$", unquote(urlparse(self.path).path))
        if not m:
            return self._send_error_json("not found", 404)
        try:
            clip = tl.update_clip(PROJECT, m.group(1), self._read_json())
            save()
            return self._send_json({"clip": clip})
        except (ValueError, KeyError) as exc:
            return self._send_error_json(str(exc), 400)
        except Exception as exc:
            traceback.print_exc()
            return self._send_error_json(str(exc), 500)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        try:
            m = re.match(r"^/api/clips/([^/]+)$", path)
            if m:
                tl.delete_clip(PROJECT, m.group(1))
                save()
                return self._send_json({"ok": True})
            if path == "/api/music":
                tl.set_background_music(PROJECT, None)
                save()
                return self._send_json({"ok": True})
            return self._send_error_json("not found", 404)
        except (ValueError, KeyError) as exc:
            return self._send_error_json(str(exc), 400)
        except Exception as exc:
            traceback.print_exc()
            return self._send_error_json(str(exc), 500)

    def _upload(self):
        body = self._read_body()
        fields, files = _parse_multipart(body, self.headers.get("Content-Type", ""))
        if "file" not in files:
            return self._send_error_json("no file field in upload")
        filename, data = files["file"]
        safe = media_mod.safe_filename(filename)
        dest = media_mod.unique_path(MEDIA_DIR, safe)
        dest.write_bytes(data)
        entry = {
            "filename": dest.name,
            "type": media_mod.media_type_for(dest.name),
        }
        entry.update(media_mod.probe_media(dest))
        if entry["filename"] not in tl.media_by_filename(PROJECT):
            PROJECT["media"].append(entry)
        thumb_dir = PROJECT_DIR / "thumbs"
        thumb = thumb_dir / f"{dest.stem}.jpg"
        # Reuse an already-generated thumbnail; only generate on first use.
        if thumb.is_file() or media_mod.make_thumbnail(dest, thumb, entry["type"]):
            entry["thumbnail"] = thumb.name
        save()
        return self._send_json({"media": entry}, 201)

    def _export(self, body):
        draft = bool(body.get("draft", False))
        if draft:
            width, height = 540, 960
        else:
            width, height = PROJECT.get("width", 1080), PROJECT.get("height", 1920)
        out_name = body.get("filename") or ("export_draft.mp4" if draft else "export.mp4")
        out_name = media_mod.safe_filename(out_name)
        if not out_name.endswith(".mp4"):
            out_name += ".mp4"
        out_path = OUTPUT_DIR / out_name
        if out_path.exists() and not body.get("overwrite"):
            return self._send_error_json(
                f"output already exists: {out_name} (pass overwrite=true to replace it)")
        result = render_mod.render_project(
            PROJECT, MEDIA_DIR, out_path, width=width, height=height,
            fps=PROJECT.get("fps", 30))
        result["download"] = f"/api/output-file/{out_name}"
        return self._send_json(result)

# Output downloads are served by wrapping do_GET (kept separate so the
# main GET handler stays a plain route table):
_orig_get = Handler.do_GET


def _do_get_with_output(self):
    parsed = urlparse(self.path)
    path = unquote(parsed.path)
    if path.startswith("/api/output-file/"):
        name = unquote(path[len("/api/output-file/"):])
        target = (OUTPUT_DIR / name).resolve()
        if target.is_file() and target.parent == OUTPUT_DIR.resolve():
            return self._serve_file(target)
        return self._send_error_json("output not found", 404)
    return _orig_get(self)


Handler.do_GET = _do_get_with_output


def open_browser_when_ready(host, port, timeout_seconds=30):
    """Poll until the server answers, then open it in the browser.

    Used only with --open-browser. Polling (not a fixed sleep) is what
    guarantees the browser does not open before the server is ready.
    """
    connect_host = "127.0.0.1" if host in ("0.0.0.0", "") else host
    url = f"http://{connect_host}:{port}/"
    for _ in range(max(1, int(timeout_seconds * 2))):
        try:
            with socket.create_connection((connect_host, port), timeout=0.5):
                break
        except OSError:
            import time
            time.sleep(0.5)
    else:
        return False
    return bool(webbrowser.open(url))


def main():
    parser = argparse.ArgumentParser(description="ADIT MVP editor server")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--open-browser", action="store_true",
        help="Mo trinh duyet khi server da san sang (launcher dung cach nay "
             "thay cho viec tu mo trinh duyet; mac dinh khong tu mo).")
    args = parser.parse_args()
    PROJECT_DIR.mkdir(parents=True, exist_ok=True)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        server = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as exc:
        if exc.errno in (errno.EADDRINUSE, 98, 10048):
            print(
                f"LỖI: Cổng {args.port} đã được dùng — có thể ADIT đã đang "
                f"chạy rồi. Hãy mở http://127.0.0.1:{args.port}/ để dùng, "
                "hoặc dừng app cũ (bấm Ctrl+C trong cửa sổ cũ, hoặc đóng "
                "cửa sổ đó) rồi chạy lại.", file=sys.stderr)
            sys.exit(1)
        raise
    if shutil.which("ffmpeg") is None and not (
            (ROOT / "ffmpeg.exe").exists() or (ROOT / "ffmpeg").exists()):
        print("CẢNH BÁO: Không tìm thấy FFmpeg. Bạn vẫn mở và chỉnh sửa "
              "được, nhưng xuất video sẽ lỗi cho tới khi cài FFmpeg và "
              "thêm vào PATH (hoặc đặt ffmpeg.exe cạnh file chạy ADIT).")
    print(f"ADIT đang chạy tại http://{args.host}:{args.port}/", flush=True)
    print(f"Thư mục dự án: {PROJECT_DIR}", flush=True)
    print("Server đang chạy — đừng đóng cửa sổ này.", flush=True)
    print("Để dừng: bấm Ctrl+C trong cửa sổ này (hoặc đóng cửa sổ).", flush=True)
    if args.open_browser:
        threading.Thread(
            target=open_browser_when_ready,
            args=(args.host, args.port), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nĐã dừng ADIT. Hẹn gặp lại!")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
