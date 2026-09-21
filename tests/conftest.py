"""Pytest configuration and database fixture."""
import pytest
from database.models import init_database


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """Ensure database tables exist for tests."""
    init_database()
