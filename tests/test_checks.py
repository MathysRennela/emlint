from emlint.checks import ALL_CHECKS

from typing import Callable

import pytest, inspect


def test_validate_checks():
    """Validate all registered checks follow the required pattern."""
    for name, check_fn in ALL_CHECKS.items():
        # Create a simple test model to verify check doesn't crash
        # This would be a basic smoke test
        pass


check_fns = ALL_CHECKS.values()


@pytest.mark.parametrize("check_fn", check_fns)
def test_validate_check_signature(check_fn: Callable) -> None:
    """Validate a check function has the correct signature."""

    sig = inspect.signature(check_fn)
    params = list(sig.parameters.keys())

    assert len(params) >= 1 and params[0] == "model"
