"""Tests for the ADIT core-feature batch: manual undo/redo, cross-track
drag (model level), split at playhead, copy/paste, projects, audio
fades (validation + a real FFmpeg render), and autosave via the manual
mutation helper.

Server-level helpers are exercised with PROJECTS_ROOT / PROJECT_DIR
monkeypatched to a TemporaryDirectory, so these tests never touch the
real projects/default/ folder in the workspace.
"""

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import render as render_mod
import timeline as tl

import server as srv


def project_with_media():
    project = tl.new_project()
    project["media"].append(
        {"filename": "clip.mp4", "type": "video", "duration": 10.0,
         "width": 640, "height": 360})
    project["media"].append(
        {"filename": "song.mp3", "type": "audio", "duration": 30.0,
         "width": None, "height": None})
    return project


class ServerSandbox:
    """Temporarily point the server at a temp project root."""

    def __init__(self, test):
        self.test = test
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def __enter__(self):
        self.orig = {
            "root": srv.PROJECTS_ROOT,
            "dir": srv.PROJECT_DIR,
            "media": srv.MEDIA_DIR,
            "output": srv.OUTPUT_DIR,
            "file": srv.PROJECT_FILE,
            "active": srv.ACTIVE_PROJECT_NAME,
            "project": srv._snapshot_project(),
            "undo": copy.deepcopy(srv.MANUAL_UNDO),
            "redo": copy.deepcopy(srv.MANUAL_REDO),
        }
        srv.PROJECTS_ROOT = self.root
        srv._set_active_dirs("default")
        srv.PROJECT.clear()
        srv.PROJECT.update(tl.new_project())
        srv.MANUAL_UNDO.clear()
        srv.MANUAL_REDO.clear()
        return self

    def __exit__(self, *exc):
        srv.PROJECTS_ROOT = self.orig["root"]
        srv.PROJECT_DIR = self.orig["dir"]
        srv.MEDIA_DIR = self.orig["media"]
        srv.OUTPUT_DIR = self.orig["output"]
        srv.PROJECT_FILE = self.orig["file"]
        srv.ACTIVE_PROJECT_NAME = self.orig["active"]
        srv.PROJECT.clear()
        srv.PROJECT.update(self.orig["project"])
        srv.MANUAL_UNDO.clear()
        srv.MANUAL_UNDO.extend(self.orig["undo"])
        srv.MANUAL_REDO.clear()
        srv.MANUAL_REDO.extend(self.orig["redo"])
        self.tmp.cleanup()
        return False


class TestManualUndoRedo(unittest.TestCase):
    def test_undo_redo_and_new_edit_clears_redo(self):
        with ServerSandbox(self):
            srv.PROJECT.update(project_with_media())
            clip = srv._apply_manual(lambda: tl.add_clip(
                srv.PROJECT, {"type": "video", "source": "clip.mp4",
                              "track": 0, "start": 0, "duration": 3}))
            srv._apply_manual(lambda: tl.update_clip(
                srv.PROJECT, clip["id"], {"speed": 1.5}))
            self.assertEqual(tl.get_clip(srv.PROJECT, clip["id"])["speed"], 1.5)
            srv.history_undo()
            self.assertEqual(tl.get_clip(srv.PROJECT, clip["id"])["speed"], 1.0)
            srv.history_redo()
            self.assertEqual(tl.get_clip(srv.PROJECT, clip["id"])["speed"], 1.5)
            # A new edit after an undo clears the redo stack.
            srv.history_undo()
            srv._apply_manual(lambda: tl.update_clip(
                srv.PROJECT, clip["id"], {"volume": 0.5}))
            with self.assertRaises(ValueError):
                srv.history_redo()
            # Undo all the way back to the empty timeline, then redo once.
            srv.history_undo()  # volume back to 1.0
            srv.history_undo()  # clip removed
            self.assertEqual(len(srv.PROJECT["clips"]), 0)
            srv.history_redo()
            self.assertEqual(len(srv.PROJECT["clips"]), 1)
            with self.assertRaises(ValueError):
                srv.history_undo()
                srv.history_undo()
                srv.history_undo()  # stack drained

    def test_failed_edit_pushes_nothing_and_changes_nothing(self):
        with ServerSandbox(self):
            srv.PROJECT.update(project_with_media())
            clip = srv._apply_manual(lambda: tl.add_clip(
                srv.PROJECT, {"type": "video", "source": "clip.mp4",
                              "track": 0, "start": 0, "duration": 3}))
            before = srv._snapshot_project()
            with self.assertRaises(ValueError):
                srv._apply_manual(lambda: tl.update_clip(
                    srv.PROJECT, clip["id"], {"speed": 9.0}))
            self.assertEqual(srv.PROJECT, before)
            # Only the successful add is on the undo stack.
            self.assertEqual(len(srv.MANUAL_UNDO), 1)

    def test_manual_mutation_autosaves(self):
        with ServerSandbox(self) as sb:
            srv.PROJECT.update(project_with_media())
            srv.PROJECT_FILE = sb.root / "project.json"
            srv._apply_manual(lambda: tl.add_clip(
                srv.PROJECT, {"type": "video", "source": "clip.mp4",
                              "track": 0, "start": 0, "duration": 2}))
            saved = json.loads(srv.PROJECT_FILE.read_text(encoding="utf-8"))
            self.assertEqual(len(saved["clips"]), 1)


