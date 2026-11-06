import pytest

from tests.cli.storage_fixtures import release_leases


@pytest.fixture(autouse=True)
def close_test_leases():
    yield
    release_leases()
