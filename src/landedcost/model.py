"""Pure-function reference model for landed unit cost and its inventory consequences.

Total unit cost = landed cost (FOB, freight, duty, port) plus three carrying charges on the
inventory that the origin's lead time forces the business to own:

* pipeline stock: goods owned from FOB until receipt, ``transit_days / 365`` of a year per unit;
* safety stock: sized for the lead-time demand variance *and* the lead-time variance, at a
  cycle service level (a stated simplification: it ignores the size of a stockout);
* cycle stock: half an order quantity on hand on average.

Every carrying charge is proportional to landed cost, so total cost is linear in the tariff.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist

from landedcost.data import Dataset, Sku

WEEKS_PER_YEAR = 52
DAYS_PER_WEEK = 7
DAYS_PER_YEAR = 365


@dataclass(frozen=True)
class CostBreakdown:
    customs_value: float
    freight: float
    duty: float
    port: float
    landed: float
    pipeline: float
    safety_stock_units: float
    safety_stock: float
    cycle: float
    total: float
    tariff_slope: float  # d(total) / d(additional tariff), per unit


def z_score(service_level: float) -> float:
    """Standard normal quantile for the cycle service level (Excel NORM.S.INV)."""
    return NormalDist().inv_cdf(service_level)


def safety_stock_units(
    *,
    annual_demand: float,
    weekly_demand_sd: float,
    transit_days_mean: float,
    transit_days_sd: float,
    service_level: float,
) -> float:
    """z * sqrt(L * sd_d^2 + d^2 * sd_L^2), with d per week and L, sd_L in weeks."""
    weekly_demand = annual_demand / WEEKS_PER_YEAR
    lead_weeks = transit_days_mean / DAYS_PER_WEEK
    lead_sd_weeks = transit_days_sd / DAYS_PER_WEEK
    variance = lead_weeks * weekly_demand_sd**2 + weekly_demand**2 * lead_sd_weeks**2
    return z_score(service_level) * math.sqrt(variance)


def cost_breakdown(
    *,
    annual_demand: float,
    weekly_demand_sd: float,
    order_qty: float,
    fob_local: float,
    fx: float,
    freight: float,
    base_duty: float,
    additional_tariff: float,
    port: float,
    transit_days_mean: float,
    transit_days_sd: float,
    carrying_rate: float,
    service_level: float,
) -> CostBreakdown:
    """Landed and total unit cost, in USD, for one SKU shipped from one origin."""
    customs_value = fob_local * fx
    duty = customs_value * (base_duty + additional_tariff)
    landed = customs_value + freight + duty + port
    pipeline = transit_days_mean / DAYS_PER_YEAR * landed * carrying_rate
    ss_units = safety_stock_units(
        annual_demand=annual_demand,
        weekly_demand_sd=weekly_demand_sd,
        transit_days_mean=transit_days_mean,
        transit_days_sd=transit_days_sd,
        service_level=service_level,
    )
    safety = ss_units * landed * carrying_rate / annual_demand
    cycle = order_qty / 2 * landed * carrying_rate / annual_demand
    total = landed + pipeline + safety + cycle
    return CostBreakdown(
        customs_value=customs_value,
        freight=freight,
        duty=duty,
        port=port,
        landed=landed,
        pipeline=pipeline,
        safety_stock_units=ss_units,
        safety_stock=safety,
        cycle=cycle,
        total=total,
        tariff_slope=customs_value * total / landed,
    )


def freight_per_unit(container_cost: float, usable_cube: float, unit_cube: float) -> float:
    """Container (or truckload) cost spread over its usable cube, times the unit's cube."""
    return container_cost / usable_cube * unit_cube


def evaluate(
    ds: Dataset,
    sku: Sku,
    origin: str,
    *,
    additional_tariff: float | None = None,
) -> CostBreakdown:
    """Cost breakdown for one SKU x origin; ``additional_tariff`` overrides the tariff table."""
    o = ds.origin(origin)
    tariff = ds.additional_tariff(sku, origin) if additional_tariff is None else additional_tariff
    return cost_breakdown(
        annual_demand=sku.annual_demand,
        weekly_demand_sd=sku.weekly_demand_sd,
        order_qty=sku.order_qty,
        fob_local=ds.quotes[(sku.sku_id, origin)],
        fx=ds.fx[o.currency],
        freight=freight_per_unit(o.container_cost, o.usable_cube, sku.unit_cube),
        base_duty=ds.base_duty[sku.hts_group],
        additional_tariff=tariff,
        port=o.port_per_unit,
        transit_days_mean=o.transit_days_mean,
        transit_days_sd=o.transit_days_sd,
        carrying_rate=ds.carrying_rate,
        service_level=ds.service_level,
    )


@dataclass(frozen=True)
class CalcRow:
    sku_id: str
    origin: str
    additional_tariff: float
    cost: CostBreakdown


def compute_all(ds: Dataset) -> list[CalcRow]:
    """One row per SKU x origin, SKU-major, origins in dataset order."""
    return [
        CalcRow(s.sku_id, o.name, ds.additional_tariff(s, o.name), evaluate(ds, s, o.name))
        for s in ds.skus
        for o in ds.origins
    ]


def pick_lowest(values: dict[str, float]) -> str:
    """Origin with the lowest value; ties go to the earliest origin (as MATCH(MIN()) does)."""
    best = min(values.values())
    return next(name for name, v in values.items() if v == best)


@dataclass(frozen=True)
class CompareRow:
    sku_id: str
    total: dict[str, float]  # origin -> total unit cost
    landed: dict[str, float]  # origin -> landed unit cost (no inventory carrying)
    best_origin: str
    best_total: float
    saving_per_unit: float  # incumbent total minus best total
    annual_saving: float
    price_pick: str  # origin a buyer picks on landed cost alone
    flip: bool  # landed cost picks a move, total cost keeps the incumbent


def compare(ds: Dataset, rows: list[CalcRow] | None = None) -> list[CompareRow]:
    rows = rows if rows is not None else compute_all(ds)
    by_key = {(r.sku_id, r.origin): r.cost for r in rows}
    names = [o.name for o in ds.origins]
    out: list[CompareRow] = []
    for s in ds.skus:
        total = {n: by_key[(s.sku_id, n)].total for n in names}
        landed = {n: by_key[(s.sku_id, n)].landed for n in names}
        best = pick_lowest(total)
        price_pick = pick_lowest(landed)
        saving = total[ds.incumbent] - total[best]
        out.append(
            CompareRow(
                sku_id=s.sku_id,
                total=total,
                landed=landed,
                best_origin=best,
                best_total=total[best],
                saving_per_unit=saving,
                annual_saving=saving * s.annual_demand,
                price_pick=price_pick,
                flip=price_pick != ds.incumbent and best == ds.incumbent,
            )
        )
    return out
