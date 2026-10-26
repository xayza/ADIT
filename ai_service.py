"""ADIT Phase 2 — AI service (on-demand, same permissions for all providers).

The AI never gets direct tool, file or shell access. A provider only
receives the user's command plus a condensed timeline summary and must
return a JSON EditPlan. The server validates every operation against
the live timeline model before anything is applied, and applying is
always undoable via a project.json backup.

Permission set — identical for Ollama, OpenAI-compatible APIs and
Anthropic, regardless of model. A smarter paid model only understands
intent faster; it never gets more rights:

    trim_clip, split_clip, delete_clip, move_clip, reorder_clip,
    set_speed, set_volume, add_text_clip, update_text_clip, set_fade,
    set_music

Nothing in this module deletes a user file, runs a shell command,
accesses the network except the configured provider's chat API, or
touches anything outside the project. API keys are never written to
a repo file, project.json or a log: they live only in the request
that configures a provider for that call (or in an environment
variable), and the log helper strips them.
"""

import copy
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import timeline as tl

# ---------------------------------------------------------------- errors


class AIError(Exception):
    """A user-facing AI failure (Vietnamese message, no secrets)."""


# ------------------------------------------------------------ plan schema

ALLOWED_OPS = (
    "trim_clip", "split_clip", "delete_clip", "move_clip", "reorder_clip",
    "set_speed", "set_volume", "add_text_clip", "update_text_clip",
    "set_fade", "set_music",
)

FADE_EFFECTS = ("none", "fade_in", "fade_out", "fade_both")

OP_SCHEMA = """Mỗi thao tác là một object JSON với khóa "op" và các tham số:
- {"op": "trim_clip", "clip_id": "...", "trim_in": 1.0, "duration": 3.0}
  (trim_in hoặc duration, ít nhất một cái; không đọc quá cuối nguồn)
- {"op": "split_clip", "clip_id": "...", "at": 12.5}
  (at là thời điểm trên timeline, phải nằm trong clip)
- {"op": "delete_clip", "clip_id": "..."}
- {"op": "move_clip", "clip_id": "...", "track": 0, "start": 4.0}
- {"op": "reorder_clip", "track": 0, "ids": ["id1", "id2"]}
  (ids phải đúng toàn bộ clip không phải nhạc trên track đó)
- {"op": "set_speed", "clip_id": "...", "speed": 1.25}  (0.5–2.0)
- {"op": "set_volume", "clip_id": "...", "volume": 0.8, "muted": false}  (0–1.5)
- {"op": "add_text_clip", "text": "...", "track": 1, "start": 2.0,
   "duration": 3.0, "font_size": 48, "color": "#FFFFFF", "position": "center"}
- {"op": "update_text_clip", "clip_id": "...", "text": "..."}
- {"op": "set_fade", "clip_id": "...", "effect": "fade_in"}
  (effect chỉ được: none, fade_in, fade_out, fade_both)
- {"op": "set_music", "source": "nhac.mp3", "volume": 0.15}  (0–0.30)
  (source phải là file nhạc đã có trong dự án; source null để xóa nhạc nền)
"""


def timeline_summary(project):
    """Condensed timeline for the model — no file paths, no keys."""
    clips = []
    for clip in project.get("clips", []):
        clips.append({
            "id": clip["id"], "type": clip["type"], "source": clip.get("source", ""),
            "track": clip["track"], "start": clip["start"],
            "duration": clip["duration"], "trim_in": clip.get("trim_in", 0),
            "speed": clip.get("speed", 1.0), "volume": clip.get("volume", 1.0),
            "muted": clip.get("muted", False), "effect": clip.get("effect", "none"),
            "text": clip.get("text", ""),
        })
    return {
        "name": project.get("name", ""),
        "duration": tl.project_duration(project),
        "clips": clips,
        "media": [{"filename": m["filename"], "type": m["type"],
                   "duration": m.get("duration")} for m in project.get("media", [])],
        "background_music": project.get("background_music"),
    }


