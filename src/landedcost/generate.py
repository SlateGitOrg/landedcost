"""Seeded synthetic data: 40 SKUs x 3 origins, with three deliberately planted patterns.

Planted patterns (recorded in ``truth.json``; the analysis must recover them from the data):

* bulky: 6 low-value tool chests where freight dominates, so Mexico wins even with no tariff
  on China;
* flip: 5 high-value, low-volume SKUs where landed cost (price + freight + duty + port) picks
  Vietnam but total cost, with inventory carrying, picks China;
* non-qualifying: 4 SKUs that do not meet USMCA origin rules, so Mexico pays the additional
  tariff and does not win in the base scenario.

Each planted SKU is drawn from ranges that make its pattern likely and is redrawn if it does
not show the pattern, so the result is deterministic for a seed and the patterns always hold.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from landedcost.data import Dataset, Origin, Sku, Tariff, save_dataset
from landedcost.model import compare, compute_all, evaluate, pick_lowest

CARRYING_RATE = 0.22
SERVICE_LEVEL = 0.97
CHINA_BASE_TARIFF = 0.25

ORIGINS = (
    Origin("China", "CNY", "ocean", 38, 8, 4200, 58, 0.15),
    Origin("Vietnam", "USD", "ocean", 45, 12, 4800, 58, 0.18),
    Origin("Mexico", "MXN", "truck", 6, 2, 3800, 90, 0.20),
)
TARIFFS = (
    Tariff("China", CHINA_BASE_TARIFF, CHINA_BASE_TARIFF),
    Tariff("Vietnam", 0.10, 0.10),
    Tariff("Mexico", 0.0, 0.10),
)
FX = {"CNY": 0.14, "USD": 1.0, "MXN": 0.056}

# Illustrative base duty rates by HTS group (not a statement of any actual tariff schedule).
BASE_DUTY = {
    "4202": 0.03,
    "7318": 0.00,
    "8201": 0.03,
    "8203": 0.04,
    "8204": 0.04,
    "8205": 0.05,
    "8206": 0.02,
    "8467": 0.05,
    "9017": 0.06,
    "9403": 0.00,
}


@dataclass(frozen=True)
class Profile:
    """Ranges one group of SKUs is drawn from."""

    fob: tuple[float, float]  # China FOB, USD
    demand: tuple[float, float]  # annual units, log-uniform
    cv: tuple[float, float]  # coefficient of variation of weekly demand
    cube: tuple[float, float]  # m3 per unit
    cover_weeks: tuple[float, float]  # order quantity as weeks of demand
    vn_premium: tuple[float, float]
    mx_premium: tuple[float, float]
    qty_step: int = 50


HAND = Profile(
    (3, 35), (3000, 40000), (0.25, 0.6), (0.0008, 0.006), (6, 13), (0.05, 0.12), (0.18, 0.30)
)
FASTENER = Profile(
    (4, 18), (8000, 60000), (0.2, 0.5), (0.001, 0.005), (6, 13), (0.05, 0.12), (0.18, 0.30)
)
STORAGE = Profile(
    (8, 40), (2000, 15000), (0.3, 0.7), (0.01, 0.08), (6, 13), (0.05, 0.12), (0.18, 0.30)
)
CHEST = Profile(
    (28, 45), (1200, 4500), (0.3, 0.5), (0.35, 0.55), (8, 12), (0.06, 0.12), (0.20, 0.26)
)
FLIP = Profile(
    (85, 160), (300, 900), (0.8, 1.6), (0.03, 0.06), (6, 10), (0.115, 0.12), (0.285, 0.30), 10
)
NONQUAL = Profile(
    (10, 30), (3000, 20000), (0.25, 0.5), (0.002, 0.01), (6, 13), (0.05, 0.12), (0.26, 0.30)
)

# (description, hts group)
HAND_TOOLS = [
    ("Claw hammer 16 oz", "8201"),
    ("Rubber mallet 24 oz", "8201"),
    ("Combination wrench set 10 pc", "8204"),
    ("Adjustable wrench 10 in", "8204"),
    ("Slip-joint pliers 8 in", "8203"),
    ("Long-nose pliers 6 in", "8203"),
    ("Aviation tin snips", "8203"),
    ("Screwdriver set 12 pc", "8205"),
    ("Retractable utility knife", "8205"),
    ("Hex key set metric and SAE", "8205"),
    ("Socket set 40 pc", "8206"),
    ("Pry bar set 3 pc", "8205"),
    ("Hacksaw frame 12 in", "8205"),
]
FASTENER_KITS = [
    ("Wood screw assortment 600 pc", "7318"),
    ("Hex bolt assortment 350 pc", "7318"),
    ("Machine screw kit 800 pc", "7318"),
    ("Wall anchor kit 300 pc", "7318"),
    ("Self-tapping screw kit 500 pc", "7318"),
    ("Nut and washer assortment 900 pc", "7318"),
    ("Cabinet hardware kit 250 pc", "7318"),
]
STORAGE_ITEMS = [
    ("Canvas tool bag 18 in", "4202"),
    ("Tool pouch organizer", "4202"),
    ("Stackable organizer tray", "4202"),
    ("Socket rail organizer", "4202"),
    ("Parts bin 24 compartment", "4202"),
]
CHESTS = [
    ("Rolling tool chest 26 in 5 drawer", "9403"),
    ("Steel tool chest 41 in 9 drawer", "9403"),
    ("Mobile workbench cabinet", "9403"),
    ("Stackable tool box set 3 pc", "9403"),
    ("Top chest 27 in 6 drawer", "9403"),
    ("Side cabinet roller 24 in", "9403"),
]
FLIPS = [
    ("Digital torque wrench 1/2 in", "9017"),
    ("Laser distance measurer 100 ft", "9017"),
    ("Digital caliper 6 in", "9017"),
    ("Cordless rotary multi-tool kit", "8467"),
    ("Stud finder with deep scan", "9017"),
]
NONQUALIFYING = [
    ("Pipe wrench 14 in", "8204"),
    ("Locking pliers set 3 pc", "8203"),
    ("Bolt cutter 24 in", "8203"),
    ("Ratcheting wrench set 8 pc", "8204"),
]

_MAX_DRAWS = 500


def _log_uniform(rng: np.random.Generator, lo: float, hi: float) -> float:
    return float(np.exp(rng.uniform(np.log(lo), np.log(hi))))


def _draw(
    rng: np.random.Generator, p: Profile, qualifying: bool, desc: str, hts: str, category: str
) -> tuple[Sku, dict[str, float]]:
    """One candidate SKU and its FOB quotes by origin (local currency)."""
    demand = round(_log_uniform(rng, *p.demand), -1)
    weekly = demand / 52
    sd = round(float(rng.uniform(*p.cv)) * weekly, 1)
    cube = round(_log_uniform(rng, *p.cube), 4)
    weeks = float(rng.uniform(*p.cover_weeks))
    qty = max(p.qty_step, round(demand * weeks / 52 / p.qty_step) * p.qty_step)
    china_usd = _log_uniform(rng, *p.fob)
    usd = {
        "China": china_usd,
        "Vietnam": china_usd * (1 + float(rng.uniform(*p.vn_premium))),
        "Mexico": china_usd * (1 + float(rng.uniform(*p.mx_premium))),
    }
    quotes = {o.name: round(usd[o.name] / FX[o.currency], 3) for o in ORIGINS}
    sku = Sku(
        sku_id="",
        description=desc,
        category=category,
        hts_group=hts,
        usmca_qualifying=qualifying,
        annual_demand=demand,
        weekly_demand_sd=sd,
        unit_cube=cube,
        order_qty=float(qty),
    )
    return sku, quotes


def _single(sku: Sku, quotes: dict[str, float], sku_id: str) -> Dataset:
    return Dataset(
        skus=(Sku(**{**sku.__dict__, "sku_id": sku_id}),),
        origins=ORIGINS,
        quotes={(sku_id, o): q for o, q in quotes.items()},
        base_duty=BASE_DUTY,
        tariffs={t.origin: t for t in TARIFFS},
        fx=FX,
        carrying_rate=CARRYING_RATE,
        service_level=SERVICE_LEVEL,
    )


def _bulky_ok(ds: Dataset) -> bool:
    s = ds.skus[0]
    totals = {
        o.name: evaluate(ds, s, o.name, additional_tariff=0.0 if o.name == "China" else None).total
        for o in ds.origins
    }
    return pick_lowest(totals) == "Mexico"


def _flip_ok(ds: Dataset) -> bool:
    row = compare(ds, compute_all(ds))[0]
    return row.flip and row.price_pick == "Vietnam"


def _nonqual_ok(ds: Dataset) -> bool:
    return compare(ds, compute_all(ds))[0].best_origin != "Mexico"


def _plain_ok(ds: Dataset) -> bool:
    return not compare(ds, compute_all(ds))[0].flip


def _build(
    rng: np.random.Generator,
    items: list[tuple[str, str]],
    profile: Profile,
    category: str,
    qualifying: bool,
    accept,
) -> list[tuple[Sku, dict[str, float]]]:
    out = []
    for desc, hts in items:
        for _ in range(_MAX_DRAWS):
            sku, quotes = _draw(rng, profile, qualifying, desc, hts, category)
            if accept(_single(sku, quotes, "X")):
                out.append((sku, quotes))
                break
        else:  # pragma: no cover - ranges are chosen so this does not happen
            raise RuntimeError(f"no draw satisfied the pattern for {desc}")
    return out


def generate(seed: int = 7) -> tuple[Dataset, dict[str, object]]:
    """Return the dataset and the truth record of planted patterns."""
    rng = np.random.default_rng(seed)
    groups: list[tuple[str, list[tuple[Sku, dict[str, float]]]]] = [
        ("bulky", _build(rng, CHESTS, CHEST, "Tool storage", True, _bulky_ok)),
        ("flip", _build(rng, FLIPS, FLIP, "Hand tools", True, _flip_ok)),
        ("non_qualifying", _build(rng, NONQUALIFYING, NONQUAL, "Hand tools", False, _nonqual_ok)),
        ("plain", _build(rng, HAND_TOOLS, HAND, "Hand tools", True, _plain_ok)),
        ("plain", _build(rng, FASTENER_KITS, FASTENER, "Fastener kits", True, _plain_ok)),
        ("plain", _build(rng, STORAGE_ITEMS, STORAGE, "Tool storage", True, _plain_ok)),
    ]
    prefix = {"Hand tools": "HT", "Fastener kits": "FK", "Tool storage": "TS"}
    flat = [(kind, sku, quotes) for kind, members in groups for sku, quotes in members]
    order = rng.permutation(len(flat))
    counters = {p: 1000 for p in prefix.values()}
    skus: list[Sku] = []
    quotes: dict[tuple[str, str], float] = {}
    truth: dict[str, list[str]] = {"bulky": [], "flip": [], "non_qualifying": []}
    for i in order:
        kind, sku, q = flat[int(i)]
        pre = prefix[sku.category]
        counters[pre] += 1
        sku_id = f"{pre}-{counters[pre]}"
        skus.append(Sku(**{**sku.__dict__, "sku_id": sku_id}))
        for origin, price in q.items():
            quotes[(sku_id, origin)] = price
        if kind in truth:
            truth[kind].append(sku_id)
    skus.sort(key=lambda s: s.sku_id)
    ds = Dataset(
        skus=tuple(skus),
        origins=ORIGINS,
        quotes={(s.sku_id, o.name): quotes[(s.sku_id, o.name)] for s in skus for o in ORIGINS},
        base_duty=BASE_DUTY,
        tariffs={t.origin: t for t in TARIFFS},
        fx=FX,
        carrying_rate=CARRYING_RATE,
        service_level=SERVICE_LEVEL,
    )
    record: dict[str, object] = {
        "seed": seed,
        "base_china_additional_tariff": CHINA_BASE_TARIFF,
        **{k: sorted(v) for k, v in truth.items()},
    }
    return ds, record


def write(seed: int, out: Path) -> Dataset:
    ds, truth = generate(seed)
    save_dataset(ds, out)
    (out / "truth.json").write_text(json.dumps(truth, indent=2) + "\n", encoding="utf-8")
    return ds
