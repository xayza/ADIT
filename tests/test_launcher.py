"""Tests for the Windows launcher / packaging files.

These tests deliberately do NOT run the .bat/.ps1 scripts: they are
Windows scripts and cannot run on this Linux VM. They validate the
scripts by reading them back (checks present, browser URL, server
start, stay-open behaviour) and validate server.py's new flags by
running it with --help and against a port that is already in use.
"""
import ast
import socket
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class LauncherFilesTest(unittest.TestCase):
    def test_bat_launcher_contains_key_steps(self):
        text = (ROOT / "scripts" / "run_adit.bat").read_text(encoding="utf-8")
        # Python + Pillow check, FFmpeg check, server start, browser URL,
        # and the script must stay open (pause) instead of vanishing.
        for needle in ("python", "PIL", "ffmpeg", "server.py",
                       "127.0.0.1:8000", "pause"):
            self.assertIn(needle, text, f"run_adit.bat missing: {needle}")
        # Must poll for the server, not just sleep and hope.
        self.assertIn("Invoke-WebRequest", text)

    def test_ps1_launcher_contains_key_steps(self):
        text = (ROOT / "scripts" / "run_adit.ps1").read_text(encoding="utf-8")
        for needle in ("python", "PIL", "ffmpeg", "server.py",
                       "127.0.0.1:8000"):
            self.assertIn(needle, text, f"run_adit.ps1 missing: {needle}")
        self.assertIn("Invoke-WebRequest", text)

    def test_build_script_and_spec(self):
        build = (ROOT / "scripts" / "build_windows.bat").read_text(encoding="utf-8")
        self.assertIn("pyinstaller", build)
        self.assertIn("adit.spec", build)
        self.assertIn("dist", build)
        spec_text = (ROOT / "adit.spec").read_text(encoding="utf-8")
        # Spec must at least parse as Python.
        ast.parse(spec_text)
        self.assertIn("server.py", spec_text)
        self.assertIn("static", spec_text)
        self.assertIn("ADIT", spec_text)

    def test_server_help_lists_open_browser(self):
        out = subprocess.run(
            [sys.executable, "server.py", "--help"],
            cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 0)
        self.assertIn("--open-browser", out.stdout)


class ServerStartupTest(unittest.TestCase):
    def test_port_in_use_exits_with_clear_error(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        try:
            proc = subprocess.run(
                [sys.executable, "server.py", "--port", str(port)],
                cwd=ROOT, capture_output=True, text=True, timeout=30)
        finally:
            sock.close()
        self.assertNotEqual(proc.returncode, 0)
        combined = proc.stdout + proc.stderr
        self.assertIn("đã được dùng", combined)


if __name__ == "__main__":
    unittest.main()
