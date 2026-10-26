"""ADIT timeline model (Phase 1, manual editing only).

The project is a plain JSON document. Every timeline operation mutates
this model; the user's original media files are never modified.

A clip::

    {
        "id": "a1b2c3",
        "type": "video" | "image" | "audio" | "text",
        "source": "clip.mp4",          # filename inside the project media folder
        "track": 0,                  # 0 = main track, >=1 = overlay tracks
        "start": 0.0,                # seconds on the project timeline
        "duration": 4.0,             # seconds on the project timeline
        "trim_in": 0.0,              # seconds into the source media
        "speed": 1.0,                # 0.5 - 2.0
        "volume": 1.0,               # 0.0 - 1.5
        "muted": false,
        "effect": "none",            # none|fade_in|fade_out|fade_both|zoom_in|zoom_out
        "text": "",                  # text clips only
        "font_size": 48,             # text clips only, pixels at 1080px width
        "color": "#FFFFFF",          # text clips only
        "position": "center",       # text clips only: center|top|bottom
    }

Rules enforced here (and re-checked on load):
- video/image/text clips on the same track may not overlap (audio may);
- a media clip may not read past the end of its source;
- images and text have trim_in == 0;
- speed, volume, effect, colour and position are range/enum checked.
"""

import json
import re
import uuid
from pathlib import Path

CLIP_TYPES = ("video", "image", "audio", "text")
EFFECTS = ("none", "fade_in", "fade_out", "fade_both", "zoom_in", "zoom_out")
POSITIONS = ("center", "top", "bottom")
_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

_EPS = 1e-6


GLOBAL_COLORS = ("none", "better")


def default_global_edits():
    """Project-level global edits (real FFmpeg filters, not AI).

    color="better": a documented eq preset (slight contrast/saturation/
    brightness). volume_norm: loudnorm on the final mix. sharpen:
    an unsharp filter. All default to off and are reversible.
    """
    return {"color": "none", "volume_norm": False, "sharpen": False}


def validate_global_edits(edits):
    if not isinstance(edits, dict):
        raise ValueError("global_edits must be an object")
    if edits.get("color", "none") not in GLOBAL_COLORS:
        raise ValueError(f"unknown global color preset: {edits.get('color')!r}")
    for key in ("volume_norm", "sharpen"):
        if not isinstance(edits.get(key, False), bool):
            raise ValueError(f"global edit {key} must be true/false")
    return edits


def set_global_edits(project, patch):
    merged = default_global_edits()
    merged.update(project.get("global_edits") or {})
    if patch:
        merged.update(patch)
    validate_global_edits(merged)
    project["global_edits"] = merged
    return merged


def reset_global_edits(project):
    project["global_edits"] = default_global_edits()
    return project["global_edits"]


def new_project(name="ADIT Project"):
    return {
        "name": name,
        "width": 1080,
        "height": 1920,
        "fps": 30,
        "clips": [],
        "media": [],
        "background_music": None,
        "global_edits": default_global_edits(),
    }


def media_by_filename(project):
    return {m["filename"]: m for m in project.get("media", [])}


def project_duration(project):
    """Total timeline length in seconds, computed from the model."""
    if not project["clips"]:
        return 0.0
    return round(max(c["start"] + c["duration"] for c in project["clips"]), 3)


def _check_overlap(project, clip, exclude_id=None):
    if clip["type"] == "audio":
        return
    start, end = clip["start"], clip["start"] + clip["duration"]
    for other in project["clips"]:
        if other["id"] == exclude_id or other["type"] == "audio":
            continue
        if other["track"] != clip["track"]:
            continue
        o_start, o_end = other["start"], other["start"] + other["duration"]
        if start < o_end - _EPS and o_start < end - _EPS:
            raise ValueError(
                f"clip overlaps clip {other['id']} on track {clip['track']} "
                f"({o_start:.2f}s-{o_end:.2f}s)"
            )


