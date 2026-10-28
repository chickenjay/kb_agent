import copy
import json
import threading
import unittest

from kb_agent.advanced import advanced_cases, check_advanced
from kb_agent.agent import AgentRunner
from kb_agent.corpus import Corpus
from kb_agent.evaluation import check_invariants
from kb_agent.models import MockModel
from kb_agent.schemas import AskRequest


class AdvancedBusinessTests(unittest.TestCase):
    """Each case has frozen business assertions, not golden prose snapshots."""


def business_test(case_id):
    def test(self):
        case = next(case for case in advanced_cases() if case["id"] == case_id)
        corpus = Corpus(case["documents"])
        runner = AgentRunner(AskRequest(question=case["question"], history=case["history"]), corpus, faults=case["faults"])
        output = runner.run()
        self.assertEqual(check_invariants(output, runner.events, corpus) + check_advanced(case, output, runner.events), [])
        if case_id == "partial_read_failure":
            self.assertTrue(output.citations, "已取得的部分证据不能在失败时丢失")
        if case_id == "intermittent_failures":
            errors = [e for e in runner.events if e["event"] == "tool_result" and not e["payload"]["ok"]]
            self.assertEqual([e["payload"]["tool"] for e in errors], ["search_documents", "read_snippet"])
    return test


for _case in advanced_cases():
    setattr(AdvancedBusinessTests, "test_" + _case["id"], business_test(_case["id"]))


class SequenceModel:
    """Protocol fixture only: explicit actions, never presented as LLM traces."""
    name = "scripted-protocol-fixture"

    def __init__(self, actions):
        self.actions = iter(actions)

    def decide(self, messages):
        action = next(self.actions)
        if isinstance(action, Exception):
            raise action
        return copy.deepcopy(action)


def action(name, arguments):
    return {"action": name, "arguments": arguments, "decision_summary": "离线协议边界测试"}


def read(document="D01"):
    return action("read_snippet", {"document_id": document, "snippet_id": document + ":p1"})


def finish(document="D01"):
    source = Corpus.load().read(document, document + ":p1")
    citation = {key: source[key] for key in ("document_id", "snippet_id", "version_date")}
    citation["quote"] = source["text"]
    return action("finish", {"status": "answered", "answer": source["text"], "citations": [citation], "gaps": [], "conflicts": [], "follow_up_question": None, "termination_reason": "completed"})


class ProtocolBoundaryTests(unittest.TestCase):
    def runner(self, actions, **kwargs):
        return AgentRunner(AskRequest(question="报销期限多久？"), Corpus.load(), model=SequenceModel(actions), **kwargs)

    def test_unread_citation_rejected_then_repaired(self):
        runner = self.runner([finish(), read(), finish()])
        self.assertEqual(runner.run().status, "answered")
        self.assertEqual(sum(e["event"] == "validation_error" for e in runner.events), 1)
        self.assertEqual(runner.decisions, 3)

    def test_cross_document_quote_cannot_be_laundered(self):
        wrong = finish("D02")
        wrong["arguments"]["citations"][0]["quote"] = "报销期限为 30 天。"
        runner = self.runner([read("D02"), wrong, finish("D02")])
        result = runner.run()
        self.assertEqual(result.status, "answered")
        self.assertIn("15", result.citations[0].quote)
        self.assertTrue(any(e["event"] == "validation_error" for e in runner.events))

    def test_wrong_version_is_not_silently_rewritten(self):
        wrong = finish()
        wrong["arguments"]["citations"][0]["version_date"] = "2099-01-01"
        runner = self.runner([read(), wrong, finish()])
        self.assertEqual(runner.run().citations[0].version_date, "2026-01-10")
        self.assertEqual(runner.decisions, 3)

    def test_final_still_allowed_after_sixth_tool(self):
        runner = self.runner([read()] * 6 + [finish()])
        self.assertEqual(runner.run().status, "answered")
        self.assertEqual((runner.tool_calls, runner.decisions), (6, 7))

    def test_malformed_json_feedback_consumes_a_decision(self):
        broken = json.JSONDecodeError("fixture", "{", 1)
        runner = self.runner([broken, read(), finish()])
        self.assertEqual(runner.run().status, "answered")
        self.assertEqual(runner.decisions, 3)
        self.assertEqual(runner.events[1]["event"], "validation_error")

    def test_invalid_tool_arguments_are_observed_and_repaired(self):
        runner = self.runner([action("search_documents", {"query": "报销", "top_k": 1000}), read(), finish()])
        self.assertEqual(runner.run().status, "answered")
        failed = [e for e in runner.events if e["event"] == "tool_result" and not e["payload"]["ok"]]
        self.assertEqual(failed[0]["payload"]["observation"]["error"]["code"], "INVALID_TOOL_ARGUMENTS")

    def test_cancel_after_read_preserves_evidence_and_stops_next_model(self):
        cancel = threading.Event()
        runner = self.runner([read(), RuntimeError("下一次模型不应执行")], cancel=cancel, on_event=lambda e: cancel.set() if e["event"] == "tool_result" else None)
        output = runner.run()
        self.assertEqual(output.termination_reason, "user_cancelled")
        self.assertEqual(runner.decisions, 1)
        self.assertEqual(output.citations[0].document_id, "D01")

    def test_repeated_invalid_finish_never_passes_as_answer(self):
        wrong = finish()
        wrong["arguments"]["citations"][0]["quote"] = "不存在的 999 天条款"
        runner = self.runner([read()] + [wrong] * 7)
        self.assertEqual(runner.run().termination_reason, "budget_exhausted")
        self.assertEqual(runner.decisions, 8)
        self.assertEqual(runner.tool_calls, 1)

    def test_unexpected_exception_does_not_expose_message(self):
        runner = self.runner([RuntimeError("SENSITIVE_FIXTURE_NOT_FOR_LOGS")])
        self.assertEqual(runner.run().termination_reason, "internal_error")
        self.assertNotIn("SENSITIVE_FIXTURE_NOT_FOR_LOGS", json.dumps(runner.events))

    def test_read_failure_does_not_become_empty_search(self):
        runner = AgentRunner(AskRequest(question="报销期限多久？"), Corpus.load(), model=MockModel(), faults={"read_snippet": -1})
        output = runner.run()
        self.assertEqual(output.status, "incomplete")
        self.assertEqual(output.termination_reason, "tool_failure")

    def test_unsupported_shell_action_never_reaches_a_tool(self):
        forbidden = action("shell_tool", {"command": "this must never execute"})
        runner = self.runner([forbidden] * 8)
        self.assertEqual(runner.run().termination_reason, "budget_exhausted")
        self.assertEqual(runner.tool_calls, 0)
