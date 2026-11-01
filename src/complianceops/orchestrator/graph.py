"""LangGraph workflow: every agent runs in parallel, then the verdicts are merged."""

import asyncio
import logging
import operator
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from complianceops.agents.coherence import content_coherence_agent
from complianceops.agents.language import language_objectivity_agent
from complianceops.agents.models import (
    Agent,
    AgentContext,
    ReportStatus,
    Rule,
    Verdict,
    VerdictStatus,
    make_verdict,
)
from complianceops.agents.presence import disclaimer_agent, structure_agent
from complianceops.agents.registration import sql_registration_agent
from complianceops.agents.rules import load_rules
from complianceops.orchestrator.aggregator import aggregate

logger = logging.getLogger(__name__)

ALL_AGENTS = (
    structure_agent,
    disclaimer_agent,
    language_objectivity_agent,
    content_coherence_agent,
    sql_registration_agent,
)
_AGGREGATE_NODE = "aggregate"


class _State(TypedDict, total=False):
    verdicts: Annotated[list[Verdict], operator.add]
    merged: list[Verdict]
    status: ReportStatus


def run_agent(agent: Agent, context: AgentContext, rules: list[Rule]) -> list[Verdict]:
    """Run an agent and guarantee a verdict for each of its rules.

    A rule the agent could not decide is ``not_evaluated``, so a crash can never look like a pass.
    """
    started = time.perf_counter()
    verdicts: list[Verdict] = []
    detail = "The agent did not return a result for this rule."
    if not context.chunks:
        detail = "No text could be extracted from the document."
    else:
        try:
            verdicts = agent.run(context, rules)
        except Exception:
            logger.exception("%s failed", agent.name)
            detail = "The agent failed while evaluating this rule."
    answered = {verdict.rule_id for verdict in verdicts}
    verdicts = verdicts + [
        make_verdict(rule, VerdictStatus.NOT_EVALUATED, context.source_doc, detail=detail)
        for rule in rules
        if rule.id not in answered
    ]
    latency_ms = (time.perf_counter() - started) * 1000
    return [
        verdict.model_copy(update={"agent": agent.name, "latency_ms": latency_ms})
        for verdict in verdicts
    ]


def _agent_node(
    agent: Agent, context: AgentContext, rules: list[Rule]
) -> Callable[[Any], Awaitable[dict[str, Any]]]:
    async def node(_: Any) -> dict[str, Any]:
        verdicts = await asyncio.to_thread(run_agent, agent, context, rules)
        return {"verdicts": verdicts}

    return node


def _aggregate_node(state: Any) -> dict[str, Any]:
    status, merged = aggregate(state.get("verdicts", []))
    return {"status": status, "merged": merged}


async def run_check(
    context: AgentContext,
    agents: Sequence[Agent] = ALL_AGENTS,
    rules: Sequence[Rule] | None = None,
) -> tuple[ReportStatus, list[Verdict]]:
    """Run the agents in parallel and return the overall status and the merged verdicts."""
    all_rules = load_rules() if rules is None else rules
    graph: Any = StateGraph(_State)
    graph.add_node(_AGGREGATE_NODE, _aggregate_node)
    for agent in agents:
        agent_rules = [rule for rule in all_rules if rule.agent == agent.name]
        graph.add_node(agent.name, _agent_node(agent, context, agent_rules))
        graph.add_edge(START, agent.name)
    graph.add_edge([agent.name for agent in agents], _AGGREGATE_NODE)
    graph.add_edge(_AGGREGATE_NODE, END)
    result = await graph.compile().ainvoke({"verdicts": []})
    return result["status"], result["merged"]