class TestCrossTrackAndSplit(unittest.TestCase):
    def test_cross_track_move_overlap_and_free(self):
        p = project_with_media()
        a = tl.add_clip(p, {"type": "video", "source": "clip.mp4",
                            "track": 0, "start": 0, "duration": 2})
        tl.add_clip(p, {"type": "video", "source": "clip.mp4",
                        "track": 1, "start": 1, "duration": 2})
        # Moving onto track 1 at 1s would overlap the track-1 clip.
        with self.assertRaises(ValueError):
            tl.move_clip(p, a["id"], 1, 1.0)
        # Moving onto track 1 at 3s is free.
        moved = tl.move_clip(p, a["id"], 1, 3.0)
        self.assertEqual((moved["track"], moved["start"]), (1, 3.0))

    def test_clip_covering_and_split_at_playhead(self):
        p = project_with_media()
        clip = tl.add_clip(p, {"type": "video", "source": "clip.mp4",
                               "track": 0, "start": 0, "duration": 6})
        covering = tl.clip_covering(p, 2.5)
        self.assertEqual(covering["id"], clip["id"])
        # Edges do not count as covering: at the end, nothing is under
        # the playhead, so a split-at-playhead action must refuse.
        self.assertIsNone(tl.clip_covering(p, 6.0))
        self.assertIsNone(tl.clip_covering(p, -0.1))
        with self.assertRaises(ValueError):
            tl.split_clip(p, clip["id"], 6.0)
        first, second = tl.split_clip(p, clip["id"], 2.5)
        self.assertEqual((first["duration"], second["start"]), (2.5, 2.5))


class TestCopyPaste(unittest.TestCase):
    def test_copy_after_original_when_free(self):
        p = project_with_media()
        clip = tl.add_clip(p, {"type": "video", "source": "clip.mp4",
                               "track": 0, "start": 0, "duration": 2})
        copied = tl.copy_clip(p, clip["id"])
        self.assertNotEqual(copied["id"], clip["id"])
        self.assertEqual((copied["start"], copied["duration"]), (2.0, 2.0))
        self.assertEqual(copied["source"], "clip.mp4")
        self.assertEqual(len(p["clips"]), 2)

    def test_copy_falls_back_to_track_end(self):
        p = project_with_media()
        a = tl.add_clip(p, {"type": "video", "source": "clip.mp4",
                            "track": 0, "start": 0, "duration": 2})
        tl.add_clip(p, {"type": "video", "source": "clip.mp4",
                        "track": 0, "start": 2, "duration": 2})
        # Right after `a` (2s) is occupied, so the copy lands at the
        # end of the track (4s) without overlapping.
        copied = tl.copy_clip(p, a["id"])
        self.assertEqual(copied["start"], 4.0)


