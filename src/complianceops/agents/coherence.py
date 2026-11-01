"""Comparison of claims in a marketing document with the fund's prospectus, using RAG and an LLM."""

import re
from typing import Literal

from pydantic import BaseModel

from complianceops.agents.llm import UNTRUSTED_TEXT_NOTICE, LlmAnswerError, LlmClient, ask_json
from complianceops.agents.models import (
    Agent,
    AgentContext,
    Retriever,
    Rule,
    Verdict,
    VerdictStatus,
    make_verdict,
)
from complianceops.ingestion.chunking import MIN_CHUNK_CHARS
from complianceops.ingestion.models import Chunk

_CLAIM_PATTERN = re.compile(
    r"\d|\b(fees?|costs?|charges?|risks?|returns?|benchmark|frais|risques?|rendements?|indice)\b",
    re.IGNORECASE,
)


class _Answer(BaseModel):
    status: Literal["consistent", "contradiction", "not_found"]
    prospectus_chunk_id: str | None = None
    explanation: str = ""


def _build_prompt(claim: Chunk, passages: list[Chunk]) -> str:
    blocks = "\n".join(f'<block id="{chunk.chunk_id}">{chunk.text}</block>' for chunk in passages)
    return (
        "Compare a claim from a fund marketing document with passages from the fund's prospectus. "
        f"{UNTRUSTED_TEXT_NOTICE}\n"
        'Answer only with JSON: {"status": "consistent" | "contradiction" | "not_found", '
        '"prospectus_chunk_id": "<block id or null>", "explanation": "..."}. '
        "Use not_found if the passages do not cover the claim.\n"
        f"<document>\nClaim: {claim.text}\nPassages:\n{blocks}\n</document>"
    )


def _check_claim(
    rule: Rule, context: AgentContext, claim: Chunk, passages: list[Chunk], llm: LlmClient
) -> Verdict | None:
    """Return a failure for a contradiction, ``None`` if consistent, and raise if unverified."""
    answer = ask_json(llm, _build_prompt(claim, passages), _Answer)
    if answer.status == "not_found":
        raise LlmAnswerError("The prospectus passages did not cover every claim.")
    if answer.status == "consistent":
        return None
    cited = next((p for p in passages if p.chunk_id == answer.prospectus_chunk_id), None)
    if cited is None:
        raise LlmAnswerError("The model reported a contradiction without a valid citation.")
    detail = f"{answer.explanation} Prospectus p.{cited.page}: {cited.text}"
    return make_verdict(rule, VerdictStatus.FAIL, context.source_doc, claim, detail)


def _compare_claims(
    rule: Rule,
    context: AgentContext,
    claims: list[Chunk],
    prospectus_id: str,
    prospectus_version: str,
    retrieve: Retriever,
    llm: LlmClient,
) -> list[Verdict]:
    failures = []
    unverified = None
    for claim in claims:
        passages = retrieve(claim.text, prospectus_id, prospectus_version)
        try:
            if not passages:
                raise LlmAnswerError(f"{prospectus_id} v{prospectus_version} has no indexed text.")
            failure = _check_claim(rule, context, claim, passages, llm)
        except LlmAnswerError as error:
            unverified = str(error)
            continue
        if failure:
            failures.append(failure)
    if failures:
        return failures
    if unverified:
        return [
            make_verdict(rule, VerdictStatus.NOT_EVALUATED, context.source_doc, detail=unverified)
        ]
    return [make_verdict(rule, VerdictStatus.PASS, context.source_doc)]


def run_coherence_rules(context: AgentContext, rules: list[Rule]) -> list[Verdict]:
    """Pass only if every claim was verified. Any unverified claim makes the rule unknown."""
    verdicts: list[Verdict] = []
    claims = [
        chunk
        for chunk in context.chunks
        if len(chunk.text) > MIN_CHUNK_CHARS and _CLAIM_PATTERN.search(chunk.text)
    ]
    for rule in rules:
        if context.prospectus_id is None or context.prospectus_version is None:
            detail = "No prospectus ID and version were given."
        elif context.llm is None or context.retrieve is None:
            detail = "This rule needs an LLM and none is configured."
        else:
            if not claims:
                verdicts.append(
                    make_verdict(rule, VerdictStatus.NOT_APPLICABLE, context.source_doc)
                )
                continue
            verdicts += _compare_claims(
                rule,
                context,
                claims,
                context.prospectus_id,
                context.prospectus_version,
                context.retrieve,
                context.llm,
            )
            continue
        verdicts.append(
            make_verdict(rule, VerdictStatus.NOT_EVALUATED, context.source_doc, detail=detail)
        )
    return verdicts


content_coherence_agent = Agent("content_coherence_agent", run_coherence_rules)
