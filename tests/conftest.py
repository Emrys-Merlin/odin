from collections.abc import Iterator

import pytest

from odin.store import Store


@pytest.fixture
def store() -> Iterator[Store]:
    with Store(":memory:") as s:
        yield s
