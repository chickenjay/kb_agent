import copy
import unittest

from kb_agent.corpus import Corpus
from kb_agent.validation import validate_proposal


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.source = Corpus.load().read("D01", "D01:p1")
        self.evidence = {("D01", "D01:p1"): self.source}
        self.proposal = {"status": "answered", "answer": "期限为 30 天。", "citations": [{"document_id": "D01", "snippet_id": "D01:p1", "version_date": "2026-01-10", "quote": "报销期限为 30 天。"}], "conflicts": [], "gaps": [], "follow_up_question": None, "termination_reason": "completed"}

    def validate(self, proposal=None, evidence=None):
        return validate_proposal(proposal or self.proposal, self.evidence if evidence is None else evidence, "run", "mock")

    def test_enrichment_comes_from_source(self):
        output = self.validate()
        self.assertEqual(output.citations[0].snippet_text, self.source["text"])

    def test_unread_source_rejected(self):
        with self.assertRaisesRegex(ValueError, "已成功读取"):
            self.validate(evidence={})

    def test_fake_quote_and_wrong_version_rejected(self):
        for field, value in [("quote", "期限为 99 天"), ("version_date", "2099-01-01"), ("snippet_id", "D01:p9"), ("quote", " ")]:
            with self.subTest(field=field):
                proposal = copy.deepcopy(self.proposal)
                proposal["citations"][0][field] = value
                with self.assertRaises(ValueError):
                    self.validate(proposal)

    def test_answer_requires_evidence_and_no_unresolved_gap(self):
        for patch in [{"citations": []}, {"gaps": ["缺少依据"]}, {"follow_up_question": "哪一份？"}, {"termination_reason": "tool_failure"}]:
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                self.validate(self.proposal | patch)

    def test_conflict_requires_two_distinct_cited_documents(self):
        proposal = self.proposal | {"status": "needs_clarification", "termination_reason": "awaiting_clarification", "gaps": ["适用范围未知"], "follow_up_question": "适用哪份？", "conflicts": [{"description": "冲突", "document_ids": ["D01", "D02"]}]}
        with self.assertRaisesRegex(ValueError, "两份"):
            self.validate(proposal)

    def test_incomplete_must_report_failure_reason(self):
        with self.assertRaises(ValueError):
            self.validate(self.proposal | {"status": "incomplete"})

    def test_clarification_requires_question_and_gap(self):
        with self.assertRaises(ValueError):
            self.validate(self.proposal | {"status": "needs_clarification", "termination_reason": "awaiting_clarification"})

    def test_original_quote_does_not_guarantee_semantic_support(self):
        # Explicit boundary: source-integrity validation is NOT an entailment judge.
        output = self.validate(self.proposal | {"answer": "这是一个不受该引用支持的任意结论。"})
        self.assertEqual(output.status, "answered")
