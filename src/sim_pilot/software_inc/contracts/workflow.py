"""State transitions and separately scoped approvals for one first contract."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid4, uuid5

from sim_pilot.game_bridge import GameSnapshot
from sim_pilot.software_inc.errors import SoftwareIncUIValidationError

from .models import (
    ContractApproval,
    ContractCandidate,
    ContractCommitment,
    ContractStage,
    ContractWorkflow,
    ContractWorkflowStatus,
)
from .projection import active_contract_work


def create_workflow(
    snapshot: GameSnapshot,
    candidate: ContractCandidate,
    *,
    now: datetime | None = None,
) -> ContractWorkflow:
    if not candidate.eligible:
        raise SoftwareIncUIValidationError("an ineligible contract cannot create a workflow")
    current = now or datetime.now(UTC)
    save_identity = json.dumps(snapshot.save_identity.model_dump(mode="json"), sort_keys=True)
    material = {
        "contract_id": candidate.contract.contract_id,
        "game_session_id": snapshot.game_session_id,
        "save_identity": save_identity,
        "team": candidate.team.team_name,
        "minimum_reward": str(candidate.minimum_reward),
        "minimum_cash_reserve": str(candidate.minimum_cash_reserve),
    }
    fingerprint = hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    workflow_id = uuid5(NAMESPACE_URL, f"sim-pilot:software-inc:contract:{fingerprint}")
    workflow = ContractWorkflow(
        workflow_id=workflow_id,
        game_session_id=snapshot.game_session_id,
        save_identity=save_identity,
        contract_id=candidate.contract.contract_id,
        contract_name=candidate.contract.name,
        client=candidate.contract.client,
        team_name=candidate.team.team_name,
        minimum_reward=candidate.minimum_reward,
        minimum_cash_reserve=candidate.minimum_cash_reserve,
        reward=candidate.contract.reward,
        maximum_penalty=candidate.contract.penalty,
        deadline=candidate.contract.deadline,
        status=ContractWorkflowStatus.WAITING_FOR_APPROVAL,
        observed_stage=ContractStage.AVAILABLE,
        plan_fingerprint=fingerprint,
        last_bridge_sequence=snapshot.bridge_sequence,
        created_at=current,
        updated_at=current,
    )
    approval = approval_for(workflow, ContractCommitment.ACCEPT, now=current)
    return workflow.model_copy(update={"pending_approval": approval})


def approval_for(
    workflow: ContractWorkflow,
    commitment: ContractCommitment,
    *,
    one_time_cost: Decimal = Decimal("0"),
    configuration: str | None = None,
    now: datetime | None = None,
) -> ContractApproval:
    current = now or datetime.now(UTC)
    summaries = {
        ContractCommitment.ACCEPT: (
            f"Accept {workflow.contract_name!r} from {workflow.client} for {workflow.team_name}; "
            f"reward ${workflow.reward:,.2f}, maximum observed penalty "
            f"${workflow.maximum_penalty:,.2f}, deadline {workflow.deadline}."
        ),
        ContractCommitment.DEADLINE_RISK: (
            f"Start or continue {workflow.contract_name!r} with deadline {workflow.deadline}; "
            f"reward ${workflow.reward:,.2f}, maximum observed penalty "
            f"${workflow.maximum_penalty:,.2f}; no other commitment is authorized."
        ),
        ContractCommitment.REVIEW: (
            f"Start the currently configured review for {workflow.contract_name!r}; "
            f"configuration {configuration}; the exact observed one-time cost is "
            f"${one_time_cost:,.2f}."
        ),
        ContractCommitment.PROMOTE: (
            f"Promote {workflow.contract_name!r} from {workflow.observed_stage.value}; "
            "this irreversible stage transition is the only authorized action."
        ),
        ContractCommitment.RELEASE: (
            f"Release {workflow.contract_name!r}; reward and reputation outcome remain "
            "subject to Software Inc.'s observed contract rules."
        ),
    }
    return ContractApproval(
        approval_id=uuid4(),
        workflow_id=workflow.workflow_id,
        commitment=commitment,
        action_summary=summaries[commitment],
        contract_id=workflow.contract_id,
        team_name=workflow.team_name,
        reward=workflow.reward,
        maximum_penalty=workflow.maximum_penalty,
        one_time_cost=one_time_cost,
        configuration=configuration,
        deadline=workflow.deadline,
        plan_fingerprint=workflow.plan_fingerprint,
        created_at=current,
    )


def resolve_approval(
    workflow: ContractWorkflow, *, approved: bool, now: datetime | None = None
) -> ContractWorkflow:
    approval = workflow.pending_approval
    if approval is None or approval.approved is not None:
        raise SoftwareIncUIValidationError("the workflow has no pending approval")
    current = now or datetime.now(UTC)
    resolved = approval.model_copy(update={"approved": approved, "resolved_at": current})
    return workflow.model_copy(
        update={
            "pending_approval": resolved,
            "status": (
                ContractWorkflowStatus.ACTIVE if approved else ContractWorkflowStatus.BLOCKED
            ),
            "updated_at": current,
        }
    )


def synchronize_workflow(
    workflow: ContractWorkflow, snapshot: GameSnapshot, *, now: datetime | None = None
) -> ContractWorkflow:
    save_identity = json.dumps(snapshot.save_identity.model_dump(mode="json"), sort_keys=True)
    if (
        workflow.game_session_id != snapshot.game_session_id
        or workflow.save_identity != save_identity
    ):
        raise SoftwareIncUIValidationError("contract workflow save or session identity is stale")
    if snapshot.bridge_sequence <= workflow.last_bridge_sequence:
        raise SoftwareIncUIValidationError("contract workflow requires a fresh bridge sequence")
    matches = [
        item
        for item in active_contract_work(snapshot)
        if item.contract_id == workflow.contract_id
        or (item.contract_name == workflow.contract_name and item.client == workflow.client)
    ]
    current = now or datetime.now(UTC)
    if not matches:
        return workflow.model_copy(
            update={"last_bridge_sequence": snapshot.bridge_sequence, "updated_at": current}
        )
    if len(matches) != 1:
        raise SoftwareIncUIValidationError("active contract work identity is ambiguous")
    item = matches[0]
    status = workflow.status
    completed_at = workflow.completed_at
    if item.stage in {ContractStage.COMPLETED, ContractStage.RELEASED} or item.done:
        status = ContractWorkflowStatus.COMPLETED
        completed_at = current
    deadline = item.deadline or workflow.deadline
    if item.contract_started is False:
        approval = workflow.pending_approval
        deadline = (
            approval.deadline
            if approval is not None
            and approval.commitment is ContractCommitment.ACCEPT
            and approval.deadline
            else workflow.deadline
        )
    return workflow.model_copy(
        update={
            "accepted_at": workflow.accepted_at or current,
            "completed_at": completed_at,
            "deadline": deadline,
            "last_bridge_sequence": snapshot.bridge_sequence,
            "observed_stage": item.stage,
            "status": status,
            "work_item_id": item.work_item_id,
            "updated_at": current,
        }
    )


__all__ = ["approval_for", "create_workflow", "resolve_approval", "synchronize_workflow"]
