"""Deterministic check of ISINs and marketing authorisations against a SQL registry."""

import re
import sqlite3
from contextlib import closing
from importlib import resources

from complianceops.agents.models import (
    Agent,
    AgentContext,
    Rule,
    Verdict,
    VerdictStatus,
    make_verdict,
)
from complianceops.ingestion.models import Chunk

_ISIN_PATTERN = re.compile(r"\b[A-Z]{2}[A-Z0-9]{9}[0-9]\b")
_VALIDITY_RULE = "REG-001"
_AUTHORISATION_RULE = "REG-002"


def is_valid_isin(isin: str) -> bool:
    """Return whether an ISIN's final digit matches its ISO 6166 check digit."""
    digits = "".join(str(int(char, 36)) for char in isin)
    total = 0
    for position, digit in enumerate(int(char) for char in reversed(digits)):
        doubled = digit * 2 if position % 2 else digit
        total += doubled - 9 if doubled > 9 else doubled
    return total % 10 == 0


def _find_isins(chunks: list[Chunk]) -> dict[str, Chunk]:
    isins: dict[str, Chunk] = {}
    for chunk in chunks:
        for isin in _ISIN_PATTERN.findall(chunk.text):
            isins.setdefault(isin, chunk)
    return isins


def _connect() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    schema = resources.files("complianceops.agents").joinpath("registry_sample.sql")
    connection.executescript(schema.read_text("utf-8"))
    return connection


def _check_validity(
    rule: Rule, context: AgentContext, isins: dict[str, Chunk], db: sqlite3.Connection
) -> list[Verdict]:
    failures = []
    for isin, chunk in isins.items():
        if not is_valid_isin(isin):
            detail = f"{isin} has an invalid check digit."
        elif not db.execute("SELECT 1 FROM funds WHERE isin = ?", (isin,)).fetchone():
            detail = f"{isin} is not in the registry."
        else:
            continue
        failures.append(make_verdict(rule, VerdictStatus.FAIL, context.source_doc, chunk, detail))
    return failures or [make_verdict(rule, VerdictStatus.PASS, context.source_doc)]


def _check_authorisation(
    rule: Rule, context: AgentContext, isins: dict[str, Chunk], db: sqlite3.Connection
) -> list[Verdict]:
    if context.target_country is None:
        detail = "No target country was given."
        return [make_verdict(rule, VerdictStatus.NOT_EVALUATED, context.source_doc, detail=detail)]
    failures = []
    for isin, chunk in isins.items():
        query = "SELECT 1 FROM authorisations WHERE isin = ? AND country = ?"
        if not db.execute(query, (isin, context.target_country)).fetchone():
            detail = f"{isin} has no authorisation for {context.target_country}."
            failures.append(
                make_verdict(rule, VerdictStatus.FAIL, context.source_doc, chunk, detail)
            )
    return failures or [make_verdict(rule, VerdictStatus.PASS, context.source_doc)]


def run_registration_rules(context: AgentContext, rules: list[Rule]) -> list[Verdict]:
    """Check every ISIN in the document. Without an ISIN there is nothing to verify."""
    isins = _find_isins(context.chunks)
    if not isins:
        detail = "No ISIN was found in the document."
        return [
            make_verdict(rule, VerdictStatus.NOT_EVALUATED, context.source_doc, detail=detail)
            for rule in rules
        ]
    verdicts: list[Verdict] = []
    with closing(_connect()) as db:
        for rule in rules:
            if rule.id == _VALIDITY_RULE:
                verdicts += _check_validity(rule, context, isins, db)
            elif rule.id == _AUTHORISATION_RULE:
                verdicts += _check_authorisation(rule, context, isins, db)
    return verdicts


sql_registration_agent = Agent("sql_registration_agent", run_registration_rules)
