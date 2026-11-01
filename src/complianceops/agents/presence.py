"""Deterministic checks that required text is present: the structure and disclaimer agents."""

from complianceops.agents.models import (
    Agent,
    AgentContext,
    Rule,
    Verdict,
    VerdictStatus,
    make_verdict,
)
from complianceops.agents.text_match import blank_matches, first_match, normalize


def _check_rule(rule: Rule, context: AgentContext, texts: list[str]) -> Verdict:
    found = [first_match(pattern, texts) for pattern in rule.required]

    # A required statement can contain trigger words ("past performance does not predict..."),
    # so it must not count as the trigger.
    searchable = texts
    for pattern in rule.required:
        searchable = blank_matches(pattern, searchable)
    triggers = [first_match(pattern, searchable) for pattern in rule.trigger]
    trigger = min((position for position in triggers if position), default=None)

    if rule.trigger and trigger is None:
        return make_verdict(rule, VerdictStatus.NOT_APPLICABLE, context.source_doc)

    trigger_chunk = context.chunks[trigger[0]] if trigger else None
    if not all(found):
        detail = "Required text was not found."
        return make_verdict(rule, VerdictStatus.FAIL, context.source_doc, trigger_chunk, detail)

    first_required = found[0]
    if rule.before_trigger and trigger and first_required and first_required > trigger:
        detail = "The required statement appears after the content it should precede."
        return make_verdict(rule, VerdictStatus.FAIL, context.source_doc, trigger_chunk, detail)

    evidence = context.chunks[first_required[0]] if first_required else None
    return make_verdict(rule, VerdictStatus.PASS, context.source_doc, evidence)


def run_presence_rules(context: AgentContext, rules: list[Rule]) -> list[Verdict]:
    """Evaluate rules on whether their required text appears in the document."""
    texts = [normalize(chunk.text) for chunk in context.chunks]
    return [_check_rule(rule, context, texts) for rule in rules]


structure_agent = Agent("structure_agent", run_presence_rules)
disclaimer_agent = Agent("disclaimer_agent", run_presence_rules)
