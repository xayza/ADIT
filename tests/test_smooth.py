"""Smoothness tests: waveform cache, global edits, timeline move rules,
and a real render with global edits applied.

No network, no browser: the UI (drag/zoom/scrub) is exercised only
through the same model + API rules it calls, so these tests prove the
behaviour the UI relies on rather than mouse events themselves.
"""

import json
import math
import struct
import subprocess
import sys
import tempfile
import unittest
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import media as media_mod
import render as render_mod
import timeline as tl


def make_tone_wav(path, seconds=2.0, freq=440.0, rate=8000):
    frames = b"".join(
        struct.pack("<h", int(12000 * math.sin(2 * math.pi * freq * i / rate)))
        for i in range(int(seconds * rate)))
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(frames)


def run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise AssertionError(f"{cmd}\n{result.stderr[-1000:]}")


class TestWaveform(unittest.TestCase):
    def test_peaks_and_cache_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "tone.wav"
            make_tone_wav(wav)
            peaks, cached = media_mod.generate_waveform(wav, buckets=60)
            self.assertEqual(len(peaks), 60)
            self.assertTrue(all(0.0 <= p <= 1.0 for p in peaks))
            self.assertGreater(max(peaks), 0.5)
            cache = media_mod.waveform_cache_path(wav)
            self.assertTrue(cache.is_file())
            peaks2, cached2 = media_mod.generate_waveform(wav, buckets=60)
            self.assertTrue(cached2)
            self.assertEqual(peaks, peaks2)

    def test_waveform_failure_is_empty_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nope.mp3"
            peaks, cached, error = media_mod.waveform_or_empty(missing)
            self.assertEqual(peaks, [])
            self.assertFalse(cached)
            self.assertIsNotNone(error)


class TestGlobalEdits(unittest.TestCase):
    def test_defaults_and_reset(self):
        p = tl.new_project()
        self.assertEqual(p["global_edits"],
                         {"color": "none", "volume_norm": False, "sharpen": False})
        tl.set_global_edits(p, {"color": "better", "sharpen": True})
        self.assertEqual(p["global_edits"]["color"], "better")
        self.assertTrue(p["global_edits"]["sharpen"])
        self.assertEqual(tl.reset_global_edits(p),
                         {"color": "none", "volume_norm": False, "sharpen": False})

    def test_unknown_preset_rejected_and_old_project_loads(self):
        p = tl.new_project()
        with self.assertRaises(ValueError):
            tl.set_global_edits(p, {"color": "neon"})
        # Old project.json files predate global_edits: they must load,
        # normalised to the defaults, not fail.
        old = tl.new_project()
        del old["global_edits"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "project.json"
            path.write_text(json.dumps(old), encoding="utf-8")
            loaded = tl.load_project(path)
        self.assertEqual(loaded["global_edits"],
                         {"color": "none", "volume_norm": False, "sharpen": False})


class TestTimelineMove(unittest.TestCase):
    def _project(self):
        p = tl.new_project()
        p["media"].append({"filename": "clip.mp4", "type": "video",
                           "duration": 10.0, "width": 640, "height": 360})
        return p

    def test_move_into_overlap_rejected_and_original_unchanged(self):
        p = self._project()
        a = tl.add_clip(p, {"type": "video", "source": "clip.mp4",
                            "track": 0, "start": 0, "duration": 2})
        b = tl.add_clip(p, {"type": "video", "source": "clip.mp4",
                            "track": 0, "start": 2, "duration": 2})
        with self.assertRaises(ValueError):
            tl.move_clip(p, b["id"], 0, 1.0)  # would overlap clip a
        self.assertEqual(tl.get_clip(p, b["id"])["start"], 2.0)
        # A legal drag (the UI's drop path) succeeds with one call.
        moved = tl.move_clip(p, b["id"], 0, 4.0)
        self.assertEqual(moved["start"], 4.0)
        self.assertIsNotNone(a)


class TestGlobalEditRender(unittest.TestCase):
    def test_render_with_all_global_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            media_dir = tmp / "media"
            media_dir.mkdir()
            video = tmp / "sample.mp4"
            run(["ffmpeg", "-y", "-v", "error",
                 "-f", "lavfi", "-i", "testsrc=size=640x360:rate=15:duration=4",
                 "-f", "lavfi", "-i", "sine=frequency=440:duration=4",
                 "-c:v", "libx264", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-shortest", str(video)])
            project = tl.new_project()
            project["media"].append(media_mod.import_media(video, media_dir))
            tl.add_clip(project, {"type": "video", "source": "sample.mp4",
                                  "track": 0, "start": 0, "duration": 3})
            tl.set_global_edits(project, {"color": "better",
                                          "volume_norm": True,
                                          "sharpen": True})
            out = tmp / "out.mp4"
            result = render_mod.render_project(
                project, media_dir, out, width=320, height=180, fps=15)
            self.assertTrue(out.exists())
            self.assertGreater(out.stat().st_size, 1000)
            self.assertEqual(result["duration"], 3.0)
            self.assertEqual(result["global_edits"]["color"], "better")
            self.assertTrue(result["global_edits"]["volume_norm"])
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries",
                 "stream=codec_type", "-show_entries", "format=duration",
                 "-of", "json", str(out)],
                capture_output=True, text=True, timeout=30)
            data = json.loads(probe.stdout)
            self.assertIn("video", {s["codec_type"] for s in data["streams"]})
            self.assertIn("audio", {s["codec_type"] for s in data["streams"]})
            self.assertGreater(float(data["format"]["duration"]), 2.5)


if __name__ == "__main__":
    unittest.main()
