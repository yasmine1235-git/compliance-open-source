"""Marketing hyperbole check: a phrase list for obvious cases and an LLM for the rest."""

from pydantic import BaseModel

from complianceops.agents.llm import UNTRUSTED_TEXT_NOTICE, LlmClient, ask_json
from complianceops.agents.models import (
    Agent,
    AgentContext,
    Rule,
    Verdict,
    VerdictStatus,
    make_verdict,
)
from complianceops.agents.text_match import first_match, normalize
from complianceops.ingestion.chunking import MIN_CHUNK_CHARS
from complianceops.ingestion.models import Chunk


class _Finding(BaseModel):
    chunk_id: str
    explanation: str


class _Answer(BaseModel):
    findings: list[_Finding]


def _build_prompt(chunks: list[Chunk]) -> str:
    blocks = "\n".join(f'<block id="{chunk.chunk_id}">{chunk.text}</block>' for chunk in chunks)
    return (
        "You review financial marketing documents for language that is not fair, clear and "
        "not misleading, such as hyperbole or unsupported promises. "
        f"{UNTRUSTED_TEXT_NOTICE}\n"
        'Answer only with JSON: {"findings": [{"chunk_id": "<block id>", "explanation": "..."}]}. '
        "Use an empty list if there are no problems.\n"
        f"<document>\n{blocks}\n</document>"
    )


def _review_with_llm(
    rule: Rule, context: AgentContext, llm: LlmClient, chunks: list[Chunk]
) -> list[Verdict]:
    answer = ask_json(llm, _build_prompt(chunks), _Answer)
    by_id = {chunk.chunk_id: chunk for chunk in chunks}
    if any(finding.chunk_id not in by_id for finding in answer.findings):
        detail = "The model cited text that is not in the document, so its answer was discarded."
        return [make_verdict(rule, VerdictStatus.NOT_EVALUATED, context.source_doc, detail=detail)]
    if not answer.findings:
        return [make_verdict(rule, VerdictStatus.PASS, context.source_doc)]
    return [
        make_verdict(
            rule,
            VerdictStatus.FAIL,
            context.source_doc,
            by_id[finding.chunk_id],
            finding.explanation,
        )
        for finding in answer.findings
    ]


def _check_rule(rule: Rule, context: AgentContext) -> list[Verdict]:
    flagged = [
        make_verdict(rule, VerdictStatus.FAIL, context.source_doc, chunk, "Flagged phrase found.")
        for chunk in context.chunks
        if any(first_match(pattern, [normalize(chunk.text)]) for pattern in rule.trigger)
    ]
    if flagged:
        return flagged
    if context.llm is None:
        detail = "No flagged phrases, but passing this rule needs an LLM and none is configured."
        return [make_verdict(rule, VerdictStatus.NOT_EVALUATED, context.source_doc, detail=detail)]
    chunks = [chunk for chunk in context.chunks if len(chunk.text) > MIN_CHUNK_CHARS]
    return _review_with_llm(rule, context, context.llm, chunks)


def run_language_rules(context: AgentContext, rules: list[Rule]) -> list[Verdict]:
    """Flag known phrases. Only the LLM review can pass a rule."""
    return [verdict for rule in rules for verdict in _check_rule(rule, context)]


language_objectivity_agent = Agent("language_objectivity_agent", run_language_rules)
