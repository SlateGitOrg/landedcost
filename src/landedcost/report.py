"""Markdown report: recommended moves, break-even distribution and flip list."""

from __future__ import annotations

import statistics

from landedcost.breakeven import raw_breakeven
from landedcost.data import Dataset
from landedcost.model import CompareRow, compare
from landedcost.scenario import scenario_grid


def _pct(x: float | None) -> str:
    return "-" if x is None else f"{x * 100:.1f}%"


def _breakeven_text(raw: float) -> str:
    """Break-even tariff; outside 0-100% the alternative is always or never ahead."""
    if raw < 0:
        return "ahead at 0%"
    if raw > 1:
        return "never"
    return f"{raw * 100:.1f}%"


def compare_table(ds: Dataset, rows: list[CompareRow], limit: int | None = None) -> str:
    """Markdown table of SKUs ranked by annual saving vs the incumbent."""
    alts = [o.name for o in ds.origins[1:]]
    by_sku = {s.sku_id: s for s in ds.skus}
    ranked = sorted(rows, key=lambda r: r.annual_saving, reverse=True)
    if limit:
        ranked = ranked[:limit]
    head = ["SKU", "Current", "Recommended", "Saving / unit", "Saving / year"] + [
        f"Break-even {a}" for a in alts
    ]
    lines = ["| " + " | ".join(head) + " |", "|" + "|".join(["---"] * len(head)) + "|"]
    for r in ranked:
        cells = [
            r.sku_id,
            ds.incumbent,
            r.best_origin,
            f"${r.saving_per_unit:,.4f}",
            f"${r.annual_saving:,.0f}",
            *[_breakeven_text(raw_breakeven(ds, by_sku[r.sku_id], a)) for a in alts],
        ]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def scenario_table(ds: Dataset) -> str:
    grid = scenario_grid(ds)
    names = [o.name for o in ds.origins]
    lines = [
        "| " + f"{ds.incumbent} tariff" + " | " + " | ".join(names) + " |",
        "|" + "|".join(["---"] * (len(names) + 1)) + "|",
    ]
    for t, counts in grid.items():
        lines.append(f"| {t:.0%} | " + " | ".join(str(counts[n]) for n in names) + " |")
    return "\n".join(lines)


def breakeven_summary(ds: Dataset) -> str:
    alts = [o.name for o in ds.origins[1:]]
    out = [
        "| Alternative | Break-even in 0-100% | Median | Min | Max "
        "| Ahead even at 0% tariff | Never ahead |",
        "|---|---|---|---|---|---|---|",
    ]
    for a in alts:
        raws = [raw_breakeven(ds, s, a) for s in ds.skus]
        finite = [t for t in raws if 0 <= t <= 1]
        ahead = sum(1 for t in raws if t < 0)
        never = sum(1 for t in raws if t > 1)
        med = statistics.median(finite) if finite else None
        lo = min(finite) if finite else None
        hi = max(finite) if finite else None
        out.append(
            f"| {a} | {len(finite)} | {_pct(med)} | {_pct(lo)} | {_pct(hi)} | {ahead} | {never} |"
        )
    return "\n".join(out)


def build_report(ds: Dataset) -> str:
    rows = compare(ds)
    moves = [r for r in rows if r.best_origin != ds.incumbent]
    flips = [r for r in rows if r.flip]
    base_t = ds.tariffs[ds.incumbent].qualifying
    total_saving = sum(r.annual_saving for r in moves)
    by_dest: dict[str, list[CompareRow]] = {}
    for r in moves:
        by_dest.setdefault(r.best_origin, []).append(r)
    descr = {s.sku_id: s.description for s in ds.skus}

    out = [
        "# Landed-cost report",
        "",
        f"Incumbent: {ds.incumbent}, additional tariff {base_t:.0%} in the base scenario. "
        f"Carrying rate {ds.carrying_rate:.0%} a year, cycle service level {ds.service_level:.0%}.",
        "",
        "## Recommended moves",
        "",
        f"{len(moves)} of {len(rows)} SKUs have a lower total cost outside {ds.incumbent}; "
        f"moving them saves ${total_saving:,.0f} a year at the base tariff.",
        "",
        "| Destination | SKUs | Annual saving |",
        "|---|---|---|",
    ]
    for dest, rs in sorted(by_dest.items()):
        out.append(f"| {dest} | {len(rs)} | ${sum(r.annual_saving for r in rs):,.0f} |")
    stay = len(rows) - len(moves)
    out += ["", f"{stay} SKUs stay with {ds.incumbent}.", "", "### Largest savings", ""]
    out.append(compare_table(ds, rows, limit=10))
    out += ["", "## Break-even distribution", ""]
    out.append(
        f"Break-even is the {ds.incumbent} additional tariff at which each alternative ties on "
        "total cost; above it the move pays off. Outside 0-100% the alternative is ahead at "
        "every tariff or at none."
    )
    out += ["", breakeven_summary(ds), "", "## Scenario sweep", ""]
    out += ["SKUs won by each origin as the incumbent's tariff changes:", "", scenario_table(ds)]
    out += ["", "## Landed-cost flips", ""]
    if flips:
        out.append(
            "Cheapest on price + freight + duty + port is not the incumbent, but the incumbent "
            "has the lowest total cost once pipeline and safety stock are counted."
        )
        out += ["", "| SKU | Description | Cheapest on landed cost | Landed gap | Total-cost gap |"]
        out.append("|---|---|---|---|---|")
        for r in flips:
            inc = ds.incumbent
            pick = r.price_pick
            out.append(
                f"| {r.sku_id} | {descr[r.sku_id]} | {pick} "
                f"| {r.landed[pick] / r.landed[inc] - 1:+.2%} "
                f"| {r.total[pick] / r.total[inc] - 1:+.2%} |"
            )
    else:
        out.append("No SKU flips.")
    return "\n".join(out) + "\n"
