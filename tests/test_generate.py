from __future__ import annotations

import json

import pytest

from landedcost.data import load_dataset, save_dataset
from landedcost.generate import generate, write
from landedcost.model import compare, compute_all, evaluate, pick_lowest


def test_shape_of_seeded_data(ds):
    assert len(ds.skus) == 40
    assert [o.name for o in ds.origins] == ["China", "Vietnam", "Mexico"]
    assert len(ds.quotes) == 120
    assert len({s.sku_id for s in ds.skus}) == 40
    assert ds.carrying_rate == 0.22 and ds.service_level == 0.97


def test_generator_is_deterministic_and_seed_sensitive():
    a, truth_a = generate(7)
    b, truth_b = generate(7)
    c, _ = generate(8)
    assert a == b and truth_a == truth_b
    assert a.quotes != c.quotes


def test_origin_parameters_follow_the_brief(ds):
    by = {o.name: o for o in ds.origins}
    assert (by["China"].transit_days_mean, by["China"].transit_days_sd) == (38, 8)
    assert (by["Vietnam"].transit_days_mean, by["Vietnam"].transit_days_sd) == (45, 12)
    assert (by["Mexico"].transit_days_mean, by["Mexico"].transit_days_sd) == (6, 2)
    assert by["Mexico"].mode == "truck" and by["China"].mode == "ocean"


def test_tariff_table_and_base_duties(ds):
    assert ds.tariffs["China"].qualifying == ds.tariffs["China"].non_qualifying == 0.25
    assert ds.tariffs["Vietnam"].qualifying == 0.10
    assert (ds.tariffs["Mexico"].qualifying, ds.tariffs["Mexico"].non_qualifying) == (0.0, 0.10)
    assert all(0.0 <= d <= 0.06 for d in ds.base_duty.values())
    assert {s.hts_group for s in ds.skus} <= set(ds.base_duty)


def test_fob_premiums_over_china(ds):
    for s in ds.skus:
        usd = {o.name: ds.quotes[(s.sku_id, o.name)] * ds.fx[o.currency] for o in ds.origins}
        vn = usd["Vietnam"] / usd["China"] - 1
        mx = usd["Mexico"] / usd["China"] - 1
        assert 0.049 <= vn <= 0.121, (s.sku_id, vn)
        assert 0.179 <= mx <= 0.301, (s.sku_id, mx)


def test_exactly_four_skus_are_not_usmca_qualifying(ds, truth):
    non_q = sorted(s.sku_id for s in ds.skus if not s.usmca_qualifying)
    assert non_q == truth["non_qualifying"]
    assert len(non_q) == 4


def test_bulky_skus_choose_mexico_at_zero_china_tariff(ds, truth):
    assert len(truth["bulky"]) == 6
    by_id = {s.sku_id: s for s in ds.skus}
    for sku_id in truth["bulky"]:
        sku = by_id[sku_id]
        totals = {
            o.name: evaluate(
                ds, sku, o.name, additional_tariff=0.0 if o.name == "China" else None
            ).total
            for o in ds.origins
        }
        assert pick_lowest(totals) == "Mexico", sku_id
        assert sku.unit_cube >= 0.35  # bulky: freight dominates


def test_bulky_skus_are_freight_dominated(ds, truth):
    rows = {(r.sku_id, r.origin): r.cost for r in compute_all(ds)}
    for sku_id in truth["bulky"]:
        china = rows[(sku_id, "China")]
        assert china.freight > 0.3 * china.customs_value


def test_flip_set_recovered_from_data_equals_planted_set(ds, truth):
    flips = sorted(r.sku_id for r in compare(ds) if r.flip)
    assert flips == truth["flip"]
    assert len(flips) == 5
    for r in compare(ds):
        if r.flip:
            assert r.price_pick == "Vietnam" and r.best_origin == "China"


def test_flip_skus_are_high_value_and_low_volume(ds, truth):
    by_id = {s.sku_id: s for s in ds.skus}
    median_demand = sorted(s.annual_demand for s in ds.skus)[20]
    for sku_id in truth["flip"]:
        assert by_id[sku_id].annual_demand < median_demand
        assert ds.quotes[(sku_id, "China")] * ds.fx["CNY"] > 80


def test_non_qualifying_skus_do_not_choose_mexico(ds, truth):
    best = {r.sku_id: r.best_origin for r in compare(ds)}
    for sku_id in truth["non_qualifying"]:
        assert best[sku_id] != "Mexico", sku_id


def test_non_qualifying_skus_lose_mexicos_tariff_advantage(ds, truth):
    by_id = {s.sku_id: s for s in ds.skus}
    for sku_id in truth["non_qualifying"]:
        assert ds.additional_tariff(by_id[sku_id], "Mexico") == 0.10


def test_csv_round_trip(ds, tmp_path):
    save_dataset(ds, tmp_path)
    assert load_dataset(tmp_path) == ds


def test_write_creates_inputs_and_truth_file(tmp_path):
    ds = write(7, tmp_path)
    names = {p.name for p in tmp_path.iterdir()}
    assert {"skus.csv", "origins.csv", "quotes.csv", "duties.csv", "tariffs.csv"} <= names
    assert {"fx.csv", "params.json", "truth.json"} <= names
    truth = json.loads((tmp_path / "truth.json").read_text())
    assert truth["seed"] == 7 and len(truth["flip"]) == 5
    assert len(ds.skus) == 40


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_planted_patterns_hold_for_other_seeds(seed):
    ds, truth = generate(seed)
    flips = sorted(r.sku_id for r in compare(ds) if r.flip)
    assert flips == truth["flip"]


def test_committed_sample_data_matches_the_seeded_generator(ds):
    from pathlib import Path

    assert load_dataset(Path(__file__).resolve().parent.parent / "data") == ds
