import json
from datetime import datetime, timezone
from pathlib import Path

from .agent import AgentRunner
from .corpus import ROOT, Corpus
from .models import LiveModel, ModelConfig
from .advanced import advanced_cases, check_advanced
from .scenarios import EXAMPLES, faults_for, scenario_corpus
from .schemas import AskRequest


def retrieval_evaluation():
    queries = json.loads((ROOT / "data/retrieval_queries.json").read_text(encoding="utf-8"))
    results = {}
    for enhanced in (False, True):
        corpus = Corpus.load(enhanced=enhanced)
        rows = []
        for query in queries:
            found = [r["document_id"] for r in corpus.search(query["query"], 5)["matches"]]
            recall = len(set(found) & set(query["relevant"])) / len(query["relevant"])
            rows.append({**query, "retrieved": found, "recall_at_5": recall})
        results["enhanced" if enhanced else "baseline"] = {"recall_at_5": sum(r["recall_at_5"] for r in rows) / len(rows), "queries": rows}
    return results


def check_invariants(output, events, corpus):
    problems = []
    if not events:
        return ["缺少运行记录"]
    read_ids = {(e["payload"]["observation"]["data"]["document_id"], e["payload"]["observation"]["data"]["snippet_id"]) for e in events if e["event"] == "tool_result" and e["payload"]["tool"] == "read_snippet" and e["payload"]["ok"]}
    for citation in output.citations:
        try:
            source = corpus.read(citation.document_id, citation.snippet_id)
        except KeyError:
            problems.append("引用不存在的文档片段")
            continue
        if (citation.document_id, citation.snippet_id) not in read_ids or citation.quote not in source["text"] or citation.version_date != source["version_date"]:
            problems.append("引用未通过来源校验")
    if sum(e["event"] == "tool_result" for e in events) > 6 or events[-1]["payload"].get("decisions", 0) > 8:
        problems.append("执行预算越界")
    if sum(e["event"] == "final" for e in events) != 1 or events[-1]["event"] != "final":
        problems.append("最终事件缺失或重复")
    if len({e["run_id"] for e in events}) != 1 or [e["seq"] for e in events] != list(range(1, len(events) + 1)):
        problems.append("运行事件标识或顺序错误")
    return problems


def check_result(case_id, output, events, corpus):
    problems = check_invariants(output, events, corpus)
    wanted = {"normal": "answered", "conflict": "needs_clarification", "outside": "insufficient_evidence", "paraphrase": "answered", "followup": "answered", "transient_failure": "answered", "persistent_failure": "incomplete", "changed_45": "answered", "conflict_added": "needs_clarification", "conflict_removed": "answered"}[case_id]
    if output.status != wanted:
        problems.append(f"status={output.status}, expected={wanted}")
    quoted_docs = {c.document_id for c in output.citations}
    if case_id in {"normal", "paraphrase", "transient_failure", "conflict_removed"}:
        if not {"D01"}.issubset(quoted_docs) or "30" not in output.answer or "D02" in quoted_docs:
            problems.append("单一制度的事实或引用不符合预期")
    if case_id in {"conflict", "conflict_added"}:
        if not {"D01", "D02"}.issubset(quoted_docs) or not output.conflicts or not output.follow_up_question:
            problems.append("冲突未完整呈现或未请求澄清")
        if not all(value in output.answer for value in ("30", "15")):
            problems.append("答案未列出双方期限")
        if not any(e["event"] == "action" and e["payload"]["action"] == "search_documents" and any(word in e["payload"]["arguments"].get("query", "") for word in ("适用", "优先", "替代")) for e in events):
            problems.append("没有补充查证适用依据")
    if case_id == "followup" and "D04" not in quoted_docs:
        problems.append("追问未读取凭证制度")
    if case_id == "outside" and (output.citations or not output.gaps):
        problems.append("资料外问题应明确缺口且不得附加不相关引用")
    if case_id == "changed_45" and ("45" not in output.answer or "30" in output.answer):
        problems.append("修改资料后答案未更新")
    if case_id == "persistent_failure" and output.termination_reason != "tool_failure":
        problems.append("持续工具故障未正确说明原因")
    if case_id == "transient_failure" and not any(e["event"] == "tool_result" and not e["payload"]["ok"] for e in events):
        problems.append("工具失败场景未实际触发故障")
    if sum(e["event"] == "tool_result" for e in events) > 6 or sum(e["event"] == "action" for e in events) > 8:
        problems.append("执行预算越界")
    return problems


