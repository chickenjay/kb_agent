import json
import hashlib
import tempfile
import threading
import unittest
from pathlib import Path

from kb_agent.agent import AgentRunner
from kb_agent.corpus import Corpus
from kb_agent.evaluation import check_result
from kb_agent.models import MockModel, ModelError
from kb_agent.scenarios import EXAMPLES, faults_for, scenario_corpus
from kb_agent.schemas import AskRequest


class AlwaysSearch:
    name = "test-fixture"

    def decide(self, messages):
        return {"action": "search_documents", "arguments": {"query": "报销"}, "decision_summary": "测试预算上限"}


class AgentTests(unittest.TestCase):
    def test_all_acceptance_scenarios_with_explicit_mock(self):
        for case in EXAMPLES:
            with self.subTest(case=case["id"]):
                request = AskRequest(question=case["question"], history=case["history"], scenario_id=case["id"])
                corpus = scenario_corpus(case["id"])
                runner = AgentRunner(request, corpus, faults=faults_for(case["id"]))
                result = runner.run()
                self.assertEqual(check_result(case["id"], result, runner.events, corpus), [])

    def test_observations_change_next_actions(self):
        paths = []
        for scenario in ("normal", "conflict"):
            runner = AgentRunner(AskRequest(question="报销期限多久？"), scenario_corpus(scenario))
            runner.run()
            paths.append([e["payload"] for e in runner.events if e["event"] == "action"])
        self.assertEqual(paths[0][-1]["arguments"]["status"], "answered")
        self.assertEqual(paths[1][-1]["arguments"]["status"], "needs_clarification")
        self.assertGreater(len(paths[1]), len(paths[0]))

    def test_tool_budget_and_final_event(self):
        runner = AgentRunner(AskRequest(question="报销"), Corpus.load(), model=AlwaysSearch())
        output = runner.run()
        self.assertEqual((output.status, output.termination_reason), ("incomplete", "budget_exhausted"))
        self.assertEqual(runner.tool_calls, 6)
        self.assertEqual(sum(e["event"] == "final" for e in runner.events), 1)
        self.assertEqual(runner.events[-1]["event"], "final")

    def test_invalid_model_actions_consume_budget(self):
        class Invalid:
            name = "invalid-test-fixture"
            def decide(self, messages):
                return {"action": "delete_everything", "arguments": {}, "decision_summary": "非法动作"}
        runner = AgentRunner(AskRequest(question="问题"), Corpus.load(), model=Invalid())
        self.assertEqual(runner.run().termination_reason, "budget_exhausted")
        self.assertEqual(runner.decisions, 8)
        self.assertEqual(runner.tool_calls, 0)

    def test_cancel_between_model_and_tool(self):
        cancel = threading.Event()
        runner = AgentRunner(AskRequest(question="报销"), Corpus.load(), model=AlwaysSearch(), cancel=cancel, on_event=lambda e: cancel.set() if e["event"] == "action" else None)
        self.assertEqual(runner.run().termination_reason, "user_cancelled")
        self.assertEqual(runner.tool_calls, 0)

    def test_model_failure_never_falls_back_to_mock(self):
        class Failed:
            name = "failed-live-fixture"
            def decide(self, messages):
                raise ModelError("模拟服务不可用")
        runner = AgentRunner(AskRequest(question="报销", mode="live"), Corpus.load(), model=Failed())
        output = runner.run()
        self.assertEqual(output.mode, "live")
        self.assertEqual(output.termination_reason, "model_failure")
        self.assertEqual(runner.tool_calls, 0)

    def test_validator_feedback_drives_correction(self):
        class Correcting(MockModel):
            def __init__(self):
                self.injected = False
            def decide(self, messages):
                result = super().decide(messages)
                if result["action"] == "finish" and not self.injected:
                    result["arguments"]["citations"][0]["quote"] = "伪造引用"
                    self.injected = True
                return result
        runner = AgentRunner(AskRequest(question="报销期限多久？"), scenario_corpus("normal"), model=Correcting())
        self.assertEqual(runner.run().status, "answered")
        self.assertTrue(any(e["event"] == "validation_error" for e in runner.events))

    def test_corpus_replacement_changes_answer(self):
        corpus = scenario_corpus("normal")
        for doc in corpus.documents:
            if doc["document_id"] == "D01":
                doc["content"] = doc["content"].replace("30", "45")
        result = AgentRunner(AskRequest(question="报销期限多久？"), Corpus(corpus.documents)).run()
        self.assertIn("45", result.answer)
        self.assertNotIn("30", result.answer)

    def test_actual_observation_and_trace_have_same_budget(self):
        runner = AgentRunner(AskRequest(question="报销期限多久？"), scenario_corpus("normal"))
        runner.run()
        tools = [e for e in runner.events if e["event"] == "tool_result"]
        self.assertEqual(tools[0]["payload"]["observation"]["remaining_tool_calls"], 5)

    def test_reruns_preserve_previous_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            runners = [AgentRunner(AskRequest(question="报销期限多久？"), scenario_corpus("normal"), output_dir=temp) for _ in range(2)]
            for runner in runners:
                runner.run()
            first = json.loads((Path(temp) / "output.json").read_text(encoding="utf-8"))
            second = json.loads((Path(temp) / runners[1].run_id / "output.json").read_text(encoding="utf-8"))
            self.assertNotEqual(first["run_id"], second["run_id"])
            prompt = (Path(temp) / "prompt.txt").read_text(encoding="utf-8")
            self.assertEqual(hashlib.sha256(prompt.encode()).hexdigest(), runners[0].events[0]["payload"]["prompt_sha256"])

    def test_interrupted_run_keeps_collected_sources_without_new_claim(self):
        class ReadThenFail:
            name = "read-then-fail-fixture"
            def decide(self, messages):
                if len(messages) == 2:
                    return {"action": "read_snippet", "arguments": {"document_id": "D01", "snippet_id": "D01:p1"}, "decision_summary": "读取已知测试片段"}
                raise ModelError("模拟模型故障")
        runner = AgentRunner(AskRequest(question="报销"), Corpus.load(), model=ReadThenFail())
        output = runner.run()
        self.assertEqual(output.termination_reason, "model_failure")
        self.assertEqual(output.citations[0].document_id, "D01")
        self.assertNotIn("30", output.answer)
