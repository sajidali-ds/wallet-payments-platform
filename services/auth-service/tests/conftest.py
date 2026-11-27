import os

import pytest

# Set BEFORE any `app` module is imported: Settings is read from the environment and cached.
os.environ["JWT_SECRET"] = "test-secret-" + "k" * 40
os.environ["BCRYPT_ROUNDS"] = "4"  # lowest allowed cost: keeps the suite fast
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://unused:unused@localhost:5432/unused"
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Everything under tests/integration/ gets the `integration` marker automatically."""
    for item in items:
        if "integration" in item.path.parts:
            item.add_marker(pytest.mark.integration)
