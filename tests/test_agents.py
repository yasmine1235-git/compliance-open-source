"""Tests for the rules and compliance agents."""

import json
import re

import pytest

from complianceops.agents.coherence import run_coherence_rules
from complianceops.agents.language import run_language_rules
from complianceops.agents.llm import LlmClient
from complianceops.agents.models import AgentContext, Rule, Verdict, VerdictStatus
from complianceops.agents.presence import run_presence_rules
from complianceops.agents.registration import is_valid_isin, run_registration_rules
from complianceops.agents.rules import load_rules
from complianceops.ingestion.chunking import chunk_blocks
from complianceops.ingestion.models import Block, BlockKind, Chunk
from complianceops.orchestrator.graph import ALL_AGENTS

VALID_FR_ONLY = "FRCOPS000033"
VALID_FR_AND_DE = "FRCOPS000017"
UNREGISTERED_BUT_VALID = "US0378331005"
BAD_CHECK_DIGIT = "FRCOPS000018"


class ScriptedLlm:
    """Returns prepared answers in order and records the prompts it was given."""

    def __init__(self, *answers: object) -> None:
        self._answers = list(answers)
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        answer = self._answers.pop(0)
        return answer if isinstance(answer, str) else json.dumps(answer)


def _chunks(*pages: str) -> list[Chunk]:
    blocks = [Block(number, text, BlockKind.TEXT) for number, text in enumerate(pages, start=1)]
    return chunk_blocks(blocks, "doc", "1", "deck.pdf", min_chars=0)


def _context(*pages: str, llm: LlmClient | None = None, country: str | None = None) -> AgentContext:
    return AgentContext(
        source_doc="deck.pdf", chunks=_chunks(*pages), llm=llm, target_country=country
    )


def _rule(rule_id: str) -> Rule:
    return next(rule for rule in load_rules() if rule.id == rule_id)


def _presence(rule_id: str, *pages: str) -> Verdict:
    return run_presence_rules(_context(*pages), [_rule(rule_id)])[0]


class TestRuleFile:
    def test_ids_are_unique_and_agents_exist(self) -> None:
        rules = load_rules()
        names = {agent.name for agent in ALL_AGENTS}

        assert len({rule.id for rule in rules}) == len(rules)
        assert {rule.agent for rule in rules} == names

    def test_patterns_compile(self) -> None:
        for rule in load_rules():
            for pattern in rule.trigger + rule.required:
                re.compile(pattern)

    def test_every_rule_cites_a_source(self) -> None:
        for rule in load_rules():
            assert rule.source
            if rule.source.startswith("ESMA"):
                assert rule.paragraph
                assert rule.quote


