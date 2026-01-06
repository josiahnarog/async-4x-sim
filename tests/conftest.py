import pytest
from tests.test_orders import build_game as _build_game


@pytest.fixture
def game():
    """
    Shared GameState fixture for all tests.
    """
    return _build_game()