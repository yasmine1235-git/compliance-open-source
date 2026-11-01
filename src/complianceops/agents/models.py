"""Data models shared by the compliance agents."""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel

from complianceops.agents.llm import LlmClient
from complianceops.ingestion.models import Chunk

Retriever = Callable[[str, str, str], list[Chunk]]
"""Finds prospectus chunks from a query, a document ID and a document version."""


class VerdictStatus(StrEnum):
    """Outcome of one rule. ``NOT_EVALUATED`` means unknown and must never be read as a pass."""

    PASS = "pass"  # noqa: S105
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"
    NOT_EVALUATED = "not_evaluated"


class ReportStatus(StrEnum):
    """Overall result of a check."""

    COMPLIANT = "compliant"
    NON_COMPLIANT = "non_compliant"
    INCOMPLETE = "incomplete"


class Rule(BaseModel):
    """A compliance rule and the public source it comes from."""

    id: str
    agent: str
    title: str
    source: str
    paragraph: str | None = None
    quote: str | None = None
    trigger: list[str] = []
    required: list[str] = []
    before_trigger: bool = False

    @property
    def citation(self) -> str:
        return f"{self.source}, para. {self.paragraph}" if self.paragraph else self.source


class Verdict(BaseModel):
    """Outcome of one rule, with evidence when the rule points at a location in the document."""

    rule_id: str
    status: VerdictStatus
    evidence_text: str | None
    source_doc: str
    page: int | None
    chunk_id: str | None
    agent: str
    latency_ms: float = 0.0
    detail: str


@dataclass(frozen=True)
class AgentContext:
    """Everything an agent may use to check one document."""

    source_doc: str
    chunks: list[Chunk]
    target_country: str | None = None
    prospectus_id: str | None = None
    prospectus_version: str | None = None
    llm: LlmClient | None = None
    retrieve: Retriever | None = field(default=None, repr=False)


def make_verdict(
    rule: Rule,
    status: VerdictStatus,
    source_doc: str,
    chunk: Chunk | None = None,
    detail: str = "",
) -> Verdict:
    """Build a verdict that cites its rule, and its evidence when there is any."""
    return Verdict(
        rule_id=rule.id,
        status=status,
        evidence_text=chunk.text if chunk else None,
        source_doc=source_doc,
        page=chunk.page if chunk else None,
        chunk_id=chunk.chunk_id if chunk else None,
        agent=rule.agent,
        detail=f"{rule.title} ({rule.citation}). {detail}".strip(),
    )


@dataclass(frozen=True)
class Agent:
    """A named check. ``run`` receives the context and the rules that belong to this agent."""

    name: str
    run: Callable[[AgentContext, list[Rule]], list[Verdict]]
