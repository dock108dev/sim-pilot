"""Software Inc. Prompt 6A contract domain."""

from .intent import ContractIntent, ContractIntentAction, parse_contract_intent
from .operator import (
    accept_recommended_contract,
    advance_contract,
    browse_contracts,
    promote_contract,
    release_contract,
    review_contract,
)
from .policy import assess_contract, recommend_contracts
from .projection import active_contract_work, available_contracts, find_contract
from .store import ContractWorkflowStore
from .workflow import approval_for, create_workflow, resolve_approval, synchronize_workflow

__all__ = [
    "ContractWorkflowStore",
    "ContractIntent",
    "ContractIntentAction",
    "active_contract_work",
    "accept_recommended_contract",
    "advance_contract",
    "approval_for",
    "assess_contract",
    "available_contracts",
    "create_workflow",
    "browse_contracts",
    "find_contract",
    "parse_contract_intent",
    "recommend_contracts",
    "promote_contract",
    "review_contract",
    "release_contract",
    "resolve_approval",
    "synchronize_workflow",
]