def build_system_prompt(project, selected_clip_id=None):
    selected = ""
    if selected_clip_id:
        try:
            clip = tl.get_clip(project, selected_clip_id)
            selected = (f"\nClip người dùng đang chọn: {clip['id']} "
                        f"({clip['type']}, track {clip['track']}, "
                        f"{clip['start']}s–{clip['start'] + clip['duration']}s). "
                        f"Ưu tiên áp dụng lệnh cho clip này nếu lệnh mơ hồ.")
        except KeyError:
            selected = ""
    return (
        "Bạn là trợ lý chỉnh sửa video của ADIT. Người dùng ra lệnh bằng "
        "tiếng Việt. Bạn CHỈ được trả về một JSON duy nhất, không giải "
        "thích, không thêm chữ ngoài JSON, không lệnh shell, không đường "
        "dẫn file ngoài dự án.\n"
        "Định dạng trả về: {\"operations\": [...]}\n"
        "Chỉ dùng các thao tác sau, mọi thao tác khác đều bị từ chối:\n"
        + OP_SCHEMA +
        "\nQuy tắc: clip video/ảnh/chữ trên cùng một track không được chồng "
        "lên nhau; thời gian phải nằm trong clip và trong nguồn; tốc độ "
        "0.5–2.0; âm lượng clip 0–1.5; âm lượng nhạc nền 0–0.30; nếu lệnh "
        "không rõ, hãy chọn cách hiểu an toàn nhất và ít thay đổi nhất, "
        "đừng bịa thêm clip hay bịa thời gian.\n"
        f"Timeline hiện tại:\n{json.dumps(timeline_summary(project), ensure_ascii=False)}"
        + selected
    )


def parse_edit_plan(raw_text):
    """Extract an EditPlan from model output. Raises AIError on bad JSON."""
    if not raw_text or not raw_text.strip():
        raise AIError("AI trả về nội dung rỗng, chưa có kế hoạch chỉnh sửa nào.")
    text = raw_text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    if not text.startswith("{"):
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise AIError("AI không trả về JSON kế hoạch hợp lệ, vui lòng thử lại.")
        text = text[start:end + 1]
    try:
        plan = json.loads(text)
    except json.JSONDecodeError:
        raise AIError("AI trả về JSON kế hoạch không hợp lệ, vui lòng thử lại.")
    if not isinstance(plan, dict) or not isinstance(plan.get("operations"), list):
        raise AIError("Kế hoạch của AI thiếu danh sách 'operations', vui lòng thử lại.")
    for op in plan["operations"]:
        if not isinstance(op, dict) or not op.get("op"):
            raise AIError("Kế hoạch của AI có thao tác không hợp lệ, vui lòng thử lại.")
    return plan


# ------------------------------------------------------- plan description


def _clip_label(project, clip_id):
    try:
        clip = tl.get_clip(project, clip_id)
        return f"clip {clip['type']} '{clip.get('source') or clip.get('text', '')[:20]}' ({clip_id})"
    except KeyError:
        return f"clip {clip_id}"


