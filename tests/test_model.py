from __future__ import annotations

import math
from statistics import NormalDist

import pytest

from landedcost.model import (
    cost_breakdown,
    freight_per_unit,
    pick_lowest,
    safety_stock_units,
    z_score,
)

FIXTURE = dict(
    annual_demand=12_000,
    weekly_demand_sd=40,
    order_qty=2_000,
    fob_local=10.0,
    fx=1.0,
    freight=2.0,
    base_duty=0.04,
    additional_tariff=0.25,
    port=0.15,
    transit_days_mean=38,
    transit_days_sd=8,
    carrying_rate=0.22,
    service_level=0.97,
)


@pytest.fixture()
def fixture_cost():
    return cost_breakdown(**FIXTURE)


def test_landed_cost_of_fixture_sku(fixture_cost):
    assert fixture_cost.landed == pytest.approx(15.05, abs=1e-12)
    assert fixture_cost.duty == pytest.approx(2.9, abs=1e-12)


def test_safety_stock_units_of_fixture_sku(fixture_cost):
    assert fixture_cost.safety_stock_units == pytest.approx(526.09, abs=0.005)


def test_carrying_charges_of_fixture_sku(fixture_cost):
    assert fixture_cost.pipeline == pytest.approx(0.3447, abs=5e-5)
    assert fixture_cost.safety_stock == pytest.approx(0.1452, abs=5e-5)
    assert fixture_cost.cycle == pytest.approx(0.2759, abs=5e-5)


def test_total_cost_of_fixture_sku(fixture_cost):
    assert fixture_cost.total == pytest.approx(15.8158, abs=5e-5)
    parts = (
        fixture_cost.landed + fixture_cost.pipeline + fixture_cost.safety_stock + fixture_cost.cycle
    )
    assert fixture_cost.total == pytest.approx(parts, rel=1e-15)


def test_z_score_matches_known_quantiles():
    assert z_score(0.97) == pytest.approx(1.8807936, abs=1e-7)
    assert z_score(0.5) == 0.0
    assert z_score(0.95) == pytest.approx(NormalDist().inv_cdf(0.95), rel=1e-15)


def test_safety_stock_uses_lead_time_variance():
    kwargs = dict(
        annual_demand=12_000,
        weekly_demand_sd=40,
        transit_days_mean=38,
        service_level=0.97,
    )
    steady = safety_stock_units(transit_days_sd=0, **kwargs)
    variable = safety_stock_units(transit_days_sd=8, **kwargs)
    # With no lead-time variance only demand variance remains: z * sd_d * sqrt(L).
    assert steady == pytest.approx(z_score(0.97) * 40 * math.sqrt(38 / 7), rel=1e-12)
    assert variable > steady * 1.5


def test_safety_stock_demand_and_lead_time_terms_add_in_variance():
    ss = safety_stock_units(
        annual_demand=5_200,
        weekly_demand_sd=30,
        transit_days_mean=14,
        transit_days_sd=7,
        service_level=0.9,
    )
    # d = 100/week, L = 2 weeks, sd_L = 1 week: variance = 2*900 + 100^2*1 = 11800.
    assert ss == pytest.approx(z_score(0.9) * math.sqrt(11_800), rel=1e-12)


def test_pipeline_charge_scales_with_transit_days():
    short = cost_breakdown(**{**FIXTURE, "transit_days_mean": 6, "transit_days_sd": 2})
    long = cost_breakdown(**FIXTURE)
    assert long.pipeline / short.pipeline == pytest.approx(38 / 6, rel=1e-12)


def test_fx_converts_local_price_before_duty():
    cost = cost_breakdown(**{**FIXTURE, "fob_local": 100.0, "fx": 0.1})
    assert cost.customs_value == pytest.approx(10.0)
    assert cost.landed == pytest.approx(15.05, abs=1e-12)


def test_tariff_slope_matches_finite_difference():
    lo = cost_breakdown(**{**FIXTURE, "additional_tariff": 0.10})
    hi = cost_breakdown(**{**FIXTURE, "additional_tariff": 0.30})
    assert (hi.total - lo.total) / 0.20 == pytest.approx(lo.tariff_slope, rel=1e-12)


def test_total_cost_is_linear_in_tariff():
    totals = [cost_breakdown(**{**FIXTURE, "additional_tariff": t}).total for t in (0.0, 0.25, 0.5)]
    assert totals[1] - totals[0] == pytest.approx(totals[2] - totals[1], rel=1e-12)


def test_freight_per_unit_spreads_container_over_cube():
    assert freight_per_unit(4200, 58, 0.5) == pytest.approx(4200 / 58 * 0.5)


def test_pick_lowest_breaks_ties_toward_the_first_origin():
    assert pick_lowest({"China": 2.0, "Vietnam": 2.0, "Mexico": 3.0}) == "China"
    assert pick_lowest({"China": 3.0, "Vietnam": 2.0, "Mexico": 2.0}) == "Vietnam"
