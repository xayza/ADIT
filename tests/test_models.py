"""Tests for the Model Manager + local transcription.

Ollama CLI calls and faster-whisper are mocked or pointed at temp
dirs — no real model is downloaded, deleted or transcribed here.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import model_service as ms
from ai_service import AIError


class FakeResult:
    def __init__(self, returncode=0, stderr=""):
        self.returncode = returncode
        self.stderr = stderr


class TestOllamaNames(unittest.TestCase):
    def test_valid_names(self):
        for name in ("qwen2.5:3b-instruct", "llama3.1", "my-model_v2:7b",
                     "org/model:tag"):
            self.assertEqual(ms.validate_ollama_model_name(name), name)

    def test_invalid_names_rejected(self):
        for name in ("", "a b", "a;rm -rf /", "../evil", "/abs/path",
                     "a|b", "a$b", "a`id`"):
            with self.assertRaises(ValueError, msg=name):
                ms.validate_ollama_model_name(name)


class TestOllamaPullDelete(unittest.TestCase):
    def test_pull_verified_against_list(self):
        seen = []

        def run(cmd):
            seen.append(cmd)
            return FakeResult(0)

        result = ms.pull_ollama_model(
            "qwen2.5:3b-instruct", run_fn=run,
            list_fn=lambda: [{"name": "qwen2.5:3b-instruct"}])
        self.assertEqual(result["name"], "qwen2.5:3b-instruct")
        self.assertEqual(seen[0][:2], ["ollama", "pull"])

    def test_pull_not_in_list_is_error(self):
        with self.assertRaises(AIError):
            ms.pull_ollama_model("qwen2.5:3b-instruct",
                                 run_fn=lambda cmd: FakeResult(0),
                                 list_fn=lambda: [])

    def test_delete_verified_gone(self):
        result = ms.delete_ollama_model(
            "qwen2.5:3b-instruct", run_fn=lambda cmd: FakeResult(0),
            list_fn=lambda: [])
        self.assertTrue(result["deleted"])


class TestWhisperCache(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self.tmp.name) / "hub"
        self.cache.mkdir()
        folder = self.cache / "models--Systran--faster-whisper-tiny"
        (folder / "snapshots").mkdir(parents=True)
        (folder / "snapshots" / "weights.bin").write_bytes(b"x" * 100)

    def tearDown(self):
        self.tmp.cleanup()

    def test_list_whisper_models(self):
        models = ms.list_whisper_models(self.cache)
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0]["name"], "Systran/faster-whisper-tiny")
        self.assertEqual(models[0]["size"], 100)

    def test_list_ignores_non_whisper_folders(self):
        other = self.cache / "models--rhasspy--piper-voices"
        other.mkdir()
        (other / "voice.onnx").write_bytes(b"v")
        models = ms.list_whisper_models(self.cache)
        self.assertEqual([m["name"] for m in models],
                         ["Systran/faster-whisper-tiny"])
        with self.assertRaises(ValueError):
            ms.delete_whisper_model("rhasspy/piper-voices", self.cache)
        self.assertTrue((other / "voice.onnx").exists())

    def test_delete_inside_cache_works(self):
        ms.delete_whisper_model("Systran/faster-whisper-tiny", self.cache)
        self.assertEqual(ms.list_whisper_models(self.cache), [])

    def test_delete_outside_cache_refused(self):
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        (outside / "keep.txt").write_text("keep")
        with self.assertRaises(ValueError):
            ms.delete_whisper_model("../outside", self.cache)
        with self.assertRaises(ValueError):
            ms.delete_whisper_model("no-such-model", self.cache)
        self.assertTrue((outside / "keep.txt").exists())

    def test_download_invalid_size_rejected(self):
        with self.assertRaises(ValueError):
            ms.download_whisper_model("huge-evil", self.cache)


class FakeSegment:
    def __init__(self, start, end, text):
        self.start, self.end, self.text = start, end, text


class FakeWhisperModel:
    def __init__(self, *args, **kwargs):
        pass

    def transcribe(self, path, beam_size=1):
        return ([FakeSegment(0.0, 2.0, "Xin chào"),
                 FakeSegment(2.0, 4.0, "đây là bản ghi.")], None)


class FakeBackend:
    WhisperModel = FakeWhisperModel


class TestTranscription(unittest.TestCase):
    def test_mocked_transcription_saves_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            media = Path(tmp) / "video.mp4"
            media.write_bytes(b"fake")
            result = ms.transcribe_media(media, "tiny", backend_module=FakeBackend)
            self.assertEqual(len(result["segments"]), 2)
            self.assertIn("Xin chào", result["text"])
            files = ms.save_transcript(tmp, result)
            saved = json.loads(Path(files["json_file"]).read_text(encoding="utf-8"))
            self.assertEqual(saved["segments"][0]["start"], 0.0)
            self.assertIn("Xin chào", Path(files["text_file"]).read_text(encoding="utf-8"))

    def test_missing_backend_is_clear_error(self):
        saved = sys.modules.get("faster_whisper")
        sys.modules["faster_whisper"] = None
        try:
            with self.assertRaises(AIError) as ctx:
                ms.transcribe_media(Path("/tmp/nope.mp4"), "tiny")
            self.assertIn("faster-whisper", str(ctx.exception))
        finally:
            if saved is None:
                sys.modules.pop("faster_whisper", None)
            else:
                sys.modules["faster_whisper"] = saved

    def test_load_missing_transcript_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                ms.load_transcript(tmp)


if __name__ == "__main__":
    unittest.main()