class TestPresenceRules:
    @pytest.mark.parametrize(
        ("rule_id", "text"),
        [
            ("MC-IDENT-001", "This is a Marketing Communication."),
            ("MC-IDENT-001", "#MarketingCommunication"),
            ("MC-IDENT-001", "Ceci est une communication publicitaire."),
            ("MC-DISC-001", "Please read the prospectus and the KID before investing."),
            ("MC-DISC-001", "Veuillez consulter le prospectus et le DIC."),
            ("MC-POLICY-001", "Investment policy"),
            ("MC-POLICY-001", "Politique d'investissement"),
            ("MC-POLICY-001", "Politique d’investissement"),
        ],
    )
    def test_always_required_text_passes(self, rule_id: str, text: str) -> None:
        assert _presence(rule_id, text).status is VerdictStatus.PASS

    @pytest.mark.parametrize(
        ("rule_id", "text"),
        [
            ("MC-IDENT-001", "A great new fund."),
            ("MC-DISC-001", "Please read the prospectus before investing."),
            ("MC-DISC-001", "Read the KID before investing."),
            ("MC-POLICY-001", "A great new fund."),
        ],
    )
    def test_missing_always_required_text_fails_without_a_location(
        self, rule_id: str, text: str
    ) -> None:
        verdict = _presence(rule_id, text)

        assert verdict.status is VerdictStatus.FAIL
        assert verdict.page is None
        assert verdict.chunk_id is None

    @pytest.mark.parametrize(
        ("rule_id", "text"),
        [
            ("MC-PERF-001", "A fund for the long term."),
            ("MC-FUTURE-001", "A fund for the long term."),
            ("MC-FUTURE-002", "A fund for the long term."),
            ("MC-ESG-001", "A fund for the long term."),
            ("MC-RISK-001", "A fund for the long term."),
            ("MC-COST-001", "A fund for the long term."),
            ("MC-LEVERAGE-001", "A fund for the long term."),
        ],
    )
    def test_conditional_rule_does_not_apply_without_its_trigger(
        self, rule_id: str, text: str
    ) -> None:
        assert _presence(rule_id, text).status is VerdictStatus.NOT_APPLICABLE

    @pytest.mark.parametrize(
        ("rule_id", "trigger_text", "required_text"),
        [
            ("MC-FUTURE-001", "Our target return is 7%.", "Subject to taxation."),
            ("MC-FUTURE-002", "Our target return is 7%.", "This may lead to a financial loss."),
            ("MC-FUTURE-002", "Rendement cible de 7%.", "Vous pouvez perdre votre capital."),
            ("MC-ESG-001", "An ESG fund.", "Consider all the characteristics of the fund."),
            ("MC-RISK-001", "High returns.", "Risks: market risk."),
            ("MC-RISK-001", "Rendement eleve.", "Risque de marche."),
            ("MC-COST-001", "Ongoing fees of 1%.", "Costs reduce your return."),
            ("MC-LEVERAGE-001", "The fund uses leverage.", "It may increase potential losses."),
            ("MC-LEVERAGE-001", "Effet de levier.", "Les pertes peuvent etre amplifiees."),
        ],
    )
    def test_conditional_rule_needs_its_text_once_triggered(
        self, rule_id: str, trigger_text: str, required_text: str
    ) -> None:
        missing = _presence(rule_id, "Cover page", trigger_text)
        assert missing.status is VerdictStatus.FAIL
        assert missing.page == 2
        assert missing.evidence_text == trigger_text

        assert _presence(rule_id, trigger_text, required_text).status is VerdictStatus.PASS

    @pytest.mark.parametrize("text", ["A risk-free return.", "Sans risque : rendement eleve."])
    def test_claiming_no_risk_does_not_count_as_describing_risks(self, text: str) -> None:
        assert _presence("MC-RISK-001", text).status is VerdictStatus.FAIL

    def test_required_statement_across_a_line_break_is_found(self) -> None:
        verdict = _presence(
            "MC-PERF-001",
            "Past performance\ndoes not predict\nfuture returns. Past performance: 5%.",
        )

        assert verdict.status is VerdictStatus.PASS

    def test_statement_must_come_before_past_performance(self) -> None:
        statement = "Past performance does not predict future returns."
        figures = "Past performance: 5% in 2023."

        assert _presence("MC-PERF-001", statement, figures).status is VerdictStatus.PASS
        late = _presence("MC-PERF-001", figures, statement)
        assert late.status is VerdictStatus.FAIL
        assert late.page == 1

    def test_statement_alone_does_not_trigger_the_rule(self) -> None:
        verdict = _presence("MC-PERF-001", "Past performance does not predict future returns.")

        assert verdict.status is VerdictStatus.NOT_APPLICABLE

    def test_past_performance_without_statement_fails(self) -> None:
        assert _presence("MC-PERF-001", "Annualised return: 9%.").status is VerdictStatus.FAIL

    def test_verdict_cites_the_guideline(self) -> None:
        assert "ESMA34-45-1272, para. 47" in _presence("MC-PERF-001", "Annual return: 9%.").detail


