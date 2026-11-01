"""Deterministic merge of agent verdicts into one result."""

from complianceops.agents.models import ReportStatus, Verdict, VerdictStatus


def aggregate(verdicts: list[Verdict]) -> tuple[ReportStatus, list[Verdict]]:
    """Return the overall status and the verdicts in a stable order.

    A document is only compliant if every rule was evaluated and none failed.
    """
    ordered = sorted(
        verdicts,
        key=lambda verdict: (verdict.rule_id, verdict.page or 0, verdict.chunk_id or ""),
    )
    statuses = {verdict.status for verdict in ordered}
    if VerdictStatus.FAIL in statuses:
        return ReportStatus.NON_COMPLIANT, ordered
    if VerdictStatus.NOT_EVALUATED in statuses or not ordered:
        return ReportStatus.INCOMPLETE, ordered
    return ReportStatus.COMPLIANT, ordered
