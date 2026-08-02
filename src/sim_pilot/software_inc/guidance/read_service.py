"""Read-only Software Inc. teaching and advisory services."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sim_pilot.guidance import (
    CapabilityEvidenceStage,
    CrashCourseResponse,
    EvidenceKind,
    EvidenceReference,
    GuidanceStatus,
    KnowledgeClaim,
    QuestionResponse,
    Recommendation,
    RecommendationResponse,
)
from sim_pilot.software_inc.ui.office import project_team_readiness

from .capabilities import action_capability
from .context import SoftwareIncGuidanceContext
from .knowledge import SoftwareIncKnowledgeProvider
from .state import SoftwareIncStateView

_RECOMMENDATION_LIFETIME = timedelta(minutes=5)


class SoftwareIncReadGuidanceService:
    """Question, course, status, and recommendation paths with no UI execution dependency."""

    def __init__(self, knowledge: SoftwareIncKnowledgeProvider) -> None:
        self._knowledge = knowledge

    def answer(self, question: str, context: SoftwareIncGuidanceContext) -> QuestionResponse:
        normalized = " ".join(question.strip().casefold().replace("-", " ").split())
        hours = re.search(r"what hours does (?P<team>.+?) work", normalized)
        if hours:
            return self._team_readiness_answer(question, context, hours.group("team"), mode="hours")
        desks = re.search(r"does (?P<team>.+?) have enough (?:desks|workspace)", normalized)
        if desks:
            return self._team_readiness_answer(
                question, context, desks.group("team"), mode="capacity"
            )
        if "what office equipment are we missing" in normalized:
            team = self._single_team_name(context)
            if team is None:
                return self._unavailable(
                    question,
                    context,
                    "Name one exact team because the current company does not resolve a "
                    "single team.",
                )
            return self._team_readiness_answer(question, context, team, mode="equipment")
        if "need a server" in normalized:
            return self._server_requirement_answer(question, context)
        if "what are contracts" in normalized or "how do contracts work" in normalized:
            return self._knowledge_answer(
                question,
                "software-inc.contracts.lifecycle",
                context,
                follow_up=(
                    "Use `software-inc contracts recommend --team <team> "
                    "--minimum-reward <amount>` for current-save advice."
                ),
            )
        if (
            "how do products work" in normalized
            or "what is a game engine" in normalized
            or "how does product development work" in normalized
        ):
            claim_id = (
                "software-inc.development.current-lifecycle"
                if "development" in normalized
                else "software-inc.products.current-configuration"
            )
            return self._knowledge_answer(
                question,
                claim_id,
                context,
                follow_up=(
                    "Use `software-inc crash-course products` or "
                    "`software-inc crash-course development`."
                ),
            )
        if "can i afford atlas" in normalized or "atlas runway" in normalized:
            return self._knowledge_answer(
                question,
                "software-inc.products.runway-policy",
                context,
                follow_up=(
                    "Open the New software window and use `software-inc products recommend "
                    "--minimum-cash-reserve 50000`."
                ),
            )
        if "when is a contract unsuitable" in normalized or "contract unsuitable" in normalized:
            return self._knowledge_answer(
                question,
                "software-inc.contracts.suitability",
                context,
                follow_up="Open the Contracts window before requesting a recommendation.",
            )
        if (
            "how does training work" in normalized
            or "how does education work" in normalized
            or "what is system design" in normalized
        ):
            return self._knowledge_answer(
                question,
                "software-inc.training.education-model",
                context,
                follow_up=(
                    "Use `software-inc training recommend --team Core "
                    "--minimum-cash-reserve <amount>` for current-save advice."
                ),
            )
        if "who should" in normalized and ("train" in normalized or "educat" in normalized):
            return self._knowledge_answer(
                question,
                "software-inc.training.suitability-and-cost",
                context,
                follow_up=(
                    "Name an exact team and cash reserve with `software-inc training recommend`."
                ),
            )
        if (
            "why isn't this employee working" in normalized
            or "why isnt this employee working" in normalized
        ):
            return self._unavailable(
                question,
                context,
                "“this employee” is ambiguous; name the employee and team. Current observations "
                "can check role, team, schedule, and workspace but not every absence or "
                "task cause.",
            )
        if "what do teams do" in normalized or "what are teams" in normalized:
            return self._knowledge_answer(
                question,
                "software-inc.teams.purpose",
                context,
                follow_up="Ask “What are my teams?” to inspect the current company.",
            )
        if "why would i hire a programmer" in normalized or "why hire a programmer" in normalized:
            return self._knowledge_answer(
                question,
                "software-inc.hiring.programmer",
                context,
                follow_up="Ask “How does hiring work?” for the bounded approval workflow.",
            )
        if "how does hiring work" in normalized:
            claims = tuple(
                claim
                for claim in (
                    self._applicable_claim("software-inc.hiring.programmer", context),
                    self._applicable_claim("software-inc.hiring.separate-approvals", context),
                )
                if claim is not None
            )
            if len(claims) != 2:
                return self._unavailable(
                    question,
                    context,
                    "Hiring knowledge is not verified for the detected game identity.",
                )
            return QuestionResponse(
                question=question,
                status=GuidanceStatus.ANSWERED,
                answer=(
                    "The bounded workflow observes a paid Programmer applicant search first, "
                    "then selects one eligible applicant under your monthly salary ceiling. "
                    "The search charge and recurring salary require separate exact approvals."
                ),
                evidence=tuple(_claim_evidence(claim) for claim in claims),
                limitation="The Phase 4 staffing workflow is not live-enabled yet.",
                follow_up="Use `software-inc crash-course hiring` for the complete boundary.",
            )
        if "separate approval" in normalized or "search need" in normalized:
            return self._knowledge_answer(
                question,
                "software-inc.hiring.separate-approvals",
                context,
                follow_up="Ask “What can Sim Pilot currently control?” before delegating.",
            )
        if "recurring payroll" in normalized or "monthly payroll" in normalized:
            if context.state is not None and context.state.recurring_payroll is not None:
                return QuestionResponse(
                    question=question,
                    status=GuidanceStatus.ANSWERED,
                    answer=(
                        "Observed recurring employee payroll is "
                        f"{_money(context.state.recurring_payroll)} per month."
                    ),
                    evidence=(_state_evidence(context.state, "employees.salary", "payroll"),),
                    limitation="This excludes unobserved rent and other expense categories.",
                    follow_up="Ask “Am I in financial trouble?” for the bounded health view.",
                )
            return self._unavailable(
                question,
                context,
                "Complete employee salaries are unavailable, so payroll cannot be calculated.",
            )
        if "what can sim pilot" in normalized or "currently control" in normalized:
            return self._capability_answer(question, context)
        if "how many teams" in normalized:
            state = context.state
            if state is None or not state.teams_complete:
                return self._unavailable(
                    question, context, "Complete team coverage is unavailable."
                )
            return QuestionResponse(
                question=question,
                status=GuidanceStatus.ANSWERED,
                answer=(
                    f"You have {len(state.teams)} observed team"
                    f"{'s' if len(state.teams) != 1 else ''}."
                ),
                evidence=(_state_evidence(state, "teams", str(len(state.teams))),),
                follow_up="Ask “What are my teams?” for their names and staffing.",
            )
        if "what are my teams" in normalized or "list my teams" in normalized:
            state = context.state
            if state is None or not state.teams_complete:
                return self._unavailable(
                    question, context, "Complete team coverage is unavailable."
                )
            description = (
                ", ".join(
                    f"{team.name} ({team.employee_count} employee"
                    f"{'s' if team.employee_count != 1 else ''})"
                    for team in state.teams
                )
                or "none"
            )
            return QuestionResponse(
                question=question,
                status=GuidanceStatus.ANSWERED,
                answer=f"Observed teams: {description}.",
                evidence=(_state_evidence(state, "teams", description),),
                follow_up="Ask “Who works for each team?” for observed membership.",
            )
        if "how many employees" in normalized:
            state = context.state
            if state is None or not state.employees_complete:
                return self._unavailable(
                    question, context, "Complete employee coverage is unavailable."
                )
            return QuestionResponse(
                question=question,
                status=GuidanceStatus.ANSWERED,
                answer=(
                    f"You have {len(state.employees)} observed employee"
                    f"{'s' if len(state.employees) != 1 else ''}."
                ),
                evidence=(_state_evidence(state, "employees", str(len(state.employees))),),
                follow_up="Ask “Who works for each team?” for observed membership.",
            )
        if "who works for each team" in normalized or "team membership" in normalized:
            return self._membership_answer(question, context)
        if "how much cash" in normalized or "cash do i have" in normalized:
            state = context.state
            if state is None or state.cash is None:
                return self._unavailable(question, context, "Observed company cash is unavailable.")
            return QuestionResponse(
                question=question,
                status=GuidanceStatus.ANSWERED,
                answer=f"Observed company cash is {_money(state.cash)}.",
                evidence=(_state_evidence(state, "finances.cash", _money(state.cash)),),
                limitation="Cash is not a complete runway or affordability forecast.",
                follow_up="Ask “Am I in financial trouble?” for the known limits.",
            )
        if "is the game paused" in normalized or normalized == "am i paused":
            state = context.state
            if state is None:
                return self._unavailable(question, context, "Live game state is unavailable.")
            value = "paused" if state.paused else "running"
            return QuestionResponse(
                question=question,
                status=GuidanceStatus.ANSWERED,
                answer=f"The observed simulation is {value}.",
                evidence=(_state_evidence(state, "game_state", value),),
                follow_up=(
                    f"Use `/operate {'resume' if state.paused else 'pause'} the game` to change it."
                ),
            )
        if "support alpha" in normalized and ("already" in normalized or "present" in normalized):
            return self._team_exists_answer(question, context, "Support Alpha")
        if "financial trouble" in normalized or "afford another employee" in normalized:
            return self._financial_health_answer(question, context)
        return QuestionResponse(
            question=question,
            status=GuidanceStatus.UNSUPPORTED,
            answer=(
                "I cannot answer that question from the current verified knowledge and "
                "observations."
            ),
            evidence=(
                EvidenceReference(
                    evidence_id="unavailable:question_catalog",
                    kind=EvidenceKind.UNAVAILABLE,
                    summary=(
                        "The requested concept is outside the current Software Inc. "
                        "question catalog."
                    ),
                    source="software-inc-guidance-v1",
                ),
            ),
            limitation="Model recall is not used as game evidence.",
            follow_up="Try `/help`, `/crash_course`, or `/capabilities`.",
        )

    def status(self, context: SoftwareIncGuidanceContext) -> QuestionResponse:
        state = context.state
        if state is None:
            return self._unavailable(
                "status",
                context,
                "Current-save status is unavailable; generic guidance still works.",
            )
        company = state.company_name or "the observed company"
        team_text = str(len(state.teams)) if state.teams_complete else "unknown"
        employee_text = str(len(state.employees)) if state.employees_complete else "unknown"
        cash_text = _money(state.cash) if state.cash is not None else "unavailable"
        return QuestionResponse(
            question="status",
            status=GuidanceStatus.ANSWERED,
            answer=(
                f"{company}: {'paused' if state.paused else 'running'}; cash {cash_text}; "
                f"teams {team_text}; employees {employee_text}."
            ),
            evidence=(
                _state_evidence(state, "game_state/company/teams/employees", state.snapshot_id),
            ),
            limitation=(
                "Finances are partial; this is an observed status, not a complete health forecast."
            ),
            follow_up="Use `/recommend` for one evidence-grounded next objective.",
        )

    def crash_course(
        self,
        topic: str,
        context: SoftwareIncGuidanceContext,
        *,
        testing: bool = False,
    ) -> CrashCourseResponse:
        normalized = topic.strip().casefold().replace("-", "_") or "company"
        if testing or normalized == "testing":
            return self._testing_course(context)
        if normalized in {"default", "basics"}:
            normalized = "company"
        if normalized == "employees":
            normalized = "hiring"
        knowledge_version = _knowledge_version(context)
        claims = self._knowledge.claims_for(
            normalized,
            game_version=knowledge_version,
            steam_build_id=context.discovery.steam_build_id,
        )
        sections = [claim.claim for claim in claims]
        limitations: list[str] = []
        if not sections:
            limitations.append(
                f"No knowledge claims are verified for {knowledge_version} and the detected build."
            )
            if normalized not in {"company", "capabilities"}:
                sections.append(
                    "No verified Software Inc. crash-course content is available for "
                    f"{normalized!r}."
                )
        if normalized == "company":
            sections.extend(self._company_course_sections(context))
        elif normalized == "teams":
            sections.append(
                "Try: ask “What are my teams?”, then use `/operate open manage teams` "
                "only if the capability view says it is live and compatible."
            )
        elif normalized == "hiring":
            sections.append(
                "Phase 4 hiring remains blocked in the Guided Operator until its live gate passes. "
                "Questions and explanations remain safe and read-only."
            )
        elif normalized in {"office", "schedules", "roles", "servers"}:
            if context.snapshot is not None and context.state is not None:
                team = self._single_team_name(context)
                if team is not None:
                    try:
                        readiness = project_team_readiness(context.snapshot, team)
                        sections.append(
                            f"Current {team} readiness: capacity "
                            f"{readiness.current_capacity}/{readiness.required_capacity}; "
                            f"hours {readiness.work_start}-{readiness.work_end}; "
                            f"servers observed {len(readiness.servers)}."
                        )
                    except Exception as error:
                        limitations.append(f"Current-save office projection unavailable: {error}.")
            sections.append(
                "Try: `software-inc office readiness <exact-team>` before delegating a change. "
                "Purchases remain blocked without exact visible item, quantity, price, reserve, "
                "and separate recurring-cost authority."
            )
        elif normalized == "contracts":
            sections.append(
                "Try: `software-inc contracts browse`, then `software-inc contracts recommend "
                "--team <exact-team> --minimum-reward <amount>`. Acceptance, promotion, "
                "deadline risk, review spending, and release remain separate exact approvals. "
                "The same bounded actions are available through `software-inc contracts do`."
            )
        elif normalized in {"training", "education"}:
            sections.append(
                "Try: `software-inc training recommend --team Core "
                "--minimum-cash-reserve <amount>`, then inspect the exact employee, "
                "Designer/System level, direct charge, continuing payroll, team capacity, and "
                "cash after cost. Starting education requires a separate exact approval; "
                "`software-inc training advance` runs only one bounded interval and always "
                "returns the game to pause."
            )
        elif normalized == "capabilities":
            sections.append(_capability_summary(context))
        return CrashCourseResponse(
            topic=normalized,
            title=f"Software Inc. crash course — {normalized.replace('_', ' ')}",
            sections=tuple(sections),
            personalized=context.state is not None,
            evidence=tuple(_claim_evidence(claim) for claim in claims),
            limitations=(
                tuple(limitations)
                if context.state is not None
                else tuple(
                    [
                        *limitations,
                        f"Current-save personalization unavailable: {context.snapshot_error}.",
                    ]
                )
            ),
        )

    def recommend(self, context: SoftwareIncGuidanceContext) -> RecommendationResponse:
        now = datetime.now(UTC)
        state = context.state
        if state is None:
            return RecommendationResponse(
                status=GuidanceStatus.INSUFFICIENT_DATA,
                rule_id="state_unavailable",
                capability_fingerprint=context.capabilities.capability_fingerprint,
                created_at=now,
                expires_at=now + _RECOMMENDATION_LIFETIME,
                explanation=(
                    "Insufficient data: a compatible current-save observation is required before "
                    "recommending a gameplay objective."
                ),
            )
        if not state.paused:
            return self._recommendation(
                context,
                rule_id="pause_before_management",
                title="Pause before management review",
                objective="pause the game",
                action="pause",
                benefit=(
                    "Prevents uncontrolled progression while you inspect and configure the company."
                ),
                risk="Pausing advances no game time and is reversible.",
                evidence=(_state_evidence(state, "game_state", "running"),),
                unknowns=(),
            )
        if not state.teams_complete or not state.employees_complete:
            return RecommendationResponse(
                status=GuidanceStatus.INSUFFICIENT_DATA,
                rule_id="staffing_coverage_incomplete",
                game_session_id=state.game_session_id,
                save_identity=state.save_identity,
                source_snapshot_id=state.snapshot_id,
                capability_fingerprint=context.capabilities.capability_fingerprint,
                created_at=now,
                expires_at=now + _RECOMMENDATION_LIFETIME,
                explanation=(
                    "Insufficient data: complete teams and employees are required for a staffing "
                    "recommendation."
                ),
            )
        if context.snapshot is not None:
            for team in state.teams:
                try:
                    readiness = project_team_readiness(context.snapshot, team.name)
                except Exception:
                    continue
                if readiness.missing_workstations > 0:
                    reuse = bool(readiness.cheaper_existing_capacity)
                    return self._recommendation(
                        context,
                        rule_id="repair_workspace_shortage",
                        title=f"Resolve {team.name}'s observed workspace shortage",
                        objective=(
                            f"assign existing room {readiness.cheaper_existing_capacity[0]} to "
                            f"{team.name}"
                            if reuse
                            else f"review office capacity for {team.name}"
                        ),
                        action="assign_existing_room" if reuse else "review_office_capacity",
                        benefit=readiness.expected_benefit,
                        risk=(
                            "Existing unassigned capacity costs $0 in the current projection; "
                            "room suitability still needs visible confirmation."
                            if reuse
                            else "No purchase is recommended because exact catalog price and "
                            "placement are not observed."
                        ),
                        evidence=(
                            _state_evidence(
                                state,
                                f"offices.{team.team_id}.capacity",
                                f"{readiness.current_capacity}/{readiness.required_capacity}",
                            ),
                        ),
                        unknowns=readiness.material_unknowns,
                    )
        empty = next((team for team in state.teams if team.employee_count == 0), None)
        if empty is not None:
            return self._recommendation(
                context,
                rule_id="review_empty_team",
                title=f"Review staffing for {empty.name}",
                objective="open manage teams",
                action="open_manage_teams",
                benefit=f"Lets you inspect why {empty.name} currently has no observed employees.",
                risk="This opens a read-only management view; hiring remains unavailable here.",
                evidence=(_state_evidence(state, f"teams.{empty.team_id}.employee_count", "0"),),
                unknowns=(
                    "An empty team alone does not prove that another employee should be hired.",
                    "A monthly salary ceiling is required before any later hiring plan.",
                ),
            )
        return self._recommendation(
            context,
            rule_id="review_team_structure",
            title="Review the current team structure",
            objective="open manage teams",
            action="open_manage_teams",
            benefit="Shows the current team structure before you choose a staffing objective.",
            risk="This only opens Manage Teams and does not change employees or finances.",
            evidence=(
                _state_evidence(state, "teams", str(len(state.teams))),
                _state_evidence(state, "employees", str(len(state.employees))),
            ),
            unknowns=(
                "Current observations do not establish that another team or hire is needed.",
            ),
        )

    def explain(
        self,
        recommendation: RecommendationResponse | None,
        context: SoftwareIncGuidanceContext,
    ) -> QuestionResponse:
        now = datetime.now(UTC)
        if recommendation is None or recommendation.recommended is None:
            return QuestionResponse(
                question="why",
                status=GuidanceStatus.INSUFFICIENT_DATA,
                answer="There is no current recommendation to explain.",
                follow_up="Run `/recommend` first.",
            )
        if not recommendation.is_current(now):
            return QuestionResponse(
                question="why",
                status=GuidanceStatus.BLOCKED,
                answer=(
                    "The current recommendation expired and cannot be explained as current advice."
                ),
                follow_up="Run `/recommend` again.",
            )
        if recommendation.capability_fingerprint != context.capabilities.capability_fingerprint:
            return QuestionResponse(
                question="why",
                status=GuidanceStatus.BLOCKED,
                answer="The capability boundary changed after that recommendation.",
                follow_up="Run `/recommend` again.",
            )
        state = context.state
        if state is None or (
            recommendation.game_session_id != state.game_session_id
            or recommendation.save_identity != state.save_identity
        ):
            return QuestionResponse(
                question="why",
                status=GuidanceStatus.BLOCKED,
                answer="The save or game session changed after that recommendation.",
                follow_up="Run `/recommend` again.",
            )
        item = recommendation.recommended
        return QuestionResponse(
            question="why",
            status=GuidanceStatus.ANSWERED,
            answer=recommendation.explanation,
            evidence=item.evidence,
            limitation=" ".join(item.material_unknowns) if item.material_unknowns else None,
            follow_up=(
                "Use `/operate use your recommended plan` to delegate this exact objective."
                if item.executable
                else "This recommendation is not currently executable."
            ),
        )

    def _knowledge_answer(
        self,
        question: str,
        claim_id: str,
        context: SoftwareIncGuidanceContext,
        *,
        follow_up: str,
    ) -> QuestionResponse:
        claim = self._applicable_claim(claim_id, context)
        if claim is None:
            return self._unavailable(
                question,
                context,
                "The requested knowledge is not verified for the detected game identity.",
            )
        return QuestionResponse(
            question=question,
            status=GuidanceStatus.ANSWERED,
            answer=claim.claim,
            evidence=(_claim_evidence(claim),),
            limitation=" ".join(claim.limitations) if claim.limitations else None,
            follow_up=follow_up,
        )

    def _applicable_claim(
        self, claim_id: str, context: SoftwareIncGuidanceContext
    ) -> KnowledgeClaim | None:
        claim = self._knowledge.claim(claim_id)
        version = _knowledge_version(context)
        build = context.discovery.steam_build_id
        if version not in claim.supported_versions:
            return None
        if claim.supported_builds and build not in claim.supported_builds:
            return None
        return claim

    def _capability_answer(
        self, question: str, context: SoftwareIncGuidanceContext
    ) -> QuestionResponse:
        live = [
            action.action
            for action in context.capabilities.actions
            if action.direct_ui_action and action.live_verified
        ]
        pending = [
            action.action
            for action in context.capabilities.actions
            if action.direct_ui_action and action.offline_tested and not action.live_verified
        ]
        return QuestionResponse(
            question=question,
            status=GuidanceStatus.ANSWERED,
            answer=(
                f"Live-proven direct UI actions: {', '.join(live) or 'none'}. "
                f"Offline-only staffing actions: {', '.join(pending) or 'none'}. "
                "The semantic bridge has no gameplay actions, and the generic Software Inc. "
                "task runtime is unavailable."
            ),
            evidence=(
                EvidenceReference(
                    evidence_id=f"capability:{context.capabilities.capability_fingerprint[:20]}",
                    kind=EvidenceKind.VERIFIED_REPOSITORY_KNOWLEDGE,
                    summary="Unified capability view",
                    source="SoftwareIncGuidedCapabilityView",
                ),
            ),
            limitation="Every delegated action still performs current live preflight.",
            follow_up="Use `/capabilities` for the complete evidence stages.",
        )

    def _membership_answer(
        self, question: str, context: SoftwareIncGuidanceContext
    ) -> QuestionResponse:
        state = context.state
        if state is None or not state.teams_complete or not state.employees_complete:
            return self._unavailable(
                question, context, "Complete team and employee coverage is required."
            )
        groups: list[str] = []
        for team in state.teams:
            names = [employee.name for employee in state.employees if employee.team == team.name]
            groups.append(f"{team.name}: {', '.join(names) if names else 'no observed employees'}")
        return QuestionResponse(
            question=question,
            status=GuidanceStatus.ANSWERED,
            answer="; ".join(groups) + ".",
            evidence=(_state_evidence(state, "employees.team", str(len(state.employees))),),
            limitation="Membership does not prove project suitability.",
            follow_up="Use `/recommend` for one bounded next objective.",
        )

    def _team_exists_answer(
        self, question: str, context: SoftwareIncGuidanceContext, name: str
    ) -> QuestionResponse:
        state = context.state
        if state is None or not state.teams_complete:
            return self._unavailable(question, context, "Complete team coverage is unavailable.")
        matches = [team for team in state.teams if team.name.casefold() == name.casefold()]
        return QuestionResponse(
            question=question,
            status=GuidanceStatus.ANSWERED,
            answer=(
                f"Yes. {matches[0].name} is an observed team with "
                f"{matches[0].employee_count} employees."
                if len(matches) == 1
                else f"No observed team is named {name}."
            ),
            evidence=(_state_evidence(state, "teams.name", name),),
            follow_up="Use `/status` or ask “What are my teams?” for current staffing.",
        )

    def _financial_health_answer(
        self, question: str, context: SoftwareIncGuidanceContext
    ) -> QuestionResponse:
        state = context.state
        if state is None or state.cash is None:
            return self._unavailable(question, context, "Observed company cash is unavailable.")
        payroll = (
            _money(state.recurring_payroll)
            if state.recurring_payroll is not None
            else "unavailable"
        )
        return QuestionResponse(
            question=question,
            status=GuidanceStatus.INSUFFICIENT_DATA,
            answer=(
                f"Insufficient data for a complete financial-health verdict. Observed cash is "
                f"{_money(state.cash)} and recurring employee payroll is {payroll} per month."
            ),
            evidence=(
                _state_evidence(state, "finances.cash", _money(state.cash)),
                _state_evidence(state, "employees.salary", payroll),
            ),
            limitation=(
                "Rent, scheduled payments, projected income, commitments, and complete runway "
                "are not observed."
            ),
            follow_up="Set an explicit reserve and salary ceiling before delegating a hire.",
        )

    def _single_team_name(self, context: SoftwareIncGuidanceContext) -> str | None:
        state = context.state
        if state is None or not state.teams_complete or len(state.teams) != 1:
            return None
        return state.teams[0].name

    def _team_readiness_answer(
        self,
        question: str,
        context: SoftwareIncGuidanceContext,
        team_name: str,
        *,
        mode: str,
    ) -> QuestionResponse:
        if context.snapshot is None:
            return self._unavailable(question, context, "Live office state is unavailable.")
        try:
            readiness = project_team_readiness(context.snapshot, team_name)
        except Exception as error:
            return self._unavailable(question, context, str(error))
        if mode == "hours":
            answer = (
                f"{readiness.team_name} works from {readiness.work_start} to {readiness.work_end}."
            )
            field = "teams.work_start/work_end"
        elif mode == "capacity":
            enough = readiness.missing_workstations == 0
            answer = (
                f"{'Yes' if enough else 'No'}. {readiness.team_name} has "
                f"{readiness.current_capacity} observed valid assignable workstation(s) for "
                f"{readiness.required_capacity} employee(s)."
            )
            field = "offices.valid_workstations"
        else:
            answer = (
                f"{readiness.team_name} has no observed workstation shortage."
                if readiness.exact_missing_resource is None
                else f"{readiness.team_name} is missing {readiness.exact_missing_resource}."
            )
            field = "offices.assignable_workstations"
        if readiness.cheaper_existing_capacity:
            answer += (
                " Unassigned existing capacity is visible in room(s) "
                + ", ".join(readiness.cheaper_existing_capacity)
                + "; prefer assignment before purchase."
            )
        return QuestionResponse(
            question=question,
            status=GuidanceStatus.ANSWERED,
            answer=answer,
            evidence=(
                EvidenceReference(
                    evidence_id=(
                        f"{context.state.snapshot_id if context.state else 'snapshot'}:{field}"
                    ),
                    kind=EvidenceKind.LIVE_OBSERVATION,
                    summary=f"Observed office readiness for {readiness.team_name}",
                    source=(
                        context.state.snapshot_id
                        if context.state is not None
                        else f"bridge-sequence:{context.snapshot.bridge_sequence}"
                    ),
                    observed_value=f"{readiness.current_capacity}/{readiness.required_capacity}",
                ),
            ),
            limitation=" ".join(readiness.material_unknowns),
            follow_up=f"Run `software-inc office readiness {readiness.team_name}` for full detail.",
        )

    def _server_requirement_answer(
        self, question: str, context: SoftwareIncGuidanceContext
    ) -> QuestionResponse:
        claim = self._applicable_claim("software-inc.servers.current-boundary", context)
        if claim is None:
            return self._unavailable(
                question, context, "Server requirements are not verified for this game identity."
            )
        observed = 0
        if context.snapshot is not None:
            surfaces = [
                surface
                for surface in context.snapshot.surfaces
                if surface.coverage.surface == "infrastructure"
            ]
            if len(surfaces) == 1:
                observed = sum(
                    entity.entity_type == "server_group" for entity in surfaces[0].entities
                )
        return QuestionResponse(
            question=question,
            status=GuidanceStatus.ANSWERED,
            answer=(
                "No universal team source-control-server requirement is verified for 1.8.41. "
                f"The current save exposes {observed} server group(s); Sim Pilot will only "
                "recommend one when a selected workflow proves it is required."
            ),
            evidence=(_claim_evidence(claim),),
            limitation="The Alpha 10 guide's SCM recommendation is historical, not authority.",
            follow_up="Use `/crash_course servers` for the evidence boundary.",
        )

    def _unavailable(
        self, question: str, context: SoftwareIncGuidanceContext, message: str
    ) -> QuestionResponse:
        detail = context.snapshot_error or "required fields are unavailable"
        return QuestionResponse(
            question=question,
            status=GuidanceStatus.INSUFFICIENT_DATA,
            answer=f"Insufficient data: {message}",
            evidence=(
                EvidenceReference(
                    evidence_id="unavailable:live_state",
                    kind=EvidenceKind.UNAVAILABLE,
                    summary=detail,
                    source="SoftwareIncGuidanceContext",
                ),
            ),
            limitation=detail,
            follow_up="Run `software-inc crash-course --testing` to inspect the live boundary.",
        )

    def _company_course_sections(self, context: SoftwareIncGuidanceContext) -> tuple[str, ...]:
        state = context.state
        if state is None:
            return (
                "Current-save personalization is unavailable; the course is using checked-in, "
                "versioned knowledge only.",
                "Start with: ask “What do teams do?”, run `/capabilities`, then `/recommend` "
                "after a compatible company is loaded.",
            )
        return (
            f"Current company: {state.company_name or 'name unavailable'}; "
            f"{'paused' if state.paused else 'running'}; "
            f"{len(state.teams) if state.teams_complete else 'unknown'} teams; "
            f"{len(state.employees) if state.employees_complete else 'unknown'} employees.",
            _capability_summary(context),
            "Start with `/status`, `/recommend`, and `/why`. Mutation occurs only after "
            "`/operate`.",
        )

    def _testing_course(self, context: SoftwareIncGuidanceContext) -> CrashCourseResponse:
        report = context.bridge_report
        discovery = context.discovery
        bridge_identity = (
            "unavailable"
            if report is None
            else (
                f"installed={report.installed}; enabled={report.enabled}; loaded={report.loaded}; "
                f"installed_sha256={report.installed_sha256 or 'unavailable'}; "
                f"artifact_sha256={report.artifact_sha256 or 'unavailable'}; "
                f"match={report.artifact_matches_installed}"
            )
        )
        state = context.state
        state_text = (
            f"session={state.game_session_id}; save={state.save_identity or 'unavailable'}; "
            f"snapshot={state.snapshot_id}; adapter={state.adapter_version}"
            if state is not None
            else f"unavailable: {context.snapshot_error}"
        )
        actions = ", ".join(
            f"{action.action}={action.evidence_stage.value}"
            for action in context.capabilities.actions
        )
        return CrashCourseResponse(
            topic="testing",
            title="Software Inc. guided-operator testing course",
            sections=(
                f"Detected version={discovery.product_version or 'unknown'}; "
                f"Steam build={discovery.steam_build_id or 'unknown'}; "
                f"running={discovery.running}.",
                f"Bridge: {bridge_identity}.",
                f"Current state: {state_text}.",
                "Semantic gameplay actions: none.",
                f"UI evidence: {actions}.",
                "Generic persisted-task runtime: unavailable.",
                "Suggested read-only prompts: What do teams do?; How many employees do I have?; "
                "Am I in financial trouble?; /recommend; /why.",
                "Expected operator proof: `/operate open manage teams`; Phase 4 staffing must be "
                "rejected until separately live-promoted.",
            ),
            personalized=state is not None,
            limitations=context.capabilities.limitations,
        )

    def _recommendation(
        self,
        context: SoftwareIncGuidanceContext,
        *,
        rule_id: str,
        title: str,
        objective: str,
        action: str,
        benefit: str,
        risk: str,
        evidence: tuple[EvidenceReference, ...],
        unknowns: tuple[str, ...],
    ) -> RecommendationResponse:
        now = datetime.now(UTC)
        state = context.state
        assert state is not None
        capability = action_capability(context.capabilities, action)
        executable = bool(
            capability
            and capability.direct_ui_action
            and capability.live_verified
            and capability.compatible
        )
        identifier = hashlib.sha256(
            f"{rule_id}|{state.snapshot_id}|{action}|"
            f"{context.capabilities.capability_fingerprint}".encode()
        ).hexdigest()[:20]
        recommendation = Recommendation(
            recommendation_id=f"recommendation:{identifier}",
            title=title,
            objective=objective,
            expected_benefit=benefit,
            risk=risk,
            prerequisites=("Same compatible save and session", "Fresh UI preflight"),
            approval_required=False,
            executable=executable,
            action=action if executable else None,
            capability_stage=(
                capability.evidence_stage
                if capability is not None
                else CapabilityEvidenceStage.UNAVAILABLE
            ),
            evidence=evidence,
            material_unknowns=unknowns,
        )
        why = (
            f"Recommended: {title}. Rule {rule_id} matched the current observed state. "
            f"Expected benefit: {benefit} Risk: {risk}"
        )
        return RecommendationResponse(
            status=GuidanceStatus.ANSWERED,
            rule_id=rule_id,
            recommended=recommendation,
            alternatives=(),
            game_session_id=state.game_session_id,
            save_identity=state.save_identity,
            source_snapshot_id=state.snapshot_id,
            capability_fingerprint=context.capabilities.capability_fingerprint,
            created_at=now,
            expires_at=now + _RECOMMENDATION_LIFETIME,
            explanation=why,
        )


def _claim_evidence(claim: KnowledgeClaim) -> EvidenceReference:
    return EvidenceReference(
        evidence_id=f"knowledge:{claim.claim_id}",
        kind=EvidenceKind.VERIFIED_REPOSITORY_KNOWLEDGE,
        summary=claim.claim,
        source=claim.provenance_locator,
        observed_value=claim.verification_stage.value,
        limitations=claim.limitations,
    )


def _knowledge_version(context: SoftwareIncGuidanceContext) -> str:
    if context.state is not None:
        return context.state.game_version
    if context.discovery.product_version is not None:
        return context.discovery.product_version
    if context.discovery.steam_build_id == "23094975":
        return "1.8.41"
    return "unknown"


def _state_evidence(state: SoftwareIncStateView, field: str, value: str) -> EvidenceReference:
    return EvidenceReference(
        evidence_id=f"{state.snapshot_id}:{field}",
        kind=EvidenceKind.LIVE_OBSERVATION,
        summary=f"Observed {field}",
        source=state.snapshot_id,
        observed_value=value,
    )


def _capability_summary(context: SoftwareIncGuidanceContext) -> str:
    live = [action.action for action in context.capabilities.actions if action.live_verified]
    pending = [
        action.action
        for action in context.capabilities.actions
        if action.offline_tested and not action.live_verified
    ]
    return (
        f"Live direct UI actions: {', '.join(live) or 'none'}. "
        f"Offline-only actions: {', '.join(pending) or 'none'}. "
        "Semantic actions and generic task-runtime actions: none."
    )


def _money(value: Decimal) -> str:
    return f"${value:,.2f}"


__all__ = ["SoftwareIncReadGuidanceService"]