def describe_operation(op, project):
    """One plain-Vietnamese line per operation (never raises for bad ops)."""
    name = op.get("op")
    try:
        if name == "trim_clip":
            return (f"Cắt clip {_clip_label(project, op.get('clip_id'))}: "
                    f"trim_in={op.get('trim_in', 'giữ nguyên')}, "
                    f"duration={op.get('duration', 'giữ nguyên')}.")
        if name == "split_clip":
            return f"Tách {_clip_label(project, op.get('clip_id'))} tại {op.get('at')}s."
        if name == "delete_clip":
            return f"Xóa {_clip_label(project, op.get('clip_id'))} khỏi timeline."
        if name == "move_clip":
            return (f"Di chuyển {_clip_label(project, op.get('clip_id'))} "
                    f"sang track {op.get('track')} tại {op.get('start')}s.")
        if name == "reorder_clip":
            return f"Sắp xếp lại track {op.get('track')} theo thứ tự đã cho."
        if name == "set_speed":
            return f"Đặt tốc độ {_clip_label(project, op.get('clip_id'))} thành {op.get('speed')}x."
        if name == "set_volume":
            muted = " (tắt tiếng)" if op.get("muted") else ""
            return (f"Đặt âm lượng {_clip_label(project, op.get('clip_id'))} "
                    f"thành {op.get('volume')}{muted}.")
        if name == "add_text_clip":
            return (f"Thêm chữ '{op.get('text', '')}' vào track "
                    f"{op.get('track', 1)} tại {op.get('start', 0)}s, "
                    f"dài {op.get('duration')}s.")
        if name == "update_text_clip":
            return f"Sửa chữ của {_clip_label(project, op.get('clip_id'))}."
        if name == "set_fade":
            return (f"Đặt hiệu ứng mờ của {_clip_label(project, op.get('clip_id'))} "
                    f"thành {op.get('effect')}.")
        if name == "set_music":
            if op.get("source") is None:
                return "Xóa nhạc nền."
            return f"Đặt nhạc nền '{op.get('source')}' với âm lượng {op.get('volume', 0.15)}."
        return f"Thao tác không được phép: {name}."
    except Exception:
        return f"Thao tác {name} (không mô tả được)."


def describe_plan(plan, project):
    return [describe_operation(op, project) for op in plan.get("operations", [])]


# --------------------------------------------------------- plan validation


def _apply_one(working, op):
    """Apply one operation to a working copy. Raises ValueError/KeyError."""
    name = op.get("op")
    if name not in ALLOWED_OPS:
        raise ValueError(f"thao tác không được phép: {name!r}")
    if name == "trim_clip":
        patch = {}
        if "trim_in" in op:
            patch["trim_in"] = float(op["trim_in"])
        if "duration" in op:
            patch["duration"] = float(op["duration"])
        if not patch:
            raise ValueError("trim_clip cần trim_in hoặc duration")
        tl.update_clip(working, op["clip_id"], patch)
    elif name == "split_clip":
        tl.split_clip(working, op["clip_id"], float(op["at"]))
    elif name == "delete_clip":
        tl.delete_clip(working, op["clip_id"])
    elif name == "move_clip":
        tl.move_clip(working, op["clip_id"], int(op["track"]), float(op["start"]))
    elif name == "reorder_clip":
        tl.reorder_track(working, int(op["track"]), list(op["ids"]))
    elif name == "set_speed":
        tl.update_clip(working, op["clip_id"], {"speed": float(op["speed"])})
    elif name == "set_volume":
        patch = {"volume": float(op["volume"])}
        if "muted" in op:
            patch["muted"] = bool(op["muted"])
        tl.update_clip(working, op["clip_id"], patch)
    elif name == "add_text_clip":
        track = int(op.get("track", 1))
        start = op.get("start")
        if start is None:
            others = [c for c in working["clips"]
                      if c["track"] == track and c["type"] != "audio"]
            start = max((c["start"] + c["duration"] for c in others), default=0.0)
        tl.add_clip(working, {
            "type": "text", "source": "", "track": track,
            "start": float(start), "duration": float(op["duration"]),
            "text": op["text"], "font_size": int(op.get("font_size", 48)),
            "color": op.get("color", "#FFFFFF"),
            "position": op.get("position", "center"), "effect": "none",
        })
    elif name == "update_text_clip":
        clip = tl.get_clip(working, op["clip_id"])
        if clip["type"] != "text":
            raise ValueError("update_text_clip chỉ áp dụng cho clip chữ")
        patch = {}
        for key in ("text", "font_size", "color", "position"):
            if key in op:
                patch[key] = op[key]
        if not patch:
            raise ValueError("update_text_clip cần ít nhất một trường để sửa")
        tl.update_clip(working, op["clip_id"], patch)
    elif name == "set_fade":
        if op.get("effect") not in FADE_EFFECTS:
            raise ValueError(f"set_fade chỉ nhận: {', '.join(FADE_EFFECTS)}")
        tl.update_clip(working, op["clip_id"], {"effect": op["effect"]})
    elif name == "set_music":
        if op.get("source") is None:
            tl.set_background_music(working, None)
        else:
            tl.set_background_music(working, op["source"],
                                    float(op.get("volume", 0.15)))
    else:  # pragma: no cover — guarded by the allowlist above
        raise ValueError(f"thao tác không được phép: {name!r}")


