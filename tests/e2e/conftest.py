from collections.abc import Iterator

import pytest

from tests.e2e.runtime import assert_free_threaded_runtime


@pytest.fixture(autouse=True)
def _check_e2e_runtime() -> Iterator[None]:
    assert_free_threaded_runtime()
    yield
    assert_free_threaded_runtime()
