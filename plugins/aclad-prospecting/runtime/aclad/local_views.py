"""One local projection cycle; never calls a provider or transmits an event."""
from .models import GateError


def refresh_local_views(store) -> None:
    if store.workspace_root is None or store._projecting or store._depth:
        return
    store._projecting = True
    try:
        from .outcome_learning import refresh_outcome_observations
        from .results import refresh_results
        from .workflow_views import refresh_workflow_views
        from .setup_flow import refresh_setup_view
        refresh_outcome_observations(store)
        refresh_results(store)
        refresh_workflow_views(store)
        refresh_setup_view(store)
    except OSError:
        raise GateError('results_report_unavailable') from None
    finally:
        store._projecting = False
