"""ADIT Model Manager + local transcription (CreatorUtils-style utilities).

Safety rules, mirroring the AI permission set:
- Ollama models are listed/pulled/deleted only through the Ollama API
  or the `ollama` CLI — never by touching files by hand.
- Whisper models are listed/deleted ONLY inside the faster-whisper /
  Hugging Face cache directory. A delete that resolves outside that
  root is refused, and only folders actually listed are deletable.
- Nothing here downloads a model silently: downloads happen only when
  the user clicks download in the UI (or runs the setup script).
- Transcription itself runs locally with faster-whisper once a model
  is downloaded — no internet is needed for the transcription step.
- faster-whisper is an OPTIONAL dependency: if it is not installed,
  every transcription/download function returns a clear install
  instruction instead of a fake transcript.
"""

import os
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path

import json as _json

from ai_service import AIError

# ---------------------------------------------------------------- Ollama

_OLLAMA_NAME_RE = re.compile(r"^[A-Za-z0-9._\-/]+(:[A-Za-z0-9._\-]+)?$")


def validate_ollama_model_name(name):
    """Reject anything that is not a plain Ollama model name:tag."""
    if not name or not isinstance(name, str):
        raise ValueError("Tên model Ollama không được để trống.")
    name = name.strip()
    if len(name) > 128 or ".." in name or name.startswith(("/", ".")):
        raise ValueError(f"Tên model Ollama không hợp lệ: {name!r}")
    if not _OLLAMA_NAME_RE.match(name):
        raise ValueError(
            f"Tên model Ollama không hợp lệ: {name!r}. Chỉ dùng chữ, số, "
            "dấu chấm, gạch ngang, gạch dưới, gạch chéo và dấu hai chấm cho tag.")
    return name


def ollama_host(settings_host=None):
    return (settings_host or os.environ.get("ADIT_OLLAMA_HOST")
            or "http://localhost:11434").rstrip("/")


def list_ollama_models(host=None):
    """Return [{name, size}] from /api/tags. Raises AIError if unreachable."""
    url = f"{ollama_host(host)}/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
    except Exception:
        raise AIError(
            f"Không kết nối được Ollama tại {ollama_host(host)}. "
            "Hãy chạy script scripts/setup_ollama_windows.ps1 một lần, "
            "rồi chạy 'ollama serve' nếu Ollama chưa chạy.")
    models = []
    for entry in data.get("models", []):
        models.append({"name": entry.get("name", ""),
                       "size": entry.get("size"),
                       "source": "ollama"})
    return models


def _default_run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=3600)


def pull_ollama_model(name, run_fn=None, list_fn=None):
    """Pull an Ollama model, then verify it is actually listed."""
    name = validate_ollama_model_name(name)
    run = run_fn or _default_run
    result = run(["ollama", "pull", name])
    if getattr(result, "returncode", 1) != 0:
        raise AIError(
            f"Tải model Ollama '{name}' thất bại: "
            f"{getattr(result, 'stderr', '')[:500]}")
    listed = (list_fn or list_ollama_models)()
    names = [m["name"] for m in listed]
    if not any(n == name or n.startswith(name + ":") for n in names):
        raise AIError(
            f"Đã chạy 'ollama pull {name}' nhưng model chưa xuất hiện trong "
            "'ollama list'. Hãy kiểm tra lại bằng 'ollama list'.")
    return {"name": name, "source": "ollama"}


def delete_ollama_model(name, run_fn=None, list_fn=None):
    """Delete an Ollama model, then verify it is actually gone."""
    name = validate_ollama_model_name(name)
    run = run_fn or _default_run
    result = run(["ollama", "delete", name])
    if getattr(result, "returncode", 1) != 0:
        raise AIError(
            f"Xóa model Ollama '{name}' thất bại: "
            f"{getattr(result, 'stderr', '')[:500]}")
    listed = (list_fn or list_ollama_models)()
    names = [m["name"] for m in listed]
    if any(n == name or n.startswith(name + ":") for n in names):
        raise AIError(
            f"Đã chạy 'ollama delete {name}' nhưng model vẫn còn trong "
            "'ollama list'.")
    return {"name": name, "source": "ollama", "deleted": True}


# ------------------------------------------------------- Whisper cache

WHISPER_SIZES = ("tiny", "tiny.en", "base", "base.en", "small", "small.en",
                 "medium", "medium.en", "large-v1", "large-v2", "large-v3",
                 "distil-large-v2", "distil-large-v3")

FASTER_WHISPER_INSTALL = (
    "Chưa cài faster-whisper. Cài bằng lệnh: pip install faster-whisper "
    "(xem requirements-optional.txt), sau đó tải một model Whisper trong "
    "Model Manager rồi thử lại.")


def whisper_cache_dir():
    """HF cache hub dir. Overridable via ADIT_WHISPER_CACHE (tests)."""
    override = os.environ.get("ADIT_WHISPER_CACHE")
    if override:
        return Path(override)
    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        return Path(hf_home) / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def _folder_size(path):
    total = 0
    for item in Path(path).rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                pass
    return total