def validate_clip(project, clip, check_overlap=True):
    errors = []
    if clip.get("type") not in CLIP_TYPES:
        errors.append(f"unknown clip type: {clip.get('type')!r}")
    if not isinstance(clip.get("track"), int) or clip.get("track", -1) < 0:
        errors.append("track must be an integer >= 0")
    if not isinstance(clip.get("start"), (int, float)) or clip["start"] < 0:
        errors.append("start must be >= 0")
    if not isinstance(clip.get("duration"), (int, float)) or clip["duration"] <= 0:
        errors.append("duration must be > 0")
    if not isinstance(clip.get("trim_in"), (int, float)) or clip["trim_in"] < 0:
        errors.append("trim_in must be >= 0")
    if not 0.5 <= float(clip.get("speed", 1.0)) <= 2.0:
        errors.append("speed must be between 0.5 and 2.0")
    if not 0.0 <= float(clip.get("volume", 1.0)) <= 1.5:
        errors.append("volume must be between 0.0 and 1.5")
    if clip.get("effect", "none") not in EFFECTS:
        errors.append(f"unknown effect: {clip.get('effect')!r}")
    if clip.get("type") in ("image", "text") and clip.get("trim_in", 0) != 0:
        errors.append("image and text clips must have trim_in == 0")
    if clip.get("type") == "text":
        if not str(clip.get("text", "")).strip():
            errors.append("text clips need non-empty text")
        if not 12 <= int(clip.get("font_size", 48)) <= 200:
            errors.append("font_size must be between 12 and 200")
        if not _COLOR_RE.match(str(clip.get("color", "#FFFFFF"))):
            errors.append("color must be a #RRGGBB hex value")
        if clip.get("position", "center") not in POSITIONS:
            errors.append(f"unknown position: {clip.get('position')!r}")
    elif clip.get("type") in ("video", "audio"):
        media = media_by_filename(project).get(clip.get("source", ""))
        if media is None:
            errors.append(f"source not in project media: {clip.get('source')!r}")
        elif media.get("duration"):
            needed = clip["trim_in"] + clip["duration"] * float(clip.get("speed", 1.0))
            if needed > media["duration"] + 0.05:
                errors.append(
                    f"clip reads to {needed:.2f}s but source "
                    f"{clip['source']} is only {media['duration']:.2f}s long"
                )
    if errors:
        raise ValueError("; ".join(errors))
    if check_overlap:
        _check_overlap(project, clip, exclude_id=clip.get("id"))


def add_clip(project, fields, media=None):
    """Append a clip. ``media`` is a media entry dict (optional, for checks)."""
    clip = {
        "id": uuid.uuid4().hex[:12],
        "type": fields["type"],
        "source": fields.get("source", ""),
        "track": int(fields.get("track", 0)),
        "start": float(fields.get("start", 0.0)),
        "duration": float(fields["duration"]),
        "trim_in": float(fields.get("trim_in", 0.0)),
        "speed": float(fields.get("speed", 1.0)),
        "volume": float(fields.get("volume", 1.0)),
        "muted": bool(fields.get("muted", False)),
        "effect": fields.get("effect", "none"),
        "text": fields.get("text", ""),
        "font_size": int(fields.get("font_size", 48)),
        "color": fields.get("color", "#FFFFFF"),
        "position": fields.get("position", "center"),
    }
    if media is not None and clip["source"]:
        project.setdefault("media", [])
        if media["filename"] not in media_by_filename(project):
            project["media"].append(media)
    validate_clip(project, clip)
    project["clips"].append(clip)
    project["clips"].sort(key=lambda c: (c["track"], c["start"]))
    return clip


def get_clip(project, clip_id):
    for clip in project["clips"]:
        if clip["id"] == clip_id:
            return clip
    raise KeyError(f"no clip with id {clip_id!r}")


def update_clip(project, clip_id, patch):
    clip = get_clip(project, clip_id)
    merged = dict(clip)
    for key in ("source", "track", "start", "duration", "trim_in", "speed",
                "volume", "muted", "effect", "text", "font_size", "color",
                "position"):
        if key in patch:
            merged[key] = patch[key]
    if "track" in patch:
        merged["track"] = int(merged["track"])
    for key in ("start", "duration", "trim_in", "speed", "volume"):
        if key in merged:
            merged[key] = float(merged[key])
    if "font_size" in merged:
        merged["font_size"] = int(merged["font_size"])
    validate_clip(project, merged)
    clip.update(merged)
    project["clips"].sort(key=lambda c: (c["track"], c["start"]))
    return clip


