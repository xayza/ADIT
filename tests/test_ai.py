"""Tests for ADIT Phase 2 AI: plan validation/apply, undo, providers.

All tests use a mock provider or local error paths — no network, no
Ollama server, no real API key is ever needed or used.
"""

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ai_service as ai_mod
import timeline as tl


def make_project():
    project = tl.new_project()
    project["media"] = [
        {"filename": "video.mp4", "type": "video", "duration": 10.0},
        {"filename": "nhac.mp3", "type": "audio", "duration": 30.0},
    ]
    tl.add_clip(project, {"type": "video", "source": "video.mp4", "track": 0,
                          "start": 0.0, "duration": 5.0})
    tl.add_clip(project, {"type": "video", "source": "video.mp4", "track": 0,
                          "start": 5.0, "duration": 5.0})
    return project


def clip_ids(project):
    return [c["id"] for c in project["clips"]]


class TestPlanApply(unittest.TestCase):
    def test_valid_plan_applies(self):
        project = make_project()
        first = clip_ids(project)[0]
        plan = {"operations": [
            {"op": "set_speed", "clip_id": first, "speed": 1.5},
            {"op": "set_fade", "clip_id": first, "effect": "fade_in"},
            {"op": "add_text_clip", "text": "Xin chào", "track": 1,
             "start": 0.0, "duration": 3.0},
        ]}
        self.assertEqual(ai_mod.validate_plan(project, plan), [])
        descriptions = ai_mod.apply_plan(project, plan)
        self.assertEqual(len(descriptions), 3)
        clip = tl.get_clip(project, first)
        self.assertEqual(clip["speed"], 1.5)
        self.assertEqual(clip["effect"], "fade_in")
        self.assertTrue(any(c["type"] == "text" and c["text"] == "Xin chào"
                            for c in project["clips"]))

    def test_invalid_plan_rejected_atomically(self):
        project = make_project()
        before = json.dumps(project, sort_keys=True)
        first = clip_ids(project)[0]
        plan = {"operations": [
            {"op": "set_speed", "clip_id": first, "speed": 1.5},
            {"op": "set_speed", "clip_id": first, "speed": 3.0},
            {"op": "delete_clip", "clip_id": "no-such-clip"},
        ]}
        errors = ai_mod.validate_plan(project, plan)
        self.assertTrue(errors)
        with self.assertRaises(ValueError):
            ai_mod.apply_plan(project, plan)
        self.assertEqual(json.dumps(project, sort_keys=True), before)

    def test_unknown_operation_rejected(self):
        project = make_project()
        plan = {"operations": [{"op": "run_shell", "command": "rm -rf /"}]}
        self.assertTrue(ai_mod.validate_plan(project, plan))
        with self.assertRaises(ValueError):
            ai_mod.apply_plan(project, plan)

    def test_overlap_move_rejected(self):
        project = make_project()
        first, second = clip_ids(project)[:2]
        plan = {"operations": [{"op": "move_clip", "clip_id": second,
                                "track": 0, "start": 2.0}]}
        self.assertTrue(ai_mod.validate_plan(project, plan))
        with self.assertRaises(ValueError):
            ai_mod.apply_plan(project, plan)
        self.assertEqual(tl.get_clip(project, second)["start"], 5.0)

    def test_set_music_validation(self):
        project = make_project()
        bad = {"operations": [{"op": "set_music", "source": "khong-co.mp3",
                               "volume": 0.15}]}
        self.assertTrue(ai_mod.validate_plan(project, bad))
        good = {"operations": [{"op": "set_music", "source": "nhac.mp3",
                                "volume": 0.2}]}
        self.assertEqual(ai_mod.validate_plan(project, good), [])
        ai_mod.apply_plan(project, good)
        self.assertEqual(project["background_music"]["source"], "nhac.mp3")

    def test_set_fade_rejects_zoom(self):
        project = make_project()
        plan = {"operations": [{"op": "set_fade", "clip_id": clip_ids(project)[0],
                                "effect": "zoom_in"}]}
        self.assertTrue(ai_mod.validate_plan(project, plan))

    def test_descriptions_are_vietnamese(self):
        project = make_project()
        text = ai_mod.describe_operation(
            {"op": "set_speed", "clip_id": clip_ids(project)[0], "speed": 1.25},
            project)
        self.assertIn("tốc độ", text)


class TestSnapshotUndo(unittest.TestCase):
    def test_apply_then_undo_restores(self):
        project = make_project()
        with tempfile.TemporaryDirectory() as tmp:
            ai_mod.save_snapshot(project, tmp)
            first = clip_ids(project)[0]
            ai_mod.apply_plan(project, {"operations": [
                {"op": "split_clip", "clip_id": first, "at": 2.0}]})
            self.assertEqual(len(project["clips"]), 3)
            restored = ai_mod.load_snapshot(tmp)
            self.assertEqual(len(restored["clips"]), 2)
            self.assertEqual(restored["clips"][0]["duration"], 5.0)

    def test_undo_without_backup_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                ai_mod.load_snapshot(tmp)


class TestProviders(unittest.TestCase):
    def test_mock_provider_proposes_plan(self):
        project = make_project()
        plan = {"operations": [{"op": "set_speed",
                                "clip_id": clip_ids(project)[0], "speed": 1.2}]}
        provider = ai_mod.MockProvider(plan=plan)
        self.assertEqual(provider.propose("tăng tốc clip đầu", project), plan)

    def test_parse_plan_from_fenced_json(self):
        raw = '```json\n{"operations": [{"op": "delete_clip", "clip_id": "x"}]}\n```'
        self.assertEqual(ai_mod.parse_edit_plan(raw)["operations"][0]["op"],
                         "delete_clip")

    def test_parse_bad_json_raises(self):
        with self.assertRaises(ai_mod.AIError):
            ai_mod.parse_edit_plan("xin chào, không có JSON ở đây")

    def test_unknown_provider_raises(self):
        with self.assertRaises(ai_mod.AIError):
            ai_mod.get_provider("khong-co", {})

    def test_openai_without_key_is_clear_error(self):
        saved = {k: os.environ.pop(k, None)
                 for k in ("ADIT_OPENAI_API_KEY", "OPENAI_API_KEY")}
        try:
            with self.assertRaises(ai_mod.AIError) as ctx:
                ai_mod.get_provider("openai", {})
            self.assertIn("API key", str(ctx.exception))
        finally:
            for key, value in saved.items():
                if value is not None:
                    os.environ[key] = value

    def test_ollama_unreachable_is_clear_error(self):
        project = make_project()
        provider = ai_mod.OllamaProvider(host="http://127.0.0.1:9", timeout=2)
        with self.assertRaises(ai_mod.AIError) as ctx:
            provider.propose("làm gì đó", project)
        self.assertIn("Ollama", str(ctx.exception))

    def test_log_never_contains_api_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "ai.log"
            ai_mod.log_ai_event(log_path, {
                "event": "propose", "provider": "openai",
                "api_key": "sk-secret-12345", "command": "test"})
            content = log_path.read_text(encoding="utf-8")
            self.assertNotIn("sk-secret-12345", content)
            self.assertIn("propose", content)

    def test_helper_with_mock_provider(self):
        provider = ai_mod.MockProvider()
        provider.generate_text = lambda system, user: "00:00 - Mở đầu\n01:00 - Kết"
        out = ai_mod.generate_helper(provider, "chapters", "xin chào " * 100)
        self.assertIn("Mở đầu", out["result"])
        self.assertFalse(out["truncated"])


if __name__ == "__main__":
    unittest.main()
