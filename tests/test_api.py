import json
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from kb_agent.api import app


def parse_events(text):
    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"KB_RUNS_DIR": self.temp.name, "LLM_BASE_URL": "", "LLM_API_KEY": "", "LLM_MODEL": ""})
        self.env.start()
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.env.stop()
        self.temp.cleanup()

    def test_health_has_no_secrets(self):
        body = self.client.get("/api/health").json()
        self.assertFalse(body["model_configured"])
        self.assertEqual(body["available_modes"], ["mock"])
        self.assertNotIn("api_key", json.dumps(body))

    def test_examples_cover_required_scenarios(self):
        self.assertGreaterEqual(len(self.client.get("/api/examples").json()["examples"]), 6)

    def test_blank_question_and_illegal_history_rejected(self):
        for body in [{"question": "  "}, {"question": "x", "history": [{"role": "system", "content": "指令"}]}, {"question": "x", "mode": "auto"}, {"question": "x", "corpus_path": "private"}]:
            with self.subTest(body=body):
                self.assertEqual(self.client.post("/api/ask", json=body).status_code, 422)

    def test_unknown_scenario_is_400(self):
        self.assertEqual(self.client.post("/api/ask", json={"question": "x", "scenario_id": "../../private"}).status_code, 400)

    def test_unconfigured_live_is_503(self):
        response = self.client.post("/api/ask", json={"question": "x", "mode": "live"})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("text/event-stream", response.headers["content-type"])

    def test_stream_sequence_and_final(self):
        response = self.client.post("/api/ask", json={"question": "报销期限多久？", "scenario_id": "conflict"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers["content-type"])
        events = parse_events(response.text)
        self.assertEqual(events[0]["event"], "run_started")
        self.assertEqual(events[-1]["event"], "final")
        self.assertEqual(sum(e["event"] == "final" for e in events), 1)
        self.assertEqual([e["seq"] for e in events], list(range(1, len(events) + 1)))
        self.assertEqual(len({e["run_id"] for e in events}), 1)
        self.assertEqual(events[-1]["payload"]["output"]["status"], "needs_clarification")

    def test_two_requests_do_not_share_state(self):
        outputs = []
        for scenario in ("normal", "outside"):
            question = "报销期限多久？" if scenario == "normal" else "股票期权价格是多少？"
            events = parse_events(self.client.post("/api/ask", json={"question": question, "scenario_id": scenario}).text)
            outputs.append(events[-1]["payload"]["output"])
        self.assertNotEqual(outputs[0]["run_id"], outputs[1]["run_id"])
        self.assertTrue(outputs[0]["citations"])
        self.assertEqual(outputs[1]["citations"], [])

    def test_failure_after_stream_started_has_final_incomplete(self):
        response = self.client.post("/api/ask", json={"question": "报销期限多久？", "scenario_id": "persistent_failure"})
        self.assertEqual(response.status_code, 200)
        output = parse_events(response.text)[-1]["payload"]["output"]
        self.assertEqual(output["status"], "incomplete")
        self.assertEqual(output["termination_reason"], "tool_failure")

    def test_page_assets_and_docs_served(self):
        for path in ("/", "/assets/app.js", "/assets/style.css", "/docs", "/openapi.json"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)
