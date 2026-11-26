from __future__ import annotations

import pytest

from landedcost.breakeven import (
    TariffLine,
    breakeven,
    breakeven_table,
    raw_breakeven,
    tariff_line,
)
from landedcost.model import compare, evaluate
from landedcost.scenario import SCENARIO_STEPS, scenario_grid, win_counts, winners


def test_tariff_line_reproduces_the_model_at_any_tariff(ds):
    sku = ds.skus[3]
    line = tariff_line(ds, sku, "China")
    for t in (0.0, 0.1, 0.25, 0.6, 1.0):
        direct = evaluate(ds, sku, "China", additional_tariff=t).total
        assert line.at(t) == pytest.approx(direct, rel=1e-12)


def test_closed_form_on_a_hand_computed_line():
    line = TariffLine(intercept=10.0, slope=4.0)
    assert line.at(0.25) == 11.0
    # An alternative costing 11.0 ties at t* = (11 - 10) / 4 = 0.25.
    assert (11.0 - line.intercept) / line.slope == 0.25


def test_substitution_makes_totals_equal_for_every_finite_breakeven(ds):
    checked = 0
    for sku in ds.skus:
        for alt in ("Vietnam", "Mexico"):
            t = breakeven(ds, sku, alt)
            if t is None:
                continue
            china = evaluate(ds, sku, "China", additional_tariff=t).total
            other = evaluate(ds, sku, alt).total
            assert china == pytest.approx(other, rel=1e-9), (sku.sku_id, alt)
            checked += 1
    assert checked >= 70


def test_alternative_wins_only_above_its_breakeven(ds):
    sku = ds.skus[0]
    t = breakeven(ds, sku, "Vietnam")
    assert t is not None
    alt = evaluate(ds, sku, "Vietnam").total
    assert evaluate(ds, sku, "China", additional_tariff=t - 0.02).total < alt
    assert evaluate(ds, sku, "China", additional_tariff=t + 0.02).total > alt


def test_breakeven_is_blank_outside_zero_to_one(ds, truth):
    by_id = {s.sku_id: s for s in ds.skus}
    for sku_id in truth["bulky"]:
        sku = by_id[sku_id]
        assert raw_breakeven(ds, sku, "Mexico") < 0  # ahead even with no China tariff
        assert breakeven(ds, sku, "Mexico") is None
    table = breakeven_table(ds)
    assert all(v is None or 0 <= v <= 1 for row in table.values() for v in row.values())
    assert set(table) == {s.sku_id for s in ds.skus}


def test_flip_skus_break_even_just_above_the_base_tariff(ds, truth):
    by_id = {s.sku_id: s for s in ds.skus}
    for sku_id in truth["flip"]:
        t = breakeven(ds, by_id[sku_id], "Vietnam")
        assert 0.25 < t < 0.26  # China holds on only because of lead-time inventory


def test_scenario_columns_each_sum_to_forty(ds):
    grid = scenario_grid(ds)
    assert list(grid) == list(SCENARIO_STEPS) and len(grid) == 13
    for t, counts in grid.items():
        assert sum(counts.values()) == 40, t


def test_china_wins_never_increase_as_its_tariff_rises(ds):
    wins = [c["China"] for c in scenario_grid(ds).values()]
    assert all(a >= b for a, b in zip(wins, wins[1:], strict=False))
    assert wins[0] > wins[-1]


def test_scenario_at_base_tariff_matches_compare(ds):
    counts = win_counts(ds, 0.25)
    expected = {o.name: 0 for o in ds.origins}
    for r in compare(ds):
        expected[r.best_origin] += 1
    assert counts == expected


def test_scenario_matches_a_full_recompute_with_overridden_tariff(ds):
    t = 0.15
    expected = {}
    for sku in ds.skus:
        totals = {
            o.name: evaluate(
                ds, sku, o.name, additional_tariff=t if o.name == "China" else None
            ).total
            for o in ds.origins
        }
        expected[sku.sku_id] = min(totals, key=lambda k: (totals[k], list(totals).index(k)))
    assert winners(ds, t) == expected


def test_at_zero_china_tariff_the_six_bulky_skus_are_the_mexico_wins(ds, truth):
    w = winners(ds, 0.0)
    mexico = sorted(k for k, v in w.items() if v == "Mexico")
    assert set(truth["bulky"]) <= set(mexico)