def evaluate(mode: str, output_dir, suite="basic", model_config=None, request_options=None, progress=None, case_ids=None):
    if suite not in {"basic", "advanced", "all"}:
        raise ValueError("未知评估套件")
    config = model_config or (ModelConfig.from_env() if mode == "live" else ModelConfig("", "", ""))
    directory = Path(output_dir)
    if (directory / "summary.json").exists():
        directory /= datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    directory.mkdir(parents=True, exist_ok=True)
    report = {"mode": mode, "suite": suite, "generated_at": datetime.now(timezone.utc).isoformat(), "semantic_support_review": "not_run: 需人工逐例核对，不以自动来源校验替代", "acceptance": "pending_live_validation", "cases": [], "retrieval": retrieval_evaluation()}
    if mode == "live":
        report["model"] = {"base_url": config.base_url, "requested_model": config.model, "request_options": config.request_options if request_options is None else request_options}
    if mode == "live" and not config.configured:
        report |= {"status": "not_run", "reason": "本地配置和环境变量均未提供完整模型配置；未降级为 Mock。"}
    else:
        cases = [(item["id"], item, scenario_corpus(item["id"]), faults_for(item["id"])) for item in EXAMPLES]
        normal = dict(EXAMPLES[0])
        changed = scenario_corpus("normal").documents
        for doc in changed:
            if doc["document_id"] == "D01":
                doc["content"] = doc["content"].replace("30", "45")
        cases += [("changed_45", normal, Corpus(changed), {}), ("conflict_added", normal, Corpus.load(), {}), ("conflict_removed", normal, scenario_corpus("normal"), {})]
        extended = {case["id"]: case for case in advanced_cases()}
        if suite == "advanced":
            cases = []
        if suite in {"advanced", "all"}:
            cases += [(case["id"], case, Corpus(case["documents"]), case["faults"]) for case in extended.values()]
        if case_ids is not None:
            unknown = set(case_ids) - {case[0] for case in cases}
            if unknown:
                raise ValueError(f"未知或不属于当前套件的用例：{sorted(unknown)}")
            cases = [case for case in cases if case[0] in case_ids]
        if not cases:
            raise ValueError("评估至少需要一个用例，空集合不能记为通过")
        for case_id, item, corpus, faults in cases:
            request = AskRequest(question=item["question"], history=item["history"], mode=mode, scenario_id=item["id"] if case_id in {x["id"] for x in EXAMPLES} else None)
            def on_event(event):
                if progress:
                    progress({"case": case_id, "event": event["event"], "step": event["step"]})
            runner = AgentRunner(request, corpus, model=LiveModel(config, request_options=request_options) if mode == "live" else None, faults=faults, output_dir=directory / case_id, on_event=on_event)
            result = runner.run()
            problems = check_invariants(result, runner.events, corpus) + check_advanced(extended[case_id], result, runner.events) if case_id in extended else check_result(case_id, result, runner.events, corpus)
            # Persist the exact input corpus, including mutations, for replay.
            (runner.output_dir / "corpus.json").write_text(json.dumps(corpus.documents, ensure_ascii=False, indent=2), encoding="utf-8")
            (runner.output_dir / "faults.json").write_text(json.dumps(faults, ensure_ascii=False, indent=2), encoding="utf-8")
            if case_id in extended:
                (runner.output_dir / "expected.json").write_text(json.dumps({"description": item["description"], **item["expected"]}, ensure_ascii=False, indent=2), encoding="utf-8")
            calls = [e["payload"]["model_call"] for e in runner.events if e["event"] in {"action", "validation_error"} and "model_call" in e["payload"]]
            metrics = {"decisions": runner.decisions, "tool_calls": runner.tool_calls, "elapsed_ms": runner.events[-1]["payload"]["elapsed_ms"], "token_usage": {name: sum(call["usage"].get(name, 0) for call in calls) for name in ("prompt_tokens", "completion_tokens", "total_tokens")}}
            report["cases"].append({"id": case_id, "passed": not problems, "problems": problems, "status": result.status, "run_id": runner.run_id, "path": str((runner.output_dir).relative_to(directory)).replace("\\", "/"), **metrics})
            # Save partial progress too: interrupted evaluations retain completed cases.
            (directory / "summary.json").write_text(json.dumps(report | {"status": "running"}, ensure_ascii=False, indent=2), encoding="utf-8")
            if progress:
                progress({"case": case_id, "passed": not problems, "problems": problems, "event": "case_completed"})
        report["passed"] = sum(case["passed"] for case in report["cases"])
        report["total"] = len(report["cases"])
        report["status"] = "passed" if report["passed"] == report["total"] else "failed"
        if mode == "mock":
            report["scope"] = "仅验证流程，不证明真实模型决策或语义支持。"
        else:
            report["acceptance"] = "pending_semantic_review"
    (directory / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report, directory
