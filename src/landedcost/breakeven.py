"""Closed-form break-even tariff on the incumbent origin.

Every carrying charge is a fixed fraction of landed cost, so total unit cost is
``m x landed`` with ``m`` independent of the tariff, and landed cost is linear in the
incumbent's additional tariff ``t``. Hence ``TCO(t) = a + b t`` and an alternative origin with
total cost ``TCO_alt`` ties the incumbent at ``t* = (TCO_alt - a) / b``.
"""

from __future__ import annotations

from dataclasses import dataclass

from landedcost.data import Dataset, Sku
from landedcost.model import evaluate


@dataclass(frozen=True)
class TariffLine:
    """TCO = intercept + slope x additional tariff, per unit."""

    intercept: float
    slope: float

    def at(self, tariff: float) -> float:
        return self.intercept + self.slope * tariff


def tariff_line(ds: Dataset, sku: Sku, origin: str) -> TariffLine:
    """Line through the incumbent's total cost, as a function of its additional tariff."""
    base = evaluate(ds, sku, origin)
    t0 = ds.additional_tariff(sku, origin)
    return TariffLine(intercept=base.total - base.tariff_slope * t0, slope=base.tariff_slope)


def raw_breakeven(ds: Dataset, sku: Sku, alternative: str) -> float:
    """Unclamped t* at which the alternative's total cost equals the incumbent's."""
    line = tariff_line(ds, sku, ds.incumbent)
    return (evaluate(ds, sku, alternative).total - line.intercept) / line.slope


def breakeven(ds: Dataset, sku: Sku, alternative: str) -> float | None:
    """The break-even tariff, or None when it falls outside 0-100%."""
    t = raw_breakeven(ds, sku, alternative)
    return t if 0 <= t <= 1 else None


def breakeven_table(ds: Dataset) -> dict[str, dict[str, float | None]]:
    """sku_id -> alternative origin -> break-even tariff (None when outside 0-100%)."""
    alternatives = [o.name for o in ds.origins if o.name != ds.incumbent]
    return {s.sku_id: {a: breakeven(ds, s, a) for a in alternatives} for s in ds.skus}