def validate_plan(project, plan):
    """Dry-run the whole plan. Returns a list of Vietnamese error strings.

    An empty list means the plan is safe to apply. Nothing is mutated.
    """
    if not isinstance(plan, dict) or not isinstance(plan.get("operations"), list):
        return ["Kế hoạch không có danh sách 'operations'."]
    if not plan["operations"]:
        return ["Kế hoạch không có thao tác nào để áp dụng."]
    working = copy.deepcopy(project)
    errors = []
    for i, op in enumerate(plan["operations"], start=1):
        if not isinstance(op, dict) or not op.get("op"):
            errors.append(f"Thao tác {i}: không hợp lệ.")
            break
        try:
            _apply_one(working, op)
        except (ValueError, KeyError, TypeError) as exc:
            errors.append(f"Thao tác {i} ({op.get('op')}): {exc}")
            break
    return errors


def apply_plan(project, plan):
    """Validate, then apply the whole plan as one transaction.

    Returns the Vietnamese description list. Raises ValueError with the
    validation errors if anything is invalid, and then nothing changes.
    """
    errors = validate_plan(project, plan)
    if errors:
        raise ValueError("; ".join(errors))
    descriptions = describe_plan(plan, project)
    working = copy.deepcopy(project)
    for op in plan["operations"]:
        _apply_one(working, op)
    tl.validate_project(working)
    project.clear()
    project.update(working)
    return descriptions


# ------------------------------------------------------------ snapshots


def save_snapshot(project, project_dir):
    """Save a snapshot backup; returns (latest_path, timestamped_path)."""
    project_dir = Path(project_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    timestamped = project_dir / f"project.json.bak-{stamp}"
    tl.save_project(project, timestamped)
    latest = project_dir / "project.json.bak"
    tl.save_project(project, latest)
    return latest, timestamped


def load_snapshot(project_dir):
    """Load the latest snapshot. Raises FileNotFoundError if none exists."""
    latest = Path(project_dir) / "project.json.bak"
    if not latest.exists():
        raise FileNotFoundError("Không có bản sao lưu nào để hoàn tác.")
    return tl.load_project(latest)


def has_snapshot(project_dir):
    return (Path(project_dir) / "project.json.bak").exists()


# ---------------------------------------------------------------- logging


def _strip_secrets(obj):
    if isinstance(obj, dict):
        return {k: _strip_secrets(v) for k, v in obj.items()
                if k not in ("api_key", "apikey", "token", "password")}
    if isinstance(obj, list):
        return [_strip_secrets(v) for v in obj]
    return obj


def log_ai_event(log_path, event):
    """Append one JSON log line. API keys are always stripped."""
    clean = _strip_secrets(event)
    clean["time"] = datetime.now().isoformat(timespec="seconds")
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(clean, ensure_ascii=False) + "\n")


# -------------------------------------------------------------- providers


def _http_post_json(url, payload, headers, timeout):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST")
    for key, value in headers.items():
        req.add_header(key, value)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise AIError(f"Nhà cung cấp AI trả về lỗi HTTP {exc.code}: {detail}")
    except urllib.error.URLError as exc:
        raise AIError(f"Không kết nối được nhà cung cấp AI: {exc.reason}")


def _http_get_json(url, timeout):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise AIError(str(exc))


