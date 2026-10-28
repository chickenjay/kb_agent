from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Status = Literal["answered", "needs_clarification", "insufficient_evidence", "incomplete"]
Mode = Literal["live", "mock"]
Reason = Literal["completed", "awaiting_clarification", "insufficient_evidence", "tool_failure", "model_failure", "user_cancelled", "budget_exhausted", "internal_error"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Message(StrictModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=16000)


class AskRequest(StrictModel):
    question: str = Field(min_length=1, max_length=4000)
    history: list[Message] = Field(default_factory=list, max_length=30)
    mode: Mode = "mock"
    scenario_id: str | None = None

    @field_validator("question")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("问题不能为空")
        return value.strip()


class CitationInput(StrictModel):
    document_id: str
    version_date: str
    snippet_id: str
    quote: str = Field(min_length=1)


class Citation(CitationInput):
    title: str
    snippet_text: str


class Conflict(StrictModel):
    description: str = Field(min_length=1)
    document_ids: list[str] = Field(min_length=2)


class Proposal(StrictModel):
    status: Status
    answer: str = Field(min_length=1)
    citations: list[CitationInput] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    follow_up_question: str | None = None
    termination_reason: Reason


class Output(Proposal):
    citations: list[Citation] = Field(default_factory=list)
    run_id: str
    mode: Mode


class Action(StrictModel):
    action: Literal["search_documents", "read_snippet", "finish"]
    arguments: dict[str, Any]
    decision_summary: str = Field(min_length=1, max_length=400)


class SearchArgs(StrictModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=10, strict=True)


class ReadArgs(StrictModel):
    document_id: str
    snippet_id: str


class Event(StrictModel):
    run_id: str
    seq: int = Field(ge=1)
    event: Literal["run_started", "action", "tool_result", "validation_error", "final"]
    step: int = Field(ge=0)
    timestamp: str
    payload: dict[str, Any]
