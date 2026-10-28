import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from kb_agent.models import ActionFormatError, LiveModel, ModelConfig, ModelError


class Response:
    def __init__(self, body):
        self.body = body
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, size):
        return self.body


class LiveTransportTests(unittest.TestCase):
    def setUp(self):
        self.config = ModelConfig("https://provider.example/v1/", "test-secret", "test-model")

    def test_request_shape_and_json_action(self):
        action = {"action": "search_documents", "arguments": {"query": "报销"}, "decision_summary": "查找制度"}
        response = {"choices": [{"message": {"content": json.dumps(action, ensure_ascii=False)}}]}
        with patch("urllib.request.urlopen", return_value=Response(json.dumps(response).encode())) as opened:
            result = LiveModel(self.config).decide([{"role": "user", "content": "问题"}])
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, "https://provider.example/v1/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-secret")
        self.assertEqual(json.loads(request.data)["model"], "test-model")
        self.assertEqual(opened.call_args.kwargs["timeout"], 30)
        self.assertEqual(result, action)

    def test_http_error_is_safe_and_not_retried(self):
        with patch("urllib.request.urlopen", side_effect=HTTPError("https://private", 401, "test-secret", None, None)) as opened:
            with self.assertRaises(ModelError) as caught:
                LiveModel(self.config).decide([])
        self.assertNotIn("test-secret", str(caught.exception))
        self.assertEqual(opened.call_count, 1)

    def test_missing_config_is_explicit(self):
        with self.assertRaises(ModelError):
            LiveModel(ModelConfig("", "", ""))

    def test_malformed_completion_is_model_failure(self):
        with patch("urllib.request.urlopen", return_value=Response(b'{"choices":[]}')):
            with self.assertRaises(ModelError):
                LiveModel(self.config).decide([])

    def test_deepseek_profile_is_explicit_and_usage_is_recorded(self):
        options = {"response_format": {"type": "json_object"}, "thinking": {"type": "disabled"}, "max_tokens": 2048, "temperature": 0}
        response = {"model": "deepseek-flash", "choices": [{"message": {"content": '{"ok":true}'}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16, "unexpected_secret": "must-not-log"}}
        model = LiveModel(self.config, request_options=options)
        with patch("urllib.request.urlopen", return_value=Response(json.dumps(response).encode())) as opened:
            model.decide([])
        self.assertEqual(json.loads(opened.call_args.args[0].data)["thinking"], {"type": "disabled"})
        self.assertEqual(model.last_metadata["usage"]["total_tokens"], 16)
        self.assertNotIn("must-not-log", json.dumps(model.last_metadata))

    def test_request_options_cannot_override_model_or_messages(self):
        with self.assertRaises(ValueError):
            LiveModel(self.config, request_options={"model": "different-model"})

    def test_invalid_json_keeps_safe_public_diagnostics_and_usage(self):
        body = {"model": "test-model", "choices": [{"message": {"content": '{"a":1}{"b":2} test-secret', "reasoning_content": "DO_NOT_STORE_INTERNAL_THOUGHTS"}, "finish_reason": "stop"}], "usage": {"total_tokens": 20}}
        model = LiveModel(self.config)
        with patch("urllib.request.urlopen", return_value=Response(json.dumps(body).encode())):
            with self.assertRaises(ActionFormatError) as caught:
                model.decide([])
        diagnostics = json.dumps(caught.exception.diagnostics)
        self.assertIn("Extra data", diagnostics)
        self.assertNotIn("test-secret", diagnostics)
        self.assertNotIn("DO_NOT_STORE_INTERNAL_THOUGHTS", diagnostics)
        self.assertEqual(model.last_metadata["usage"]["total_tokens"], 20)