class BaseProvider:
    name = "base"

    def __init__(self, model=None, timeout=120):
        self.model = model
        self.timeout = timeout

    def propose(self, command, project, selected_clip_id=None):
        system = build_system_prompt(project, selected_clip_id)
        raw = self._chat(system, command)
        return parse_edit_plan(raw)

    def generate_text(self, system, user):
        """Free-form text generation (helpers only — never edits a timeline)."""
        return self._chat(system, user)

    def _chat(self, system, user):
        raise NotImplementedError


class OllamaProvider(BaseProvider):
    name = "ollama"
    default_model = "qwen2.5:3b-instruct"

    def __init__(self, model=None, host=None, timeout=120):
        super().__init__(model or self.default_model, timeout)
        self.host = (host or os.environ.get("ADIT_OLLAMA_HOST")
                     or "http://localhost:11434").rstrip("/")

    def _chat(self, system, user):
        try:
            data = _http_post_json(
                f"{self.host}/api/chat",
                {"model": self.model,
                 "messages": [{"role": "system", "content": system},
                              {"role": "user", "content": user}],
                 "stream": False, "format": "json"},
                {}, self.timeout)
        except AIError as exc:
            if "Không kết nối" in str(exc):
                raise AIError(
                    f"Không kết nối được Ollama tại {self.host}. "
                    "Hãy chạy script scripts/setup_ollama_windows.ps1 một lần, "
                    "rồi chạy 'ollama serve' nếu Ollama chưa chạy.")
            raise
        try:
            return data["message"]["content"]
        except (KeyError, TypeError):
            raise AIError("Ollama trả về định dạng không nhận diện được.")

    def status(self):
        """True if an Ollama server answers at the configured host."""
        try:
            _http_get_json(f"{self.host}/api/tags", timeout=2)
            return True
        except AIError:
            return False


class OpenAICompatibleProvider(BaseProvider):
    name = "openai"
    default_model = "gpt-4o-mini"

    def __init__(self, model=None, base_url=None, api_key=None, timeout=120):
        super().__init__(model or self.default_model, timeout)
        self.base_url = (base_url or os.environ.get("ADIT_OPENAI_BASE_URL")
                         or "https://api.openai.com/v1").rstrip("/")
        self.api_key = (api_key or os.environ.get("ADIT_OPENAI_API_KEY")
                        or os.environ.get("OPENAI_API_KEY"))
        if not self.api_key:
            raise AIError(
                "Chưa có API key cho nhà cung cấp này. Đặt biến môi trường "
                "OPENAI_API_KEY, hoặc nhập key vào ô API key trong giao diện "
                "(key chỉ dùng cho phiên làm việc này, không được lưu lại).")

    def _chat(self, system, user):
        data = _http_post_json(
            f"{self.base_url}/chat/completions",
            {"model": self.model,
             "messages": [{"role": "system", "content": system},
                          {"role": "user", "content": user}],
             "temperature": 0.2,
             "response_format": {"type": "json_object"}},
            {"Authorization": f"Bearer {self.api_key}"}, self.timeout)
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise AIError("API trả về định dạng không nhận diện được.")


class AnthropicProvider(BaseProvider):
    name = "anthropic"
    default_model = "claude-sonnet-4-5"

    def __init__(self, model=None, base_url=None, api_key=None, timeout=120):
        super().__init__(model or self.default_model, timeout)
        self.base_url = (base_url or "https://api.anthropic.com").rstrip("/")
        self.api_key = (api_key or os.environ.get("ADIT_ANTHROPIC_API_KEY")
                        or os.environ.get("ANTHROPIC_API_KEY"))
        if not self.api_key:
            raise AIError(
                "Chưa có API key cho Anthropic. Đặt biến môi trường "
                "ANTHROPIC_API_KEY, hoặc nhập key vào ô API key trong giao diện "
                "(key chỉ dùng cho phiên làm việc này, không được lưu lại).")

    def _chat(self, system, user):
        data = _http_post_json(
            f"{self.base_url}/v1/messages",
            {"model": self.model, "max_tokens": 2048, "system": system,
             "messages": [{"role": "user", "content": user}]},
            {"x-api-key": self.api_key,
             "anthropic-version": "2023-06-01"}, self.timeout)
        try:
            texts = [b["text"] for b in data["content"] if b.get("type") == "text"]
            return "\n".join(texts)
        except (KeyError, TypeError):
            raise AIError("API trả về định dạng không nhận diện được.")


