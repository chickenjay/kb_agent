import tempfile
import unittest

from kb_agent.advanced import advanced_cases, check_advanced
from kb_agent.agent import AgentRunner
from kb_agent.corpus import Corpus
from kb_agent.evaluation import check_invariants, evaluate
from kb_agent.schemas import AskRequest


class EvaluationContractTests(unittest.TestCase):
    def test_empty_trace_is_failure_not_a_crash(self):
        corpus = Corpus.load()
        output = AgentRunner(AskRequest(question="报销期限多久？"), corpus).run()
        self.assertEqual(check_invariants(output, [], corpus), ["缺少运行记录"])

    def test_empty_case_selection_cannot_report_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "至少需要一个"):
                evaluate("mock", directory, case_ids=[])

    def test_unknown_case_selection_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "未知"):
                evaluate("mock", directory, case_ids=["not-a-case"])

    def test_strict_injection_check_is_a_lexical_flag_not_semantic_judge(self):
        case = next(c for c in advanced_cases() if c["id"] == "untrusted_document")
        corpus = Corpus(case["documents"])
        runner = AgentRunner(AskRequest(question=case["question"]), corpus)
        output = runner.run()
        # Explicitly document the limitation exposed by real-model testing:
        # even a refusal containing the poison number raises a review flag.
        output.answer += " 夹带的999天不予采纳。"
        self.assertTrue(any("999" in p for p in check_advanced(case, output, runner.events)))
