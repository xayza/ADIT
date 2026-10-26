"""Real FFmpeg render tests for ADIT (small draft size, fast).

Generates sample media with FFmpeg/Pillow, builds a timeline with a
video clip (fade + speed), an image clip (zoom), a text overlay and
background music, renders it, and verifies the output with FFprobe.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import media as media_mod
import render as render_mod
import timeline as tl


def run(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise AssertionError(f"{cmd}\n{result.stderr[-1000:]}")


def ffprobe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "stream=codec_type,codec_name,width,height",
         "-show_entries", "format=duration",
         "-of", "json", str(path)],
        capture_output=True, text=True, timeout=30)
    return json.loads(out.stdout)


class TestRender(unittest.TestCase):
    def test_render_timeline_with_effects_text_and_music(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            media_dir = tmp / "media"
            media_dir.mkdir()
            # Sample video: 6s colour bars + tone.
            video = tmp / "sample.mp4"
            run(["ffmpeg", "-y", "-v", "error",
                 "-f", "lavfi", "-i", "testsrc=size=640x360:rate=15:duration=6",
                 "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
                 "-c:v", "libx264", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-shortest", str(video)])
            # Sample image via Pillow.
            from PIL import Image
            img = tmp / "pic.png"
            Image.new("RGB", (640, 360), (200, 60, 60)).save(img)
            # Sample music tone.
            music = tmp / "music.wav"
            run(["ffmpeg", "-y", "-v", "error",
                 "-f", "lavfi", "-i", "sine=frequency=880:duration=10",
                 str(music)])

            project = tl.new_project()
            for src in (video, img, music):
                project["media"].append(media_mod.import_media(src, media_dir))
            tl.add_clip(project, {"type": "video", "source": "sample.mp4",
                                  "track": 0, "start": 0, "duration": 3,
                                  "effect": "fade_both", "speed": 1.0})
            tl.add_clip(project, {"type": "image", "source": "pic.png",
                                  "track": 0, "start": 3, "duration": 2,
                                  "effect": "zoom_in"})
            tl.add_clip(project, {"type": "text", "track": 1, "start": 0.5,
                                  "duration": 2, "text": "ADIT test",
                                  "position": "bottom"})
            tl.set_background_music(project, "music.wav", 0.15)

            out = tmp / "out.mp4"
            result = render_mod.render_project(
                project, media_dir, out, width=320, height=180, fps=15)
            self.assertTrue(out.exists())
            self.assertGreater(out.stat().st_size, 1000)
            probe = ffprobe(out)
            streams = {s["codec_type"] for s in probe["streams"]}
            self.assertIn("video", streams)
            self.assertIn("audio", streams)
            vstream = [s for s in probe["streams"] if s["codec_type"] == "video"][0]
            self.assertEqual((vstream["width"], vstream["height"]), (320, 180))
            self.assertGreater(float(probe["format"]["duration"]), 4.0)
            self.assertEqual(result["duration"], 5.0)

    def test_empty_project_refuses_to_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                render_mod.render_project(
                    tl.new_project(), Path(tmp), Path(tmp) / "x.mp4",
                    width=320, height=180, fps=15)


if __name__ == "__main__":
    unittest.main()