class MockProvider(BaseProvider):
    """Test-only provider: returns a preset plan, makes no network call."""

    name = "mock"

    def __init__(self, plan=None, model="mock"):
        super().__init__(model)
        self.plan = plan or {"operations": []}

    def _chat(self, system, user):
        return json.dumps(self.plan, ensure_ascii=False)


HELPER_PROMPTS = {
    "chapters": (
        "Bạn tạo chapter cho video từ bản ghi lời thoại dưới đây. "
        "Trả về mỗi chapter một dòng, dạng 'MM:SS - Tiêu đề ngắn', theo "
        "thứ tự thời gian, không bịa thời gian ngoài bản ghi. Chỉ trả về "
        "danh sách chapter, không giải thích thêm."),
    "summary": (
        "Bạn tóm tắt nội dung video dưới đây thành một đoạn ngắn gọn, "
        "rõ ý chính, bằng tiếng Việt. Chỉ trả về đoạn tóm tắt."),
    "metadata": (
        "Bạn gợi ý metadata đăng video từ bản ghi dưới đây, bằng tiếng "
        "Việt. Trả về: một tiêu đề hấp dẫn, một đoạn mô tả ngắn, và "
        "10 hashtag liên quan (mỗi hashtag một dòng, bắt đầu bằng #). "
        "Không bịa thông tin ngoài bản ghi."),
}

HELPER_NAMES = ("chapters", "summary", "metadata")


def generate_helper(provider, helper, transcript_text):
    """Generate a text-only helper suggestion (never edits the timeline).

    The transcript is truncated to 12,000 characters so a long video
    does not blow up the provider's context window; the truncation is
    reported in the returned dict.
    """
    if helper not in HELPER_PROMPTS:
        raise AIError(f"Trợ giúp không hỗ trợ: {helper!r}. "
                      f"Chọn một trong: {', '.join(HELPER_NAMES)}.")
    if not transcript_text or not transcript_text.strip():
        raise AIError("Bản ghi trống, chưa có gì để tạo trợ giúp.")
    truncated = len(transcript_text) > 12000
    text = transcript_text[:12000]
    result = provider.generate_text(HELPER_PROMPTS[helper], text)
    return {"helper": helper, "result": result, "truncated": truncated}


PROVIDER_NAMES = ("ollama", "openai", "anthropic")
DEFAULT_MODELS = {
    "ollama": OllamaProvider.default_model,
    "openai": OpenAICompatibleProvider.default_model,
    "anthropic": AnthropicProvider.default_model,
}


def get_provider(name, settings=None):
    """Build a provider. ``settings`` may carry model/host/base_url/api_key.

    The API key is used only for this provider instance; it is never
    stored anywhere by this module.
    """
    settings = settings or {}
    if name == "ollama":
        return OllamaProvider(model=settings.get("model") or None,
                              host=settings.get("host") or settings.get("base_url") or None,
                              timeout=settings.get("timeout", 120))
    if name == "openai":
        return OpenAICompatibleProvider(
            model=settings.get("model") or None,
            base_url=settings.get("base_url") or None,
            api_key=settings.get("api_key") or None,
            timeout=settings.get("timeout", 120))
    if name == "anthropic":
        return AnthropicProvider(
            model=settings.get("model") or None,
            base_url=settings.get("base_url") or None,
            api_key=settings.get("api_key") or None,
            timeout=settings.get("timeout", 120))
    if name == "mock":
        return MockProvider(plan=settings.get("plan"))
    raise AIError(f"Nhà cung cấp AI không hỗ trợ: {name!r}. "
                  f"Chọn một trong: {', '.join(PROVIDER_NAMES)}.")
