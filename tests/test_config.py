import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from kb_agent.api import app
from kb_agent.models import LiveModel, ModelConfig, ModelError


FIXTURE = '''[llm]
base_url = "https://provider.example"
api_key = "local-fixture-secret"
model = "fixture-model"
[llm.request_options]
thinking = {type = "disabled"}
response_format = {type = "json_object"}
temperature = 0
max_tokens = 2048
'''


class LocalConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "config.local.toml"
        self.path.write_text(FIXTURE, encoding="utf-8")
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_reads_local_config_and_model_options(self):
        config = ModelConfig.from_env(self.path)
        self.assertTrue(config.configured)
        self.assertEqual(config.base_url, "https://provider.example")
        self.assertEqual(config.model, "fixture-model")
        self.assertEqual(LiveModel(config).request_options["thinking"], {"type": "disabled"})

    def test_environment_overrides_each_local_field(self):
        with patch.dict(os.environ, {"LLM_MODEL": "env-model"}):
            config = ModelConfig.from_env(self.path)
        self.assertEqual(config.model, "env-model")
        self.assertEqual(config.api_key, "local-fixture-secret")

    def test_empty_environment_explicitly_disables_local_secret(self):
        with patch.dict(os.environ, {"LLM_API_KEY": ""}):
            self.assertFalse(ModelConfig.from_env(self.path).configured)

    def test_no_file_requires_configuration(self):
        self.assertFalse(ModelConfig.from_env(self.path.parent / "absent.toml").configured)

    def test_invalid_toml_never_discloses_its_contents(self):
        self.path.write_text('api_key = "local-fixture-secret', encoding="utf-8")
        with self.assertRaises(ModelError) as caught:
            ModelConfig.from_env(self.path)
        self.assertNotIn("local-fixture-secret", str(caught.exception))

    def test_key_not_in_repr_or_process_environment(self):
        config = ModelConfig.from_env(self.path)
        self.assertNotIn("local-fixture-secret", repr(config))
        self.assertNotIn("LLM_API_KEY", os.environ)

    def test_private_options_cannot_override_model_or_headers(self):
        self.path.write_text(FIXTURE + 'headers = {Authorization = "local-fixture-secret"}\n', encoding="utf-8")
        with self.assertRaises(ModelError) as caught:
            ModelConfig.from_env(self.path)
        self.assertNotIn("local-fixture-secret", str(caught.exception))

    def test_health_uses_local_configuration_without_exposing_values(self):
        with patch("kb_agent.models.LOCAL_CONFIG_PATH", self.path), TestClient(app) as client:
            response = client.get("/api/health")
        self.assertTrue(response.json()["model_configured"])
        self.assertNotIn("local-fixture-secret", response.text)
        self.assertIn("live", response.json()["available_modes"])

    def test_broken_config_keeps_mock_available(self):
        self.path.write_text('bad = "local-fixture-secret', encoding="utf-8")
        with patch("kb_agent.models.LOCAL_CONFIG_PATH", self.path), TestClient(app) as client:
            response = client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["available_modes"], ["mock"])
        self.assertNotIn("local-fixture-secret", response.text)
