"""Unit tests for the ADIT timeline model (no FFmpeg, no network)."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import timeline as tl


def project_with_media():
    project = tl.new_project()
    project["media"].append(
        {"filename": "clip.mp4", "type": "video", "duration": 10.0,
         "width": 640, "height": 360})
    project["media"].append(
        {"filename": "song.mp3", "type": "audio", "duration": 30.0,
         "width": None, "height": None})
    return project


class TestTimeline(unittest.TestCase):
    def test_add_and_duration(self):
        p = project_with_media()
        c1 = tl.add_clip(p, {"type": "video", "source": "clip.mp4",
                             "track": 0, "start": 0, "duration": 4})
        tl.add_clip(p, {"type": "video", "source": "clip.mp4",
                        "track": 0, "start": 4, "duration": 3, "trim_in": 2})
        self.assertEqual(c1["effect"], "none")
        self.assertEqual(tl.project_duration(p), 7.0)

    def test_overlap_rejected(self):
        p = project_with_media()
        tl.add_clip(p, {"type": "video", "source": "clip.mp4",
                        "track": 0, "start": 0, "duration": 4})
        with self.assertRaises(ValueError):
            tl.add_clip(p, {"type": "video", "source": "clip.mp4",
                            "track": 0, "start": 3, "duration": 2})
        # Touching is fine, and another track is fine.
        tl.add_clip(p, {"type": "video", "source": "clip.mp4",
                        "track": 0, "start": 4, "duration": 2})
        tl.add_clip(p, {"type": "video", "source": "clip.mp4",
                        "track": 1, "start": 1, "duration": 2})

    def test_trim_past_source_rejected(self):
        p = project_with_media()
        with self.assertRaises(ValueError):
            tl.add_clip(p, {"type": "video", "source": "clip.mp4",
                            "track": 0, "start": 0, "duration": 6, "trim_in": 5})
        # Speed consumes source faster: 3s at 2x needs 6s of source.
        with self.assertRaises(ValueError):
            tl.add_clip(p, {"type": "video", "source": "clip.mp4",
                            "track": 0, "start": 0, "duration": 3,
                            "trim_in": 5, "speed": 2.0})

    def test_invalid_effect_speed_volume(self):
        p = project_with_media()
        for patch in ({"effect": "spin"}, {"speed": 3.0}, {"volume": 2.0},
                      {"duration": 0}, {"start": -1}):
            fields = {"type": "video", "source": "clip.mp4", "track": 0,
                      "start": 0, "duration": 2}
            fields.update(patch)
            with self.assertRaises(ValueError, msg=str(patch)):
                tl.add_clip(p, fields)

    def test_text_validation(self):
        p = tl.new_project()
        with self.assertRaises(ValueError):
            tl.add_clip(p, {"type": "text", "track": 1, "start": 0,
                            "duration": 2, "text": "  "})
        with self.assertRaises(ValueError):
            tl.add_clip(p, {"type": "text", "track": 1, "start": 0,
                            "duration": 2, "text": "Hi", "color": "red"})
        clip = tl.add_clip(p, {"type": "text", "track": 1, "start": 0,
                               "duration": 2, "text": "Xin chao",
                               "position": "bottom", "font_size": 64})
        self.assertEqual(clip["position"], "bottom")

    def test_split(self):
        p = project_with_media()
        clip = tl.add_clip(p, {"type": "video", "source": "clip.mp4",
                               "track": 0, "start": 0, "duration": 6})
        first, second = tl.split_clip(p, clip["id"], 2.5)
        self.assertEqual(first["duration"], 2.5)
        self.assertEqual(second["start"], 2.5)
        self.assertEqual(second["duration"], 3.5)
        self.assertEqual(second["trim_in"], 2.5)
        self.assertEqual(tl.project_duration(p), 6.0)
        with self.assertRaises(ValueError):
            tl.split_clip(p, first["id"], 0)  # at the clip edge

    def test_delete_move_reorder(self):
        p = project_with_media()
        a = tl.add_clip(p, {"type": "video", "source": "clip.mp4",
                            "track": 0, "start": 0, "duration": 2})
        b = tl.add_clip(p, {"type": "video", "source": "clip.mp4",
                            "track": 0, "start": 2, "duration": 2})
        tl.reorder_track(p, 0, [b["id"], a["id"]])
        self.assertEqual(tl.get_clip(p, b["id"])["start"], 0.0)
        self.assertEqual(tl.get_clip(p, a["id"])["start"], 2.0)
        with self.assertRaises(ValueError):
            tl.reorder_track(p, 0, [a["id"]])  # incomplete id list
        tl.delete_clip(p, a["id"])
        self.assertEqual(len(p["clips"]), 1)
        tl.move_clip(p, b["id"], 1, 5.0)
        self.assertEqual(tl.get_clip(p, b["id"])["track"], 1)

    def test_background_music_rules(self):
        p = project_with_media()
        self.assertIsNotNone(tl.set_background_music(p, "song.mp3", 0.2))
        with self.assertRaises(ValueError):
            tl.set_background_music(p, "song.mp3", 0.5)  # capped at 0.30
        with self.assertRaises(ValueError):
            tl.set_background_music(p, "clip.mp4", 0.1)  # not audio
        self.assertIsNone(tl.set_background_music(p, None))

    def test_save_load_roundtrip(self):
        p = project_with_media()
        tl.add_clip(p, {"type": "video", "source": "clip.mp4",
                        "track": 0, "start": 0, "duration": 3,
                        "effect": "fade_both"})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "project.json"
            tl.save_project(p, path)
            loaded = tl.load_project(path)
        self.assertEqual(loaded["clips"][0]["effect"], "fade_both")
        self.assertEqual(tl.project_duration(loaded), 3.0)


if __name__ == "__main__":
    unittest.main()
