from unittest.mock import MagicMock

import pytest

from app.core.metrics import KubernetesMetrics
from app.settings import Settings

pytestmark = pytest.mark.unit


def test_pods_by_phase_emits_deltas_and_zeroes_vanished_phases(test_settings: Settings) -> None:
    m = KubernetesMetrics(test_settings)
    m.pods_by_phase = MagicMock()

    m.update_pods_by_phase({"Running": 2})
    m.update_pods_by_phase({"Running": 1, "Succeeded": 1})
    m.update_pods_by_phase({"Running": 1, "Succeeded": 1})
    m.update_pods_by_phase({})

    adds = sorted((c.args[0], c.kwargs["attributes"]["phase"]) for c in m.pods_by_phase.add.call_args_list)
    assert adds == [(-1, "Running"), (-1, "Running"), (-1, "Succeeded"), (1, "Succeeded"), (2, "Running")]