def delete_clip(project, clip_id):
    clip = get_clip(project, clip_id)
    project["clips"].remove(clip)
    return clip


def split_clip(project, clip_id, at):
    """Split a clip at project time ``at``. Returns (first, second)."""
    clip = get_clip(project, clip_id)
    if not (clip["start"] < at < clip["start"] + clip["duration"]):
        raise ValueError(
            f"split point {at} is outside clip "
            f"({clip['start']:.2f}s-{clip['start'] + clip['duration']:.2f}s)"
        )
    offset = at - clip["start"]
    second_fields = dict(clip)
    second_fields.pop("id", None)
    second_fields["start"] = at
    second_fields["duration"] = clip["duration"] - offset
    if clip["type"] in ("video", "audio"):
        second_fields["trim_in"] = clip["trim_in"] + offset * clip["speed"]
    # Temporarily remove the original so the shortened first half passes
    # the overlap check, then add both halves back.
    project["clips"].remove(clip)
    first = dict(clip)
    first["duration"] = offset
    validate_clip(project, first, check_overlap=False)
    project["clips"].append(first)
    second = add_clip(project, second_fields)
    project["clips"].sort(key=lambda c: (c["track"], c["start"]))
    return first, second


def move_clip(project, clip_id, track, start):
    return update_clip(project, clip_id, {"track": int(track), "start": float(start)})


def reorder_track(project, track, ids):
    """Place the given clips, in order, on ``track`` starting at 0s.

    ``ids`` must be exactly the clips currently on that track (audio
    clips are excluded from reordering: they are mixed, not sequenced).
    """
    track_clips = [c for c in project["clips"]
                   if c["track"] == track and c["type"] != "audio"]
    if sorted(ids) != sorted(c["id"] for c in track_clips):
        raise ValueError("reorder ids must match exactly the clips on that track")
    by_id = {c["id"]: c for c in track_clips}
    cursor = 0.0
    for clip_id in ids:
        clip = by_id[clip_id]
        clip["start"] = round(cursor, 3)
        cursor += clip["duration"]
    project["clips"].sort(key=lambda c: (c["track"], c["start"]))
    return track_clips


def set_background_music(project, source, volume=0.15):
    if source is None:
        project["background_music"] = None
        return None
    media = media_by_filename(project).get(source)
    if media is None or media["type"] != "audio":
        raise ValueError(f"background music must be an audio file in media: {source!r}")
    if not 0.0 <= float(volume) <= 0.30:
        raise ValueError("background music volume must be between 0.0 and 0.30")
    project["background_music"] = {"source": source, "volume": float(volume)}
    return project["background_music"]


def validate_project(project):
    for key in ("clips", "media"):
        if key not in project:
            raise ValueError(f"project is missing {key!r}")
    # Old projects predate global edits; normalise instead of failing.
    if not isinstance(project.get("global_edits"), dict):
        project["global_edits"] = default_global_edits()
    else:
        merged = default_global_edits()
        merged.update(project["global_edits"])
        validate_global_edits(merged)
        project["global_edits"] = merged
    seen = set()
    for clip in project["clips"]:
        if clip["id"] in seen:
            raise ValueError(f"duplicate clip id {clip['id']!r}")
        seen.add(clip["id"])
        validate_clip(project, clip, check_overlap=False)
    # Overlap check needs the full list; run it clip by clip.
    others = project["clips"]
    project["clips"] = []
    try:
        for clip in others:
            validate_clip(project, clip)
            project["clips"].append(clip)
    finally:
        project["clips"] = others
    return project


def save_project(project, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(project, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return path


def load_project(path):
    project = json.loads(Path(path).read_text(encoding="utf-8"))
    return validate_project(project)
