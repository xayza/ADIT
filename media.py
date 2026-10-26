"""Media import, probing and thumbnails for ADIT.

Original files are copied into the project media folder under a safe
filename; the user's original file is never modified or moved.
"""

import json
import re
import shutil
import struct
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


def waveform_cache_path(media_path):
    """Cache file next to the media, e.g. song.mp3 -> song.waveform.json."""
    path = Path(media_path)
    return path.with_name(path.stem + ".waveform.json")


def generate_waveform(media_path, buckets=120):
    """Return (peaks, cached).

    Peaks are normalised 0..1 max-absolute amplitudes per bucket, computed
    once from FFmpeg-decoded mono PCM and cached next to the media file.
    The cache is reused only when the media's mtime and size still match;
    on any failure an empty peak list is returned (callers must never
    block the timeline on a waveform) — use ``waveform_or_empty`` for that.
    """
    media_path = Path(media_path)
    cache = waveform_cache_path(media_path)
    try:
        stat = media_path.stat()
        if cache.is_file():
            data = json.loads(cache.read_text(encoding="utf-8"))
            if (data.get("mtime") == stat.st_mtime_ns
                    and data.get("size") == stat.st_size
                    and isinstance(data.get("peaks"), list)):
                return [float(p) for p in data["peaks"]], True
    except Exception:
        pass
    result = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(media_path),
         "-ac", "1", "-ar", "8000", "-f", "f32le", "-"],
        capture_output=True, timeout=120,
    )
    if result.returncode != 0 or not result.stdout:
        # Raised so waveform_or_empty can report the reason; it never
        # propagates to the timeline UI, which draws a bare block.
        tail = (result.stderr or b"")[-500:].decode("utf-8", "replace")
        raise RuntimeError(f"ffmpeg waveform failed: {tail or 'no audio data'}")
    count = len(result.stdout) // 4
    samples = struct.unpack(f"<{count}f", result.stdout[:count * 4])
    if not samples:
        return [], False
    peak = max(abs(s) for s in samples) or 1.0
    per = max(1, (len(samples) + buckets - 1) // buckets)
    peaks = []
    for i in range(buckets):
        chunk = samples[i * per:(i + 1) * per]
        peaks.append(round(max((abs(s) for s in chunk), default=0.0) / peak, 4))
    try:
        tmp = cache.with_suffix(".tmp")
        tmp.write_text(json.dumps(
            {"peaks": peaks, "mtime": media_path.stat().st_mtime_ns,
             "size": media_path.stat().st_size}, ensure_ascii=False),
            encoding="utf-8")
        tmp.replace(cache)
    except Exception:
        pass  # a missing cache only costs a regeneration next time
    return peaks, False


def waveform_or_empty(media_path, buckets=120):
    """Never-raising wrapper: ([peaks], cached, error-or-None)."""
    try:
        peaks, cached = generate_waveform(media_path, buckets=buckets)
        return peaks, cached, None
    except Exception as exc:  # ffmpeg missing, unreadable file, ...
        return [], False, str(exc)


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
