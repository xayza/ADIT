"""FFmpeg export for ADIT (Phase 1).

Render model, kept deliberately simple and deterministic:
- Track 0 video/image clips play in start order on the main track.
  Gaps between them are filled with black video.
- Tracks >= 1 (video/image/text) are full-frame overlays on the main
  track, enabled only between the clip's start and end.
- Audio from video/audio clips, plus optional background music, is
  delayed onto the timeline and mixed.
- Text is rendered to a transparent PNG with Pillow (no fontfile
  guessing in FFmpeg drawtext) and overlaid.
- Effects that are honoured here: fade_in / fade_out / fade_both,
  zoom_in / zoom_out (video and image clips), speed 0.5-2.0, volume,
  mute. Zoom and fade are ignored for text overlays except fade,
  which fades the overlay's alpha channel.

On failure this raises RuntimeError carrying FFmpeg's stderr tail;
it never reports success without an output file on disk.
"""

import subprocess
import tempfile
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # pragma: no cover - Pillow is in requirements.txt
    Image = ImageDraw = ImageFont = None


def _has_audio(path):
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        return bool(out.stdout.strip())
    except Exception:
        return False


def _find_font():
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\arial.ttf",
    ]
    for cand in candidates:
        if Path(cand).exists():
            return cand
    return None


