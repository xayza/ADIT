"""Media import, probing and thumbnails for ADIT.

Original files are copied into the project media folder under a safe
filename; the user's original file is never modified or moved.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac"}


def media_type_for(filename):
    ext = Path(filename).suffix.lower()
    if ext in VIDEO_EXTS:
        return "video"
    if ext in IMAGE_EXTS:
        return "image"
    if ext in AUDIO_EXTS:
        return "audio"
    raise ValueError(f"unsupported media type: {filename!r}")


def safe_filename(name):
    base = Path(name).name
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base)
    base = base.strip("._")
    if not base:
        base = "media"
    stem, ext = Path(base).stem, Path(base).suffix.lower()
    return f"{stem[:80]}{ext}"


def unique_path(folder, filename):
    folder = Path(folder)
    candidate = folder / filename
    if not candidate.exists():
        return candidate
    stem, ext = Path(filename).stem, Path(filename).suffix
    i = 2
    while True:
        candidate = folder / f"{stem}_{i}{ext}"
        if not candidate.exists():
            return candidate
        i += 1


def probe_media(path):
    """Return {duration, width, height} via ffprobe, or Nones if it fails."""
    info = {"duration": None, "width": None, "height": None}
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-show_entries", "format=duration",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(out.stdout or "{}")
        if data.get("format", {}).get("duration"):
            info["duration"] = float(data["format"]["duration"])
        streams = data.get("streams") or []
        if streams:
            info["width"] = streams[0].get("width")
            info["height"] = streams[0].get("height")
    except Exception:
        pass
    return info


def import_media(src_path, media_dir):
    """Copy a file into the media folder; return its media entry dict."""
    src = Path(src_path)
    if not src.is_file():
        raise FileNotFoundError(f"media file not found: {src}")
    mtype = media_type_for(src.name)
    media_dir = Path(media_dir)
    media_dir.mkdir(parents=True, exist_ok=True)
    dest = unique_path(media_dir, safe_filename(src.name))
    shutil.copyfile(src, dest)
    info = probe_media(dest)
    return {
        "filename": dest.name,
        "type": mtype,
        "duration": info["duration"],
        "width": info["width"],
        "height": info["height"],
    }


def make_thumbnail(media_path, thumb_path, media_type):
    """Write a JPEG thumbnail; return True, or False if it cannot be made.

    Video: one FFmpeg frame at 1s, scaled to 320px wide.
    Image: Pillow thumbnail (Pillow is optional; without it, no thumbnail).
    Audio: no thumbnail (returns False).
    """
    media_path, thumb_path = Path(media_path), Path(thumb_path)
    thumb_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if media_type == "video":
            result = subprocess.run(
                ["ffmpeg", "-y", "-v", "error", "-ss", "1", "-i", str(media_path),
                 "-frames:v", "1", "-vf", "scale=320:-2", str(thumb_path)],
                capture_output=True, text=True, timeout=30,
            )
            return result.returncode == 0 and thumb_path.exists()
        if media_type == "image":
            from PIL import Image
            with Image.open(media_path) as im:
                im.convert("RGB").thumbnail((320, 320))
                im.save(thumb_path, "JPEG", quality=82)
            return True
    except Exception:
        return False
    return False