class TestRegistration:
    @pytest.mark.parametrize(
        ("isin", "valid"),
        [
            (VALID_FR_ONLY, True),
            (VALID_FR_AND_DE, True),
            (UNREGISTERED_BUT_VALID, True),
            (BAD_CHECK_DIGIT, False),
        ],
    )
    def test_isin_check_digit(self, isin: str, valid: bool) -> None:
        assert is_valid_isin(isin) is valid

    def _run(self, text: str, country: str | None) -> dict[str, list[Verdict]]:
        rules = [_rule("REG-001"), _rule("REG-002")]
        verdicts = run_registration_rules(_context(text, country=country), rules)
        return {rule.id: [v for v in verdicts if v.rule_id == rule.id] for rule in rules}

    def test_registered_and_authorised_fund_passes(self) -> None:
        results = self._run(f"ISIN {VALID_FR_AND_DE}", "DE")

        assert results["REG-001"][0].status is VerdictStatus.PASS
        assert results["REG-002"][0].status is VerdictStatus.PASS

    def test_fund_not_authorised_in_target_country_fails(self) -> None:
        results = self._run(f"ISIN {VALID_FR_ONLY}", "DE")

        assert results["REG-001"][0].status is VerdictStatus.PASS
        assert results["REG-002"][0].status is VerdictStatus.FAIL
        assert results["REG-002"][0].page == 1

    @pytest.mark.parametrize("isin", [BAD_CHECK_DIGIT, UNREGISTERED_BUT_VALID])
    def test_invalid_or_unknown_isin_fails(self, isin: str) -> None:
        results = self._run(f"ISIN {isin}", "FR")

        assert results["REG-001"][0].status is VerdictStatus.FAIL
        assert isin in results["REG-001"][0].detail

    def test_missing_country_is_not_evaluated(self) -> None:
        results = self._run(f"ISIN {VALID_FR_ONLY}", None)

        assert results["REG-002"][0].status is VerdictStatus.NOT_EVALUATED

    def test_document_without_isin_is_not_evaluated(self) -> None:
        results = self._run("No identifier here.", "FR")

        assert results["REG-001"][0].status is VerdictStatus.NOT_EVALUATED
        assert results["REG-002"][0].status is VerdictStatus.NOT_EVALUATED

    def test_injection_style_text_is_not_treated_as_sql(self) -> None:
        results = self._run(f"ISIN {VALID_FR_ONLY}", "FR' OR '1'='1")

        assert results["REG-002"][0].status is VerdictStatus.FAIL


class TestLanguage:
    def _run(self, *pages: str, llm: LlmClient | None = None) -> list[Verdict]:
        return run_language_rules(_context(*pages, llm=llm), [_rule("LANG-001")])

    @pytest.mark.parametrize(
        "text",
        [
            "A risk-free investment.",
            "Guaranteed returns every year.",
            "You cannot lose.",
            "Un placement sans risque.",
            "Rendement garanti chaque annee.",
        ],
    )
    def test_flagged_phrase_fails_without_needing_llm(self, text: str) -> None:
        verdicts = self._run("Cover page", text)

        assert [(verdict.status, verdict.page) for verdict in verdicts] == [(VerdictStatus.FAIL, 2)]

    def test_negated_phrase_is_not_flagged(self) -> None:
        verdicts = self._run("This fund is not risk-free.")

        assert verdicts[0].status is VerdictStatus.NOT_EVALUATED

    def test_no_phrases_and_no_llm_is_not_a_pass(self) -> None:
        verdicts = self._run("A carefully worded description of the fund.")

        assert [verdict.status for verdict in verdicts] == [VerdictStatus.NOT_EVALUATED]

    def test_llm_can_pass_the_rule(self) -> None:
        llm = ScriptedLlm({"findings": []})

        verdicts = self._run("A carefully worded description of the fund.", llm=llm)

        assert verdicts[0].status is VerdictStatus.PASS
        assert "untrusted" in llm.prompts[0]

    def test_llm_finding_fails_with_evidence_from_the_document(self) -> None:
        text = "The best fund you will ever find anywhere."
        chunk_id = _chunks(text)[0].chunk_id
        llm = ScriptedLlm({"findings": [{"chunk_id": chunk_id, "explanation": "Hyperbole."}]})

        verdict = self._run(text, llm=llm)[0]

        assert verdict.status is VerdictStatus.FAIL
        assert verdict.evidence_text == text

    def test_llm_citation_outside_the_document_is_discarded(self) -> None:
        llm = ScriptedLlm({"findings": [{"chunk_id": "invented", "explanation": "Hyperbole."}]})

        verdicts = self._run("A carefully worded description of the fund.", llm=llm)

        assert [verdict.status for verdict in verdicts] == [VerdictStatus.NOT_EVALUATED]


