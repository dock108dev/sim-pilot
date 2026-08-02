"""Validated, versioned Software Inc. knowledge catalog."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sim_pilot.guidance import KnowledgeClaim
from sim_pilot.software_inc.errors import SoftwareIncCompatibilityError

SUPPORTED_TOPICS = frozenset(
    {
        "capabilities",
        "company",
        "contracts",
        "employees",
        "hiring",
        "office",
        "products",
        "development",
        "roles",
        "schedules",
        "servers",
        "teams",
        "training",
    }
)
SUPPORTED_ACTIONS = frozenset(
    {
        "create_team",
        "hire_employee",
        "observe_applicants",
        "open_manage_teams",
        "pause",
        "resume",
        "assign_employee_role",
        "set_team_working_hours",
        "open_contracts",
        "accept_contract",
        "advance_contract",
        "review_contract",
        "promote_contract",
        "release_contract",
        "start_education",
        "advance_education",
        "create_product",
        "advance_product",
        "review_product",
        "iterate_product",
        "promote_product",
        "hold_product",
        "resume_product",
    }
)
DEFAULT_KNOWLEDGE_PATH = Path(__file__).with_name("knowledge_v1.json")


class SoftwareIncKnowledgeCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    schema_version: Literal[1] = 1
    claims: tuple[KnowledgeClaim, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_catalog(self) -> SoftwareIncKnowledgeCatalog:
        identifiers = tuple(claim.claim_id for claim in self.claims)
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("knowledge claim IDs must be unique")
        for claim in self.claims:
            if claim.game_id != "software-inc":
                raise ValueError("Software Inc. catalog contains another game")
            if claim.topic not in SUPPORTED_TOPICS:
                raise ValueError(f"unsupported Software Inc. knowledge topic {claim.topic!r}")
            unknown = set(claim.related_actions) - SUPPORTED_ACTIONS
            if unknown:
                raise ValueError(f"knowledge claim references unknown actions: {sorted(unknown)}")
        return self


class SoftwareIncKnowledgeProvider:
    def __init__(self, path: Path = DEFAULT_KNOWLEDGE_PATH) -> None:
        self._path = path
        try:
            self._catalog = SoftwareIncKnowledgeCatalog.model_validate_json(
                path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as error:
            raise SoftwareIncCompatibilityError(
                f"Software Inc. knowledge catalog is invalid: {error}"
            ) from error

    @property
    def catalog(self) -> SoftwareIncKnowledgeCatalog:
        return self._catalog

    def topics(self) -> tuple[str, ...]:
        return tuple(sorted({claim.topic for claim in self._catalog.claims}))

    def claims_for(
        self, topic: str, *, game_version: str = "1.8.41", steam_build_id: str | None = None
    ) -> tuple[KnowledgeClaim, ...]:
        normalized = topic.strip().casefold().replace("-", "_")
        if normalized not in SUPPORTED_TOPICS:
            raise SoftwareIncCompatibilityError(
                f"unknown knowledge topic {topic!r}; choose {', '.join(sorted(SUPPORTED_TOPICS))}"
            )
        return tuple(
            claim
            for claim in self._catalog.claims
            if claim.topic == normalized
            and game_version in claim.supported_versions
            and (
                not claim.supported_builds
                or (steam_build_id is not None and steam_build_id in claim.supported_builds)
            )
        )

    def claim(self, claim_id: str) -> KnowledgeClaim:
        matches = [claim for claim in self._catalog.claims if claim.claim_id == claim_id]
        if len(matches) != 1:
            raise SoftwareIncCompatibilityError(f"unknown knowledge claim {claim_id!r}")
        return matches[0]


__all__ = [
    "DEFAULT_KNOWLEDGE_PATH",
    "SUPPORTED_ACTIONS",
    "SUPPORTED_TOPICS",
    "SoftwareIncKnowledgeCatalog",
    "SoftwareIncKnowledgeProvider",
]