def list_whisper_models(cache_dir=None):
    """List Whisper model folders inside the cache dir only."""
    root = Path(cache_dir or whisper_cache_dir())
    models = []
    if not root.is_dir():
        return models
    for folder in sorted(root.iterdir()):
        if not folder.is_dir() or not folder.name.startswith("models--"):
            continue
        # Only faster-whisper models belong to ADIT's Whisper list. The
        # shared HF cache may hold other projects' models (e.g. Piper
        # voices); those must never appear here or become deletable.
        if "faster-whisper" not in folder.name:
            continue
        display = folder.name[len("models--"):].replace("--", "/")
        models.append({"name": display, "folder": folder.name,
                       "size": _folder_size(folder), "source": "whisper"})
    return models


def _resolve_whisper_folder(name, cache_dir=None):
    """Resolve a listed Whisper folder name to a path inside the cache.

    ``name`` may be the display name (Systran/faster-whisper-tiny) or
    the folder name (models--Systran--faster-whisper-tiny). Anything
    resolving outside the cache root is refused.
    """
    root = Path(cache_dir or whisper_cache_dir()).resolve()
    if "/" in name or "\\" in name:
        folder_name = "models--" + name.replace("/", "--").replace("\\", "--")
    else:
        folder_name = name
    if "faster-whisper" not in folder_name:
        raise ValueError(
            f"Model Whisper không có trong thư mục cache an toàn: {name!r}")
    if folder_name.startswith("models--"):
        candidate = (root / folder_name).resolve()
    else:
        candidate = (root / folder_name).resolve()
    if candidate.parent != root or not candidate.is_dir():
        raise ValueError(
            f"Model Whisper không có trong thư mục cache an toàn: {name!r}")
    return candidate


def delete_whisper_model(name, cache_dir=None):
    """Delete a listed Whisper folder inside the cache, then verify."""
    folder = _resolve_whisper_folder(name, cache_dir)
    shutil.rmtree(folder)
    if folder.exists():
        raise AIError(f"Xóa model Whisper '{name}' thất bại: thư mục vẫn còn.")
    return {"name": name, "source": "whisper", "deleted": True}


def download_whisper_model(model, cache_dir=None):
    """Download a Whisper model with faster-whisper (optional dependency)."""
    if model not in WHISPER_SIZES:
        raise ValueError(
            f"Model Whisper không hỗ trợ tải tự động: {model!r}. "
            f"Chọn một trong: {', '.join(WHISPER_SIZES)}.")
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise AIError(FASTER_WHISPER_INSTALL)
    # Constructing the model downloads it into the HF cache if missing.
    WhisperModel(model, device="cpu", compute_type="int8")
    listed = list_whisper_models(cache_dir)
    if not any(model in m["name"] for m in listed):
        raise AIError(
            f"Đã tải model Whisper '{model}' nhưng chưa thấy trong thư mục "
            "cache. Hãy kiểm tra lại danh sách model.")
    return {"name": model, "source": "whisper"}


# ------------------------------------------------------- transcription


def transcribe_media(media_path, model="tiny", backend_module=None):
    """Transcribe locally with faster-whisper.

    Returns {"text": str, "segments": [{"start","end","text"}]}.
    ``backend_module`` is a test hook: pass a fake module with a
    WhisperModel class to avoid a real model download in tests.
    """
    if backend_module is None:
        try:
            import faster_whisper as backend_module
        except ImportError:
            raise AIError(FASTER_WHISPER_INSTALL)
    whisper = backend_module.WhisperModel(model, device="cpu",
                                          compute_type="int8")
    segments, _info = whisper.transcribe(str(media_path), beam_size=1)
    out_segments = []
    texts = []
    for seg in segments:
        item = {"start": round(float(seg.start), 2),
                "end": round(float(seg.end), 2),
                "text": str(seg.text).strip()}
        out_segments.append(item)
        texts.append(item["text"])
    return {"text": " ".join(texts), "segments": out_segments}


def save_transcript(project_dir, result):
    """Save transcript.txt + transcript.json in the project folder."""
    project_dir = Path(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    text_path = project_dir / "transcript.txt"
    json_path = project_dir / "transcript.json"
    text_path.write_text(result["text"], encoding="utf-8")
    json_path.write_text(_json.dumps(result, indent=2, ensure_ascii=False),
                         encoding="utf-8")
    return {"text_file": str(text_path), "json_file": str(json_path)}


def load_transcript(project_dir):
    """Load a saved transcript.json, or raise FileNotFoundError."""
    path = Path(project_dir) / "transcript.json"
    if not path.exists():
        raise FileNotFoundError(
            "Chưa có bản ghi nào. Phiên âm một file trong dự án trước.")
    return _json.loads(path.read_text(encoding="utf-8"))
