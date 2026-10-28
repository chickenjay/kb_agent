import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from kb_agent.corpus import ROOT


class CliTests(unittest.TestCase):
    def run_cli(self, scenario, mode="mock"):
        with tempfile.TemporaryDirectory() as directory:
            env = {**os.environ, "LLM_BASE_URL": "", "LLM_API_KEY": "", "LLM_MODEL": ""}
            process = subprocess.run([sys.executable, "-m", "kb_agent", "ask", "--input", str(ROOT / "examples/cases" / f"{scenario}.json"), "--mode", mode, "--output-dir", directory], cwd=ROOT, env=env, capture_output=True, encoding="utf-8", timeout=30)
            output_path = Path(directory) / "output.json"
            saved = json.loads(output_path.read_text(encoding="utf-8")) if output_path.exists() else None
            return process, saved

    def test_success_stdout_is_utf8_and_matches_saved_output(self):
        process, saved = self.run_cli("normal")
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertIn("报销期限为 30 天", process.stdout)
        self.assertEqual(json.loads(process.stdout), saved)

    def test_tool_failure_is_nonzero_with_truthful_output(self):
        process, saved = self.run_cli("persistent_failure")
        self.assertEqual(process.returncode, 2)
        self.assertEqual(saved["termination_reason"], "tool_failure")
        self.assertEqual(json.loads(process.stdout)["status"], "incomplete")

    def test_missing_live_configuration_is_nonzero_and_never_mock(self):
        process, saved = self.run_cli("normal", "live")
        self.assertEqual(process.returncode, 2)
        self.assertIsNone(saved)
        self.assertEqual(json.loads(process.stderr)["mode"], "live")
