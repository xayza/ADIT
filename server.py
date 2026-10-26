"""ADIT MVP server (Phase 1, manual editing only, no AI, no network calls).

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
import json
import mimetypes
import re
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

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


def save():
    tl.save_project(PROJECT, PROJECT_FILE)


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
            if path.startswith("/api/media-file/"):
                name = unquote(path[len("/api/media-file/"):])
                target = (MEDIA_DIR / name).resolve()
                if not target.is_file() or target.parent != MEDIA_DIR.resolve():
                    return self._send_error_json("media not found", 404)
                return self._serve_file(target)
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
            if path == "/api/music":
                music = tl.set_background_music(
                    PROJECT, body.get("source"), body.get("volume", 0.15))
                save()
                return self._send_json({"background_music": music})
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
        except (ValueError, KeyError, FileNotFoundError) as exc:
            return self._send_error_json(str(exc), 400)
        except Exception as exc:
            traceback.print_exc()
            return self._send_error_json(str(exc), 500)

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
        if media_mod.make_thumbnail(dest, thumb, entry["type"]):
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


def main():
    parser = argparse.ArgumentParser(description="ADIT MVP editor server")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    PROJECT_DIR.mkdir(parents=True, exist_ok=True)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"ADIT MVP running at http://{args.host}:{args.port}/")
    print(f"Project folder: {PROJECT_DIR}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