class TestProjects(unittest.TestCase):
    def test_project_name_validation(self):
        for bad in ("", "a/b", "a\\b", "../x", "a b", "a" * 65):
            with self.assertRaises(ValueError, msg=bad):
                srv.validate_project_name(bad)
        self.assertEqual(srv.validate_project_name("video-1_2"), "video-1_2")

    def test_create_switch_rename(self):
        with ServerSandbox(self) as sb:
            srv.create_project("proj-a")
            self.assertEqual(srv.ACTIVE_PROJECT_NAME, "proj-a")
            self.assertTrue((sb.root / "proj-a" / "project.json").exists())
            with self.assertRaises(ValueError):
                srv.create_project("proj-a")  # existing name rejected
            srv.create_project("proj-b")
            srv.switch_active_project("proj-a")
            self.assertEqual(srv.ACTIVE_PROJECT_NAME, "proj-a")
            old, new = srv.rename_project("proj-a", "proj-c")
            self.assertEqual((old, new), ("proj-a", "proj-c"))
            self.assertTrue((sb.root / "proj-c").exists())
            self.assertFalse((sb.root / "proj-a").exists())
            self.assertEqual(srv.ACTIVE_PROJECT_NAME, "proj-c")
            with self.assertRaises(ValueError):
                srv.rename_project("proj-c", "proj-b")  # existing target
            with self.assertRaises(ValueError):
                srv.rename_project("nope", "proj-d")


class TestAudioFade(unittest.TestCase):
    def test_fade_validation(self):
        p = project_with_media()
        with self.assertRaises(ValueError):
            tl.add_clip(p, {"type": "video", "source": "clip.mp4",
                            "track": 0, "start": 0, "duration": 3,
                            "fade_in_seconds": 4.0})  # longer than clip
        with self.assertRaises(ValueError):
            tl.add_clip(p, {"type": "video", "source": "clip.mp4",
                            "track": 0, "start": 0, "duration": 3,
                            "fade_out_seconds": 6.0})  # over the 5s cap
        with self.assertRaises(ValueError):
            tl.add_clip(p, {"type": "video", "source": "clip.mp4",
                            "track": 0, "start": 0, "duration": 3,
                            "fade_in_seconds": 2.0,
                            "fade_out_seconds": 2.0})  # sum exceeds clip
        clip = tl.add_clip(p, {"type": "video", "source": "clip.mp4",
                               "track": 0, "start": 0, "duration": 4,
                               "fade_in_seconds": 1.0,
                               "fade_out_seconds": 1.0})
        self.assertEqual((clip["fade_in_seconds"], clip["fade_out_seconds"]),
                         (1.0, 1.0))

    def test_render_with_audio_fade(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            media_dir = tmp / "media"
            media_dir.mkdir()
            video = tmp / "sample.mp4"
            result = subprocess.run(
                ["ffmpeg", "-y", "-v", "error",
                 "-f", "lavfi", "-i", "testsrc=size=640x360:rate=15:duration=6",
                 "-f", "lavfi", "-i", "sine=frequency=440:duration=6",
                 "-c:v", "libx264", "-pix_fmt", "yuv420p",
                 "-c:a", "aac", "-shortest", str(video)],
                capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stderr[-500:])
            import media as media_mod
            project = tl.new_project()
            project["media"].append(media_mod.import_media(video, media_dir))
            tl.add_clip(project, {"type": "video", "source": "sample.mp4",
                                  "track": 0, "start": 0, "duration": 3,
                                  "fade_in_seconds": 1.0,
                                  "fade_out_seconds": 1.0})
            out = tmp / "out.mp4"
            result = render_mod.render_project(
                project, media_dir, out, width=320, height=180, fps=15)
            self.assertTrue(out.exists())
            self.assertEqual(result["duration"], 3.0)
            self.assertEqual(len(result["audio_fades"]), 1)
            self.assertEqual(result["audio_fades"][0]["fade_in_seconds"], 1.0)
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries",
                 "stream=codec_type", "-show_entries", "format=duration",
                 "-of", "json", str(out)],
                capture_output=True, text=True, timeout=30)
            data = json.loads(probe.stdout)
            types = {s["codec_type"] for s in data["streams"]}
            self.assertIn("audio", types)
            self.assertGreater(float(data["format"]["duration"]), 2.5)


if __name__ == "__main__":
    unittest.main()
