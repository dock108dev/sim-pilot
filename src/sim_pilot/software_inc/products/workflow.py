"""Durable state transitions and exact approvals for Atlas."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid4, uuid5

from sim_pilot.game_bridge import GameSnapshot
from sim_pilot.software_inc.errors import SoftwareIncUIValidationError

from .models import (
    ProductApproval,
    ProductCommitment,
    ProductRecommendation,
    ProductStage,
    ProductWorkflow,
    ProductWorkflowStatus,
)
from .projection import observed_stage, product_work


def create_workflow(
    snapshot: GameSnapshot,
    recommendation: ProductRecommendation,
    *,
    now: datetime | None = None,
) -> ProductWorkflow:
    if not recommendation.recommended:
        raise SoftwareIncUIValidationError("a rejected Atlas recommendation cannot be committed")
    current = now or datetime.now(UTC)
    configuration = recommendation.configuration
    material = {
        "recommendation": recommendation.capability_fingerprint,
        "session": snapshot.game_session_id,
        "save": recommendation.save_identity,
    }
    fingerprint = hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    workflow_id = uuid5(NAMESPACE_URL, f"sim-pilot:software-inc:product:{fingerprint}")
    workflow = ProductWorkflow(
        workflow_id=workflow_id,
        game_session_id=snapshot.game_session_id,
        save_identity=recommendation.save_identity,
        product_name=configuration.name,
        product_type=configuration.product_type,
        category=configuration.category,
        features=configuration.features,
        operating_systems=configuration.operating_systems,
        team_name=recommendation.team.team_name,
        price=configuration.price,
        minimum_cash_reserve=recommendation.runway.minimum_cash_reserve,
        initial_cash=recommendation.runway.observed_cash,
        projected_cash_after=recommendation.runway.projected_cash_after,
        stage=ProductStage.CONFIGURATION,
        status=ProductWorkflowStatus.WAITING_FOR_APPROVAL,
        held=False,
        iteration=0,
        progress=Decimal("0"),
        configuration_fingerprint=fingerprint,
        last_bridge_sequence=snapshot.bridge_sequence,
        created_at=current,
        updated_at=current,
    )
    return workflow.model_copy(update={"pending_approval": approval_for(workflow)})


def approval_for(
    workflow: ProductWorkflow,
    commitment: ProductCommitment = ProductCommitment.CREATE,
    *,
    expected_stage: ProductStage | None = None,
    one_time_cost: Decimal = Decimal("0"),
    observed_cash: Decimal | None = None,
    projected_cash_after: Decimal | None = None,
    now: datetime | None = None,
) -> ProductApproval:
    target = (
        expected_stage
        or {
            ProductStage.CONFIGURATION: ProductStage.DESIGN,
            ProductStage.DESIGN: ProductStage.ALPHA,
            ProductStage.ALPHA: ProductStage.BETA,
            ProductStage.BETA: ProductStage.BETA,
        }[workflow.stage]
    )
    current_cash = workflow.initial_cash if observed_cash is None else observed_cash
    projected_cash = (
        workflow.projected_cash_after if projected_cash_after is None else projected_cash_after
    )
    summaries = {
        ProductCommitment.CREATE: (
            f"Create {workflow.product_name!r} as {workflow.product_type}/{workflow.category}; "
            f"features {', '.join(workflow.features)}; operating systems "
            f"{', '.join(workflow.operating_systems)}; design and development team "
            f"{workflow.team_name}; price ${workflow.price:,.2f}; projected conservative cash "
            f"${workflow.projected_cash_after:,.2f}, reserve "
            f"${workflow.minimum_cash_reserve:,.2f}."
        ),
        ProductCommitment.REVIEW: (
            f"Start the exact visible review for {workflow.product_name!r}; observed one-time "
            f"cost ${one_time_cost:,.2f}; current cash ${current_cash:,.2f}; projected "
            f"conservative cash ${projected_cash:,.2f}; reserve "
            f"${workflow.minimum_cash_reserve:,.2f}."
        ),
        ProductCommitment.ITERATE: (
            f"Iterate {workflow.product_name!r} after the observed review; preserve the exact "
            f"approved configuration; projected conservative cash ${projected_cash:,.2f} "
            f"remains above the ${workflow.minimum_cash_reserve:,.2f} reserve; leave the game "
            "paused."
        ),
        ProductCommitment.PROMOTE: (
            f"Promote {workflow.product_name!r} from {workflow.stage.value} to {target.value}; "
            f"current cash ${current_cash:,.2f}; projected conservative cash "
            f"${projected_cash:,.2f} remains above "
            f"the ${workflow.minimum_cash_reserve:,.2f} reserve."
        ),
    }
    current = now or datetime.now(UTC)
    return ProductApproval(
        approval_id=uuid4(),
        workflow_id=workflow.workflow_id,
        commitment=commitment,
        action_summary=summaries[commitment],
        product_name=workflow.product_name,
        stage_before=workflow.stage,
        expected_stage_after=target,
        configuration_fingerprint=workflow.configuration_fingerprint,
        observed_cash=current_cash,
        projected_cash_after=projected_cash,
        minimum_cash_reserve=workflow.minimum_cash_reserve,
        one_time_cost=one_time_cost,
        created_at=current,
    )


def resolve_approval(
    workflow: ProductWorkflow, *, approved: bool, now: datetime | None = None
) -> ProductWorkflow:
    pending = workflow.pending_approval
    if pending is None or pending.approved is not None:
        raise SoftwareIncUIValidationError("Atlas workflow has no pending approval")
    current = now or datetime.now(UTC)
    resolved = pending.model_copy(update={"approved": approved, "resolved_at": current})
    return workflow.model_copy(
        update={
            "pending_approval": resolved,
            "status": ProductWorkflowStatus.ACTIVE if approved else ProductWorkflowStatus.BLOCKED,
            "updated_at": current,
        }
    )


def synchronize_workflow(
    workflow: ProductWorkflow,
    snapshot: GameSnapshot,
    *,
    now: datetime | None = None,
) -> ProductWorkflow:
    save_identity = json.dumps(snapshot.save_identity.model_dump(mode="json"), sort_keys=True)
    if (
        workflow.game_session_id != snapshot.game_session_id
        or workflow.save_identity != save_identity
    ):
        raise SoftwareIncUIValidationError("Atlas workflow save or session identity is stale")
    if snapshot.bridge_sequence <= workflow.last_bridge_sequence:
        raise SoftwareIncUIValidationError("Atlas workflow requires a fresh bridge sequence")
    work = product_work(snapshot, workflow.product_name)
    current = now or datetime.now(UTC)
    if work is None:
        return workflow.model_copy(
            update={"last_bridge_sequence": snapshot.bridge_sequence, "updated_at": current}
        )
    stage = observed_stage(work)
    paused = work.values.get("paused")
    if not isinstance(paused, bool):
        raise SoftwareIncUIValidationError("Atlas project pause state is not observed")
    progress_value = work.values.get("progress")
    iteration_value = work.values.get("iteration", workflow.iteration)
    if isinstance(progress_value, bool) or not isinstance(progress_value, (int, float)):
        raise SoftwareIncUIValidationError("Atlas project progress is not observed")
    if isinstance(iteration_value, bool) or not isinstance(iteration_value, int):
        raise SoftwareIncUIValidationError("Atlas project iteration is not observed")
    status = (
        ProductWorkflowStatus.BETA_REACHED
        if stage is ProductStage.BETA
        else (ProductWorkflowStatus.HELD if paused else ProductWorkflowStatus.ACTIVE)
    )
    review_accuracy = work.values.get("review_accuracy")
    review_score = work.values.get("review_score")
    return workflow.model_copy(
        update={
            "stage": stage,
            "status": status,
            "work_item_id": work.entity_id,
            "held": paused,
            "iteration": iteration_value,
            "progress": Decimal(str(progress_value)),
            "review_accuracy": (
                Decimal(str(review_accuracy))
                if isinstance(review_accuracy, (int, float))
                and not isinstance(review_accuracy, bool)
                else None
            ),
            "review_score": (
                Decimal(str(review_score))
                if isinstance(review_score, (int, float)) and not isinstance(review_score, bool)
                else None
            ),
            "last_bridge_sequence": snapshot.bridge_sequence,
            "updated_at": current,
        }
    )


__all__ = ["approval_for", "create_workflow", "resolve_approval", "synchronize_workflow"]
