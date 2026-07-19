"""Application-level registration of supported adapter reconcilers."""

from sim_pilot.reconciliation.openttd import reconcile_openttd_action
from sim_pilot.reconciliation.reference import reconcile_reference_action
from sim_pilot.runtime.recovery import ReconciliationDispatcher

LEGACY_OPENTTD_ADAPTER_TYPE = "sim_pilot.adapters.openttd.adapter.OpenTTDAdapter"


def default_reconciliation_dispatcher() -> ReconciliationDispatcher:
    """Build a fresh explicit registry, including the pre-7.6 persisted OpenTTD alias."""
    return ReconciliationDispatcher(
        {
            "reference": reconcile_reference_action,
            "openttd": reconcile_openttd_action,
            LEGACY_OPENTTD_ADAPTER_TYPE: reconcile_openttd_action,
        }
    )
