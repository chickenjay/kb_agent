import hashlib
import json
import math
import re
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def tokens(text: str) -> list[str]:
    result = re.findall(r"[a-z0-9]+", text.lower())
    for segment in re.findall(r"[\u4e00-\u9fff]+", text):
        result.extend(segment[i:i + 2] for i in range(len(segment) - 1))
        if len(segment) == 1:
            result.append(segment)
    return result


class Corpus:
    """Per-run immutable source snapshot and deterministic lexical index."""

    def __init__(self, documents: list[dict], enhanced: bool = True):
        self.documents = json.loads(json.dumps(documents, ensure_ascii=False))
        self.enhanced = enhanced
        self.synonyms = json.loads((ROOT / "data/synonyms.json").read_text(encoding="utf-8"))
        self.hash = hashlib.sha256(json.dumps(self.documents, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        self.snippets = {}
        ids = set()
        for doc in self.documents:
            if doc["document_id"] in ids:
                raise ValueError("重复文档 ID")
            ids.add(doc["document_id"])
            date.fromisoformat(doc["version_date"])
            offset = 0
            for index, paragraph in enumerate(doc["content"].split("\n\n"), 1):
                if paragraph.strip():
                    snippet = {"document_id": doc["document_id"], "title": doc["title"], "version_date": doc["version_date"], "snippet_id": f"{doc['document_id']}:p{index}", "text": paragraph, "start": offset, "end": offset + len(paragraph), "scope": doc.get("scope"), "supersedes": doc.get("supersedes")}
                    self.snippets[(snippet["document_id"], snippet["snippet_id"])] = snippet
                offset += len(paragraph) + 2
        self.rows = list(self.snippets.values())
        self.counts = [Counter(tokens(row["title"] + " " + row["text"])) for row in self.rows]
        self.lengths = [sum(c.values()) for c in self.counts]
        self.avg_length = sum(self.lengths) / max(len(self.lengths), 1) or 1
        self.df = Counter(term for count in self.counts for term in count)

    @classmethod
    def load(cls, path: str | Path | None = None, **kwargs):
        return cls(json.loads(Path(path or ROOT / "data/documents.json").read_text(encoding="utf-8")), **kwargs)

    def search(self, query: str, top_k: int = 5) -> dict:
        expanded = query
        if self.enhanced:
            for group in self.synonyms:
                if any(word in query for word in group):
                    expanded += " " + " ".join(group)
        terms = set(tokens(expanded))
        ranked = []
        n = len(self.rows)
        for row, counts, length in zip(self.rows, self.counts, self.lengths):
            score = 0.0
            for term in terms:
                tf = counts[term]
                if tf:
                    idf = math.log(1 + (n - self.df[term] + 0.5) / (self.df[term] + 0.5))
                    score += idf * tf * 2.5 / (tf + 1.5 * (0.25 + 0.75 * length / self.avg_length))
            if score > 0:
                ranked.append({k: row[k] for k in ("document_id", "title", "version_date", "snippet_id")} | {"score": round(score, 5), "preview": row["text"][:90]})
        ranked.sort(key=lambda row: (-row["score"], row["document_id"], row["snippet_id"]))
        return {"matches": ranked[:top_k], "total_matches": len(ranked), "truncated": len(ranked) > top_k}

    def read(self, document_id: str, snippet_id: str) -> dict:
        row = self.snippets.get((document_id, snippet_id))
        if row is None:
            raise KeyError("文档或片段不存在")
        return dict(row)