def render_text_png(path, text, font_size, color, position, width, height):
    """Render centred text onto a transparent W x H PNG. Returns path."""
    if Image is None:
        raise RuntimeError("Pillow is required to render text clips")
    font_path = _find_font()
    font = None
    if font_path and ImageFont is not None:
        try:
            font = ImageFont.truetype(font_path, font_size)
        except Exception:
            font = None
    if font is None:
        font = ImageFont.load_default()
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    lines = []
    for raw in str(text).split("\n"):
        line, words = "", raw.split()
        for word in words:
            trial = f"{line} {word}".strip()
            if draw.textlength(trial, font=font) <= width * 0.9 or not line:
                line = trial
            else:
                lines.append(line)
                line = word
        if line:
            lines.append(line)
    if not lines:
        lines = [""]
    spacing = max(4, font_size // 4)
    total_h = len(lines) * font_size + (len(lines) - 1) * spacing
    if position == "top":
        y = int(height * 0.08)
    elif position == "bottom":
        y = height - int(height * 0.08) - total_h
    else:
        y = (height - total_h) // 2
    stroke = max(2, font_size // 16)
    for line in lines:
        lw = draw.textlength(line, font=font)
        draw.text(((width - lw) / 2, y), line, font=font, fill=color,
                  stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
        y += font_size + spacing
    img.save(path, "PNG")
    return path


def _fade_filters(effect, duration):
    parts = []
    d = min(0.5, duration / 2) if duration > 0 else 0
    if d > 0:
        if effect in ("fade_in", "fade_both"):
            parts.append(f"fade=t=in:st=0:d={d:.3f}")
        if effect in ("fade_out", "fade_both"):
            parts.append(f"fade=t=out:st={duration - d:.3f}:d={d:.3f}")
    return parts


def _segment_filter(idx, clip, width, height, fps, is_image, is_text_png=False):
    """Filter chain for one video/image/text segment. Returns filter text
    (without the leading ``[idx:v]`` / trailing label)."""
    duration = clip["duration"]
    speed = clip["speed"]
    needed = duration * speed
    frames = max(1, round(duration * fps))
    chain = []
    if is_text_png:
        chain.append(f"trim=end={duration:.3f}")
        chain.append("setpts=PTS-STARTPTS")
        chain.append("format=rgba")
        d = min(0.5, duration / 2)
        if clip["effect"] in ("fade_in", "fade_both"):
            chain.append(f"fade=t=in:st=0:d={d:.3f}:alpha=1")
        if clip["effect"] in ("fade_out", "fade_both"):
            chain.append(f"fade=t=out:st={duration - d:.3f}:d={d:.3f}:alpha=1")
        return ",".join(chain)
    if is_image:
        chain.append(f"trim=end={duration:.3f}")
    else:
        chain.append(f"trim=start={clip['trim_in']:.3f}:end={clip['trim_in'] + needed:.3f}")
    chain.append("setpts=PTS-STARTPTS")
    if speed != 1.0:
        chain.append(f"setpts=PTS/{speed}")
    if clip["effect"] in ("zoom_in", "zoom_out"):
        chain.append(f"scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase")
        if clip["effect"] == "zoom_in":
            z = f"min(1+0.15*on/{frames},1.15)"
        else:
            z = f"max(1.15-0.15*on/{frames},1.0)"
        chain.append(
            f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d=1:s={width}x{height}:fps={fps}"
        )
    else:
        chain.append(f"scale={width}:{height}:force_original_aspect_ratio=increase")
        chain.append(f"crop={width}:{height}")
        chain.append(f"fps={fps}")
    chain.extend(_fade_filters(clip["effect"], duration))
    chain.append("format=yuv420p")
    return ",".join(chain)


def render_project(project, media_dir, output_path, width=None, height=None,
                   fps=None):
    """Render ``project`` to ``output_path``. Returns a result dict."""
    from timeline import project_duration  # local import: script-dir layout

    media_dir, output_path = Path(media_dir), Path(output_path)
    width = int(width or project.get("width", 1080))
    height = int(height or project.get("height", 1920))
    fps = int(fps or project.get("fps", 30))
    clips = project["clips"]
    total = project_duration(project)
    if total <= 0 or not clips:
        raise ValueError("cannot export an empty project: add at least one clip")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    media_map = {m["filename"]: m for m in project.get("media", [])}
    inputs = []   # list of argv lists, one per -i
    filters = []

    def add_input(argv):
        inputs.append(argv)
        return len(inputs) - 1

    def media_input(clip):
        src = media_dir / clip["source"]
        if not src.is_file():
            raise FileNotFoundError(f"clip source missing: {src}")
        if clip["type"] == "image":
            return add_input(["-loop", "1", "-framerate", str(fps), "-i", str(src)])
        return add_input(["-i", str(src)])

    main_clips = sorted(
        (c for c in clips if c["track"] == 0 and c["type"] in ("video", "image")),
        key=lambda c: c["start"],
    )
    overlay_clips = sorted(
        (c for c in clips if c["track"] >= 1 and c["type"] in ("video", "image", "text")),
        key=lambda c: c["start"],
    )

    main_labels = []
    with tempfile.TemporaryDirectory(prefix="adit_text_") as tmpdir:
        tmpdir = Path(tmpdir)
        cursor = 0.0
        seg = 0

        def gap_segment(gap):
            nonlocal seg
            idx = add_input(["-f", "lavfi", "-i",
                             f"color=c=black:s={width}x{height}:r={fps}:d={gap:.3f}"])
            label = f"g{seg}"
            seg += 1
            filters.append(f"[{idx}:v]fps={fps},format=yuv420p[{label}]")
            return label

        def clip_segment(clip):
            nonlocal seg
            if clip["type"] == "text":
                png = tmpdir / f"text_{clip['id']}.png"
                scaled_font = max(12, round(clip["font_size"] * width / 1080))
                render_text_png(png, clip["text"], scaled_font, clip["color"],
                                clip["position"], width, height)
                idx = add_input(["-loop", "1", "-framerate", str(fps), "-i", str(png)])
                label = f"s{seg}"
                seg += 1
                chain = _segment_filter(idx, clip, width, height, fps,
                                        is_image=True, is_text_png=True)
                filters.append(f"[{idx}:v]{chain}[{label}]")
                return label
            idx = media_input(clip)
            label = f"s{seg}"
            seg += 1
            chain = _segment_filter(idx, clip, width, height, fps,
                                    is_image=(clip["type"] == "image"))
            filters.append(f"[{idx}:v]{chain}[{label}]")
            return label

        for clip in main_clips:
            if clip["start"] > cursor + 1e-6:
                main_labels.append(gap_segment(clip["start"] - cursor))
            main_labels.append(clip_segment(clip))
            cursor = clip["start"] + clip["duration"]
        if cursor < total - 1e-6:
            main_labels.append(gap_segment(total - cursor))
        if not main_labels:
            main_labels.append(gap_segment(total))

        if len(main_labels) == 1:
            main_label = main_labels[0]
        else:
            joined = "".join(f"[{lab}]" for lab in main_labels)
            filters.append(f"{joined}concat=n={len(main_labels)}:v=1:a=0[mainv]")
            main_label = "mainv"

        # Overlays, in start order.
        base = main_label
        for i, clip in enumerate(overlay_clips):
            label = clip_segment(clip)
            out = f"vout{i}"
            filters.append(
                f"[{base}][{label}]overlay=enable='between(t,{clip['start']:.3f},"
                f"{clip['start'] + clip['duration']:.3f})'[{out}]"
            )
            base = out
        final_video = base

        # Project-level global edits (real FFmpeg filters, not AI).
        # Applied once to the composited frame, not per clip, so the
        # export stays a single FFmpeg chain.
        global_edits = project.get("global_edits") or {}
        video_chain = []
        if global_edits.get("color") == "better":
            # eq preset: slight contrast / saturation / brightness lift.
            video_chain.append("eq=contrast=1.08:brightness=0.03:saturation=1.12")
        if global_edits.get("sharpen"):
            video_chain.append("unsharp=5:5:0.6:5:5:0.0")
        if video_chain:
            filters.append(f"[{final_video}]{','.join(video_chain)}[globalv]")
            final_video = "globalv"

        # Audio.
        audio_labels = []
        for clip in clips:
            if clip["type"] not in ("video", "audio") or clip.get("muted"):
                continue
            if float(clip.get("volume", 1.0)) <= 0:
                continue
            src = media_dir / clip["source"]
            if not src.is_file() or not _has_audio(src):
                continue
            idx = media_input(clip)
            needed = clip["duration"] * clip["speed"]
            chain = (f"[{idx}:a]atrim=start={clip['trim_in']:.3f}:"
                     f"end={clip['trim_in'] + needed:.3f},asetpts=PTS-STARTPTS")
            if clip["speed"] != 1.0:
                chain += f",atempo={clip['speed']}"
            chain += f",volume={clip['volume']}"
            chain += f",adelay={int(round(clip['start'] * 1000))}|{int(round(clip['start'] * 1000))}"
            chain += ",apad"
            label = f"a{len(audio_labels)}"
            filters.append(f"{chain}[{label}]")
            audio_labels.append(label)

        music = project.get("background_music")
        if music:
            msrc = media_dir / music["source"]
            if msrc.is_file():
                idx = add_input(["-stream_loop", "-1", "-i", str(msrc)])
                label = f"a{len(audio_labels)}"
                filters.append(
                    f"[{idx}:a]atrim=0:{total:.3f},asetpts=PTS-STARTPTS,"
                    f"volume={music['volume']}[{label}]"
                )
                audio_labels.append(label)

        if audio_labels:
            joined = "".join(f"[{lab}]" for lab in audio_labels)
            filters.append(
                f"{joined}amix=inputs={len(audio_labels)}:duration=longest:"
                f"normalize=0,atrim=0:{total:.3f},asetpts=PTS-STARTPTS[finala]"
            )
            final_audio = "finala"
        else:
            idx = add_input(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"])
            filters.append(f"[{idx}:a]atrim=0:{total:.3f},asetpts=PTS-STARTPTS[finala]")
            final_audio = "finala"

        # Global loudness normalisation (single-pass loudnorm) on the
        # final mix only; it never touches the per-clip audio above.
        if global_edits.get("volume_norm"):
            filters.append("[finala]loudnorm=I=-16:TP=-1.5:LRA=11[globala]")
            final_audio = "globala"

        cmd = ["ffmpeg", "-y"]
        for argv in inputs:
            cmd.extend(argv)
        cmd += ["-filter_complex", ";".join(filters),
                "-map", f"[{final_video}]", "-map", f"[{final_audio}]",
                "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
                "-r", str(fps), "-c:a", "aac", "-b:a", "128k",
                "-t", f"{total:.3f}", str(output_path)]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if result.returncode != 0 or not output_path.exists() or output_path.stat().st_size == 0:
            tail = (result.stderr or "")[-2000:]
            raise RuntimeError(f"FFmpeg export failed (exit {result.returncode}):\n{tail}")

    return {
        "output": str(output_path),
        "duration": total,
        "width": width,
        "height": height,
        "fps": fps,
        "global_edits": global_edits,
    }
