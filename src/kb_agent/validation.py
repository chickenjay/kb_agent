from .schemas import Citation, Output, Proposal


def validate_proposal(arguments: dict, evidence: dict, run_id: str, mode: str) -> Output:
    proposal = Proposal.model_validate(arguments)
    citations = []
    for citation in proposal.citations:
        snippet = evidence.get((citation.document_id, citation.snippet_id))
        if snippet is None:
            raise ValueError("引用必须来自本次已成功读取的片段")
        if citation.version_date != snippet["version_date"]:
            raise ValueError("引用版本日期与本次原文不一致")
        if not citation.quote.strip() or citation.quote not in snippet["text"]:
            raise ValueError("引用文字必须是对应原文的非空连续子串")
        citations.append(Citation(**citation.model_dump(), title=snippet["title"], snippet_text=snippet["text"]))
    cited = {c.document_id for c in citations}
    for conflict in proposal.conflicts:
        if len(set(conflict.document_ids)) < 2 or not set(conflict.document_ids).issubset(cited):
            raise ValueError("冲突必须引用至少两份不同文档")
    expected = {"answered": "completed", "needs_clarification": "awaiting_clarification", "insufficient_evidence": "insufficient_evidence"}
    if proposal.status in expected and proposal.termination_reason != expected[proposal.status]:
        raise ValueError("任务状态和终止原因不一致")
    if proposal.status == "answered" and (not citations or proposal.conflicts or proposal.gaps or proposal.follow_up_question):
        raise ValueError("已回答必须有引用，且不得存在未解决冲突、缺口或追问")
    if proposal.status == "needs_clarification" and (not proposal.follow_up_question or not proposal.gaps):
        raise ValueError("待澄清必须提供资料缺口和追问")
    if proposal.status == "insufficient_evidence" and (not proposal.gaps or proposal.conflicts):
        raise ValueError("资料不足必须说明缺口；已知冲突应请求澄清")
    if proposal.conflicts and proposal.status != "needs_clarification":
        raise ValueError("未解决冲突必须请求澄清")
    if proposal.status == "incomplete" and (proposal.termination_reason in {"completed", "awaiting_clarification", "insufficient_evidence"} or not proposal.gaps):
        raise ValueError("未完成状态必须提供对应的失败原因及资料缺口")
    fields = proposal.model_dump(exclude={"citations"})
    return Output(**fields, citations=citations, run_id=run_id, mode=mode)
