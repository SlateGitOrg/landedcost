"""Scenario sweep: how many SKUs each origin wins as the incumbent's tariff changes."""

from __future__ import annotations

from landedcost.breakeven import tariff_line
from landedcost.data import Dataset
from landedcost.model import evaluate, pick_lowest

SCENARIO_STEPS = tuple(round(0.05 * i, 2) for i in range(13))  # 0% .. 60%


def winners(ds: Dataset, incumbent_tariff: float) -> dict[str, str]:
    """sku_id -> winning origin when the incumbent's additional tariff is ``incumbent_tariff``."""
    out: dict[str, str] = {}
    for s in ds.skus:
        totals = {o.name: evaluate(ds, s, o.name).total for o in ds.origins}
        totals[ds.incumbent] = tariff_line(ds, s, ds.incumbent).at(incumbent_tariff)
        out[s.sku_id] = pick_lowest(totals)
    return out


def win_counts(ds: Dataset, incumbent_tariff: float) -> dict[str, int]:
    w = winners(ds, incumbent_tariff)
    return {o.name: sum(1 for v in w.values() if v == o.name) for o in ds.origins}


def scenario_grid(
    ds: Dataset, steps: tuple[float, ...] = SCENARIO_STEPS
) -> dict[float, dict[str, int]]:
    return {t: win_counts(ds, t) for t in steps}
