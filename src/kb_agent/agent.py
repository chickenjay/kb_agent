import json
import hashlib
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from .models import SYSTEM_PROMPT, LiveModel, MockModel, ModelConfig, ModelError
from .schemas import Action, AskRequest, Citation, Event, Output, ReadArgs, SearchArgs
from .validation import validate_proposal


class GraphState(TypedDict):
    messages: list[dict]
    action: dict | None
    done: bool


class AgentRunner:
    """One runner per request: no mutable state shared across conversations."""

    def __init__(self, request: AskRequest, corpus, model=None, faults=None, cancel=None, on_event=None, output_dir=None, max_decisions=8, max_tools=6):
        self.request = request
        self.corpus = corpus
        self.model = model or (MockModel() if request.mode == "mock" else LiveModel(ModelConfig.from_env()))
        self.faults = dict(faults or {})
        self.cancel = cancel or threading.Event()
        self.on_event = on_event
        self.output_dir = Path(output_dir) if output_dir else None
        self.run_id = uuid.uuid4().hex
        self.events = []
        self.evidence = {}
        self.result = None
        self.decisions = 0
        self.tool_calls = 0
        self.tool_occurrences = {}
        self.max_decisions = max_decisions
        self.max_tools = max_tools
        self.started = time.monotonic()
        self.system_prompt = SYSTEM_PROMPT

    def emit(self, event, payload):
        item = Event(run_id=self.run_id, seq=len(self.events) + 1, event=event, step=self.decisions, timestamp=datetime.now(timezone.utc).isoformat(), payload=payload).model_dump(mode="json")
        self.events.append(item)
        if self.on_event:
            self.on_event(item)

    def stop(self, reason, message):
        partial = [Citation(document_id=s["document_id"], version_date=s["version_date"], snippet_id=s["snippet_id"], quote=s["text"], title=s["title"], snippet_text=s["text"]) for s in self.evidence.values()]
        self.result = Output(status="incomplete", answer=message, citations=partial, gaps=["本次任务尚未完成；已取得的证据仅供检查，不能替代最终结论。"], termination_reason=reason, run_id=self.run_id, mode=self.request.mode)

    def decide(self, state):
        if self.cancel.is_set():
            self.stop("user_cancelled", "任务已停止，未完成。")
            return {"done": True, "action": None}
        if self.decisions >= self.max_decisions:
            self.stop("budget_exhausted", "模型决策次数达到上限，任务未完成。")
            return {"done": True, "action": None}
        self.decisions += 1
        messages = state["messages"]
        try:
            raw = self.model.decide(messages)
            action = Action.model_validate(raw)
        except ModelError as exc:
            self.stop("model_failure", str(exc))
            return {"done": True, "action": None}
        except (ValueError, TypeError) as exc:
            # Validation errors exclude model-provided input values from logs.
            metadata = getattr(self.model, "last_metadata", {})
            diagnostics = getattr(exc, "diagnostics", {})
            if hasattr(exc, "errors"):
                diagnostics = {"schema_errors": [{"field": str(e["loc"]), "message": e["msg"]} for e in exc.errors(include_input=False, include_url=False)]}
            self.emit("validation_error", {"summary": "模型动作不是合法 JSON 或不符合动作 schema。", "error_type": type(exc).__name__, **({"model_call": metadata} if metadata else {}), **diagnostics})
            feedback = {"observation": {"kind": "validation", "error": "请返回单个合法动作 JSON，字段仅 action、arguments、decision_summary。每次只能选择一个动作，不能拼接多个 JSON 对象。", "diagnostics": {k: v for k, v in diagnostics.items() if k != "content_preview"}, "remaining_decisions": self.max_decisions - self.decisions}}
            return {"action": None, "messages": messages + [{"role": "user", "content": json.dumps(feedback, ensure_ascii=False)}]}
        metadata = getattr(self.model, "last_metadata", {})
        self.emit("action", action.model_dump() | ({"model_call": metadata} if metadata else {}))
        return {"action": action.model_dump(), "messages": messages + [{"role": "assistant", "content": action.model_dump_json()}]}

    def act(self, state):
        if state["done"]:
            return {}
        if self.cancel.is_set():
            self.stop("user_cancelled", "任务已停止，未完成。")
            return {"done": True}
        action = state["action"]
        if action is None:
            return {}
        name, args = action["action"], action["arguments"]
        if name == "finish":
            try:
                self.result = validate_proposal(args, self.evidence, self.run_id, self.request.mode)
                return {"done": True}
            except ValueError as exc:
                error = str(exc) if not hasattr(exc, "errors") else "; ".join(str(e["loc"]) + ": " + e["msg"] for e in exc.errors(include_input=False, include_url=False))
                self.emit("validation_error", {"summary": error})
                observation = {"kind": "validation", "error": error}
        else:
            if self.tool_calls >= self.max_tools:
                self.stop("budget_exhausted", "工具调用次数达到上限，任务未完成。")
                return {"done": True}
            self.tool_calls += 1
            start = time.monotonic()
            observation = {"kind": "tool", "tool": name, "arguments": args}
            try:
                parsed = SearchArgs.model_validate(args) if name == "search_documents" else ReadArgs.model_validate(args)
                self.tool_occurrences[name] = self.tool_occurrences.get(name, 0) + 1
                plan = self.faults.get(name, 0)
                failed = self.tool_occurrences[name] in plan if isinstance(plan, list) else bool(plan)
                if failed:
                    if isinstance(plan, int) and plan > 0:
                        self.faults[name] -= 1
                    observation |= {"ok": False, "error": {"code": "TOOL_UNAVAILABLE", "message": "演示注入：工具暂时不可用", "recoverable": isinstance(plan, list) or plan > 0}}
                else:
                    data = self.corpus.search(**parsed.model_dump()) if name == "search_documents" else self.corpus.read(**parsed.model_dump())
                    if name == "read_snippet":
                        self.evidence[(data["document_id"], data["snippet_id"])] = data
                    observation |= {"ok": True, "data": data}
            except (ValueError, KeyError):
                observation |= {"ok": False, "error": {"code": "INVALID_TOOL_ARGUMENTS", "message": "参数不合法或文档片段不存在", "recoverable": True}}
            summary = observation.get("error", {}).get("message")
            if observation.get("ok"):
                summary = f"找到 {len(observation['data']['matches'])} 个片段" if name == "search_documents" else f"已读取 {observation['data']['document_id']} 原文"
            observation |= {"remaining_decisions": self.max_decisions - self.decisions, "remaining_tool_calls": self.max_tools - self.tool_calls}
            self.emit("tool_result", {"tool": name, "ok": observation["ok"], "summary": summary, "elapsed_ms": round((time.monotonic() - start) * 1000), "observation": observation})
        observation |= {"remaining_decisions": self.max_decisions - self.decisions, "remaining_tool_calls": self.max_tools - self.tool_calls}
        return {"messages": state["messages"] + [{"role": "user", "content": json.dumps({"observation": observation}, ensure_ascii=False)}]}

    def run(self):
        self.emit("run_started", {"mode": self.request.mode, "model": self.model.name, "corpus_hash": self.corpus.hash, "prompt_sha256": hashlib.sha256(self.system_prompt.encode()).hexdigest(), "max_decisions": self.max_decisions, "max_tools": self.max_tools})
        graph = StateGraph(GraphState)
        graph.add_node("decide", self.decide)
        graph.add_node("act", self.act)
        graph.add_edge(START, "decide")
        graph.add_edge("decide", "act")
        graph.add_conditional_edges("act", lambda state: "end" if state["done"] else "again", {"end": END, "again": "decide"})
        messages = [{"role": "system", "content": self.system_prompt}, {"role": "user", "content": json.dumps({"question": self.request.question, "history": [m.model_dump() for m in self.request.history]}, ensure_ascii=False)}]
        try:
            graph.compile().invoke({"messages": messages, "action": None, "done": False}, {"recursion_limit": 64})
        except Exception as exc:
            self.stop("internal_error", "执行发生异常，任务未完成。")
            self.emit("validation_error", {"summary": "执行异常，已安全停止。", "error_type": type(exc).__name__})
        if self.result is None:
            self.stop("internal_error", "未产生有效最终结果。")
        self.emit("final", {"output": self.result.model_dump(mode="json"), "elapsed_ms": round((time.monotonic() - self.started) * 1000), "decisions": self.decisions, "tool_calls": self.tool_calls})
        if self.output_dir:
            self.save(self.output_dir)
        return self.result

    def save(self, directory):
        directory = Path(directory)
        if (directory / "output.json").exists():
            directory /= self.run_id
        directory.mkdir(parents=True, exist_ok=True)
        self.output_dir = directory
        (directory / "input.json").write_text(self.request.model_dump_json(indent=2), encoding="utf-8")
        (directory / "prompt.txt").write_text(self.system_prompt, encoding="utf-8")
        (directory / "output.json").write_text(self.result.model_dump_json(indent=2), encoding="utf-8")
        (directory / "trace.jsonl").write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in self.events), encoding="utf-8")
