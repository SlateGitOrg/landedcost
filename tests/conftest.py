from __future__ import annotations

import pytest

from landedcost.data import Dataset
from landedcost.generate import generate
from landedcost.workbook import build_workbook


@pytest.fixture(scope="session")
def seeded() -> tuple[Dataset, dict]:
    return generate(7)


@pytest.fixture(scope="session")
def ds(seeded) -> Dataset:
    return seeded[0]


@pytest.fixture(scope="session")
def truth(seeded) -> dict:
    return seeded[1]


@pytest.fixture(scope="session")
def workbook_path(ds, tmp_path_factory):
    return build_workbook(ds, tmp_path_factory.mktemp("wb") / "landedcost.xlsx")
