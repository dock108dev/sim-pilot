"""Versioned knowledge and fail-safe interaction-routing tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sim_pilot.guidance import EvidenceKind, InteractionKind, KnowledgeVerificationStage
from sim_pilot.software_inc.errors import SoftwareIncCompatibilityError
from sim_pilot.software_inc.guidance import classify_interaction
from sim_pilot.software_inc.guidance.knowledge import SoftwareIncKnowledgeProvider


def test_checked_in_knowledge_is_versioned_provenanced_and_staged() -> None:
    provider = SoftwareIncKnowledgeProvider()

    assert provider.topics() == (
        "capabilities",
        "company",
        "contracts",
        "development",
        "employees",
        "hiring",
        "office",
        "products",
        "roles",
        "schedules",
        "servers",
        "teams",
        "training",
    )
    assert all(claim.supported_versions == ("1.8.41",) for claim in provider.catalog.claims)
    assert all(claim.provenance_locator for claim in provider.catalog.claims)
    assert {
        KnowledgeVerificationStage.RESEARCHED,
        KnowledgeVerificationStage.FIXTURE_VALIDATED,
        KnowledgeVerificationStage.LIVE_REGRESSION_PROVEN,
    } <= {claim.verification_stage for claim in provider.catalog.claims}
    assert provider.claims_for("teams", steam_build_id=None) == ()


def test_invalid_or_cross_game_knowledge_fails_closed(tmp_path: Path) -> None:
    source = json.loads(Path("src/sim_pilot/software_inc/guidance/knowledge_v1.json").read_text())
    source["claims"][0]["game_id"] = "rail-route"
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(source))

    with pytest.raises(SoftwareIncCompatibilityError, match="another game"):
        SoftwareIncKnowledgeProvider(path)


@pytest.mark.parametrize(
    ("value", "kind", "mutation"),
    [
        ("What do teams do?", InteractionKind.QUESTION, False),
        ("Can you hire a programmer?", InteractionKind.QUESTION, False),
        ("Should I hire a programmer?", InteractionKind.RECOMMENDATION, False),
        ("pause the game", InteractionKind.DELEGATION, True),
        ("/operate pause the game", InteractionKind.DELEGATION, True),
        ("/crash_course hiring", InteractionKind.CRASH_COURSE, False),
        ("set Support Alpha working hours to 7-15", InteractionKind.DELEGATION, True),
        ("assign Ada as Programmer for Support Alpha", InteractionKind.DELEGATION, True),
        ("prepare one workstation for Core", InteractionKind.DELEGATION, True),
        ("/why", InteractionKind.EXPLANATION, False),
    ],
)
def test_deterministic_routing_separates_reading_from_delegation(
    value: str, kind: InteractionKind, mutation: bool
) -> None:
    result = classify_interaction(value)

    assert result.kind is kind
    assert result.mutation_permitted is mutation
    assert result.deterministic is True


def test_ambiguous_and_missing_operation_never_permit_mutation() -> None:
    ambiguous = classify_interaction("maybe help with staffing")
    missing = classify_interaction("/operate")

    assert ambiguous.kind is InteractionKind.UNKNOWN
    assert ambiguous.clarification_required is True
    assert ambiguous.mutation_permitted is False
    assert missing.kind is InteractionKind.DELEGATION
    assert missing.clarification_required is True
    assert missing.mutation_permitted is False


def test_model_generated_text_is_not_an_evidence_kind() -> None:
    assert "model" not in {kind.value for kind in EvidenceKind}
