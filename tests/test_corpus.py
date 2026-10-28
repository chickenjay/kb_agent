import unittest

from kb_agent.corpus import Corpus


class CorpusTests(unittest.TestCase):
    def test_conflicting_sources_both_retrievable(self):
        result = Corpus.load().search("报销期限")
        self.assertTrue({"D01", "D02"}.issubset({r["document_id"] for r in result["matches"]}))

    def test_synonym_expansion_improves_isolated_paraphrase(self):
        self.assertEqual(Corpus.load(enhanced=False).search("住店")["matches"], [])
        self.assertEqual(Corpus.load().search("住店")["matches"][0]["document_id"], "D03")

    def test_empty_search_is_successful_empty_result(self):
        self.assertEqual(Corpus.load().search("量子纠缠实验")["matches"], [])

    def test_mutation_changes_snapshot_and_read(self):
        old = Corpus.load()
        documents = old.documents.copy()
        documents[0] = {**documents[0], "content": "报销期限为 45 天。"}
        new = Corpus(documents)
        self.assertNotEqual(new.hash, old.hash)
        self.assertIn("45", new.read("D01", "D01:p1")["text"])
        self.assertIn("30", old.read("D01", "D01:p1")["text"])

    def test_paragraph_positions_match_original(self):
        doc = {"document_id": "X", "version_date": "2026-01-01", "title": "片段", "content": "第一段\n\n第二段"}
        corpus = Corpus([doc])
        for row in corpus.rows:
            self.assertEqual(doc["content"][row["start"]:row["end"]], row["text"])

    def test_duplicate_ids_rejected(self):
        doc = Corpus.load().documents[0]
        with self.assertRaises(ValueError):
            Corpus([doc, doc])

    def test_unknown_snippet_is_error(self):
        with self.assertRaises(KeyError):
            Corpus.load().read("D01", "D02:p1")

    def test_truncation_is_explicit(self):
        result = Corpus.load().search("报销", 1)
        self.assertEqual(len(result["matches"]), 1)
        self.assertTrue(result["truncated"])
