"""Tests for the verdict aggregator and the LangGraph workflow."""

import asyncio
import threading

from complianceops.agents.models import (
    Agent,
    AgentContext,
    ReportStatus,
    Rule,
    Verdict,
    VerdictStatus,
    make_verdict,
)
from complianceops.ingestion.models import BlockKind, Chunk
from complianceops.orchestrator.aggregator import aggregate
from complianceops.orchestrator.graph import ALL_AGENTS, run_check

CHUNK = Chunk("c1", "doc", "1", "deck.pdf", 1, BlockKind.TEXT, "Some text in the document.")
CONTEXT = AgentContext(source_doc="deck.pdf", chunks=[CHUNK])


def _rule(rule_id: str, agent: str) -> Rule:
    return Rule(id=rule_id, agent=agent, title=rule_id, source="Test")


def _verdict(rule_id: str, status: VerdictStatus, page: int | None = None) -> Verdict:
    chunk = Chunk(f"c{page}", "doc", "1", "d", page, BlockKind.TEXT, "text") if page else None
    return make_verdict(_rule(rule_id, "agent"), status, "deck.pdf", chunk)


def _passing_agent(name: str) -> Agent:
    def run(context: AgentContext, rules: list[Rule]) -> list[Verdict]:
        return [make_verdict(rule, VerdictStatus.PASS, context.source_doc) for rule in rules]

    return Agent(name, run)


class TestAggregate:
    def test_all_passing_or_not_applicable_is_compliant(self) -> None:
        status, _ = aggregate(
            [_verdict("A", VerdictStatus.PASS), _verdict("B", VerdictStatus.NOT_APPLICABLE)]
        )

        assert status is ReportStatus.COMPLIANT

    def test_one_failure_is_non_compliant_even_with_unknowns(self) -> None:
        status, _ = aggregate(
            [
                _verdict("A", VerdictStatus.PASS),
                _verdict("B", VerdictStatus.NOT_EVALUATED),
                _verdict("C", VerdictStatus.FAIL),
            ]
        )

        assert status is ReportStatus.NON_COMPLIANT

    def test_one_unknown_without_failures_is_incomplete(self) -> None:
        status, _ = aggregate(
            [_verdict("A", VerdictStatus.PASS), _verdict("B", VerdictStatus.NOT_EVALUATED)]
        )

        assert status is ReportStatus.INCOMPLETE

    def test_no_verdicts_is_incomplete(self) -> None:
        assert aggregate([])[0] is ReportStatus.INCOMPLETE

    def test_order_does_not_depend_on_input_order(self) -> None:
        verdicts = [
            _verdict("B", VerdictStatus.PASS),
            _verdict("A", VerdictStatus.FAIL, page=2),
            _verdict("A", VerdictStatus.FAIL, page=1),
        ]

        forward = aggregate(verdicts)[1]
        backward = aggregate(list(reversed(verdicts)))[1]

        assert forward == backward
        assert [(v.rule_id, v.page) for v in forward] == [("A", 1), ("A", 2), ("B", None)]


class TestRunCheck:
    def test_merges_every_agent_with_latency(self) -> None:
        rules = [_rule("A", "first"), _rule("B", "second")]

        status, verdicts = asyncio.run(
            run_check(CONTEXT, [_passing_agent("first"), _passing_agent("second")], rules)
        )

        assert status is ReportStatus.COMPLIANT
        assert [(verdict.rule_id, verdict.agent) for verdict in verdicts] == [
            ("A", "first"),
            ("B", "second"),
        ]
        assert all(verdict.latency_ms >= 0 for verdict in verdicts)

    def test_agents_run_in_parallel(self) -> None:
        # Each agent waits for the other, so this only completes if both run at the same time.
        barrier = threading.Barrier(2, timeout=10)

        def waiting_agent(name: str) -> Agent:
            def run(context: AgentContext, rules: list[Rule]) -> list[Verdict]:
                barrier.wait()
                return [
                    make_verdict(rule, VerdictStatus.PASS, context.source_doc) for rule in rules
                ]

            return Agent(name, run)

        rules = [_rule("A", "first"), _rule("B", "second")]
        status, _ = asyncio.run(
            run_check(CONTEXT, [waiting_agent("first"), waiting_agent("second")], rules)
        )

        assert status is ReportStatus.COMPLIANT

    def test_crashing_agent_is_not_evaluated_and_others_still_finish(self) -> None:
        def crash(context: AgentContext, rules: list[Rule]) -> list[Verdict]:
            raise RuntimeError("boom")

        rules = [_rule("A", "broken"), _rule("B", "working")]
        status, verdicts = asyncio.run(
            run_check(CONTEXT, [Agent("broken", crash), _passing_agent("working")], rules)
        )

        assert status is ReportStatus.INCOMPLETE
        assert {verdict.rule_id: verdict.status for verdict in verdicts} == {
            "A": VerdictStatus.NOT_EVALUATED,
            "B": VerdictStatus.PASS,
        }

    def test_rule_skipped_by_its_agent_is_not_evaluated(self) -> None:
        def partial(context: AgentContext, rules: list[Rule]) -> list[Verdict]:
            return [make_verdict(rules[0], VerdictStatus.PASS, context.source_doc)]

        rules = [_rule("A", "partial"), _rule("B", "partial")]
        status, verdicts = asyncio.run(run_check(CONTEXT, [Agent("partial", partial)], rules))

        assert status is ReportStatus.INCOMPLETE
        assert {verdict.rule_id: verdict.status for verdict in verdicts} == {
            "A": VerdictStatus.PASS,
            "B": VerdictStatus.NOT_EVALUATED,
        }

    def test_document_without_text_is_incomplete_not_failed(self) -> None:
        empty = AgentContext(source_doc="deck.pdf", chunks=[])

        status, verdicts = asyncio.run(run_check(empty, ALL_AGENTS))

        assert status is ReportStatus.INCOMPLETE
        assert {verdict.status for verdict in verdicts} == {VerdictStatus.NOT_EVALUATED}