class TestCoherence:
    PASSAGE = Chunk("p1", "prospectus", "3", "prospectus.pdf", 12, BlockKind.TEXT, "The fee is 2%.")

    def _run(
        self,
        *pages: str,
        llm: LlmClient | None,
        passages: list[Chunk] | None = None,
        prospectus: str | None = "prospectus",
    ) -> list[Verdict]:
        found = [self.PASSAGE] if passages is None else passages
        context = AgentContext(
            source_doc="deck.pdf",
            chunks=_chunks(*pages),
            llm=llm,
            retrieve=lambda *_: found,
            prospectus_id=prospectus,
            prospectus_version="3" if prospectus else None,
        )
        return run_coherence_rules(context, [_rule("CONS-001")])

    CLAIM = "The management fee of the fund is 1.5%."

    def test_without_prospectus_is_not_evaluated(self) -> None:
        verdicts = self._run(self.CLAIM, llm=ScriptedLlm(), prospectus=None)

        assert verdicts[0].status is VerdictStatus.NOT_EVALUATED

    def test_without_llm_is_not_evaluated(self) -> None:
        assert self._run(self.CLAIM, llm=None)[0].status is VerdictStatus.NOT_EVALUATED

    def test_contradiction_fails_and_cites_the_prospectus(self) -> None:
        llm = ScriptedLlm(
            {"status": "contradiction", "prospectus_chunk_id": "p1", "explanation": "Fee differs."}
        )

        verdict = self._run(self.CLAIM, llm=llm)[0]

        assert verdict.status is VerdictStatus.FAIL
        assert verdict.evidence_text == self.CLAIM
        assert "Prospectus p.12" in verdict.detail

    def test_contradiction_with_invented_citation_is_not_a_finding(self) -> None:
        llm = ScriptedLlm({"status": "contradiction", "prospectus_chunk_id": "invented"})

        assert self._run(self.CLAIM, llm=llm)[0].status is VerdictStatus.NOT_EVALUATED

    def test_all_claims_consistent_passes(self) -> None:
        llm = ScriptedLlm({"status": "consistent"})

        assert self._run(self.CLAIM, llm=llm)[0].status is VerdictStatus.PASS

    def test_one_uncovered_claim_prevents_a_pass(self) -> None:
        llm = ScriptedLlm({"status": "consistent"}, {"status": "not_found"})

        verdicts = self._run(self.CLAIM, "The ongoing risk level of the fund is 4.", llm=llm)

        assert [verdict.status for verdict in verdicts] == [VerdictStatus.NOT_EVALUATED]

    def test_a_contradiction_is_still_reported_alongside_an_uncovered_claim(self) -> None:
        llm = ScriptedLlm(
            {"status": "not_found"},
            {"status": "contradiction", "prospectus_chunk_id": "p1", "explanation": "Differs."},
        )

        verdicts = self._run(self.CLAIM, "The ongoing risk level of the fund is 4.", llm=llm)

        assert [verdict.status for verdict in verdicts] == [VerdictStatus.FAIL]

    def test_unindexed_prospectus_is_not_evaluated(self) -> None:
        verdicts = self._run(self.CLAIM, llm=ScriptedLlm(), passages=[])

        assert verdicts[0].status is VerdictStatus.NOT_EVALUATED

    def test_malformed_llm_answer_is_not_evaluated(self) -> None:
        assert self._run(self.CLAIM, llm=ScriptedLlm("not json"))[0].status is (
            VerdictStatus.NOT_EVALUATED
        )

    def test_document_without_claims_does_not_apply(self) -> None:
        verdicts = self._run("A description of our team and offices.", llm=ScriptedLlm())

        assert verdicts[0].status is VerdictStatus.NOT_APPLICABLE
