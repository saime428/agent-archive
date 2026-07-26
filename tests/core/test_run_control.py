from __future__ import annotations

import pytest

from agent.core.run_control import RunControl, validate_timeout_seconds


@pytest.mark.parametrize("value", [True, False, 0, -1, 3601, 1.0, "30"])
def test_validate_timeout_seconds_rejects_non_integer_or_out_of_range_values(value: object) -> None:
    with pytest.raises(ValueError, match="timeout_seconds must be an integer from 1 to 3600"):
        validate_timeout_seconds(value)


def test_validate_timeout_seconds_applies_the_default_and_boundaries() -> None:
    assert validate_timeout_seconds(None) == 900
    assert validate_timeout_seconds(1) == 1
    assert validate_timeout_seconds(3600) == 3600


def test_run_control_uses_monotonic_deadline_and_cancel_has_priority() -> None:
    now = [10.0]
    control = RunControl.with_timeout(5, clock=lambda: now[0])

    assert control.stop_reason() is None
    now[0] = 15.0
    assert control.stop_reason() == "timed_out"
    assert control.request_cancel() is True
    assert control.request_cancel() is False
    assert control.stop_reason() == "cancelled"


def test_run_control_without_deadline_only_stops_after_cancel() -> None:
    control = RunControl()

    assert control.stop_reason() is None
    assert control.request_cancel() is True
    assert control.stop_reason() == "cancelled"


def test_run_control_promotes_external_cancel_probe_to_local_cancel() -> None:
    requested = [False]
    control = RunControl(cancel_probe=lambda: requested[0])

    assert control.stop_reason() is None
    requested[0] = True
    assert control.stop_reason() == "cancelled"
    requested[0] = False
    assert control.stop_reason() == "cancelled"
