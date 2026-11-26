"""Recalculate the saved workbook outside Excel and compare it to the Python reference."""

from __future__ import annotations

import contextlib
import io
import math
import warnings
from dataclasses import dataclass
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from landedcost import layout as L
from landedcost.breakeven import breakeven, raw_breakeven, tariff_line
from landedcost.data import Dataset
from landedcost.model import CalcRow, CompareRow, compare, compute_all, z_score
from landedcost.scenario import SCENARIO_STEPS, win_counts
from landedcost.workbook import read_dataset

REL_TOL = 1e-9
ABS_TOL = 1e-12  # only matters for values that are exactly or nearly zero


class VerifyError(Exception):
    """The workbook disagrees with the reference; the message names the first bad cell."""


@dataclass(frozen=True)
class VerifyReport:
    calc_rows: int
    compare_rows: int
    scenario_columns: int
    cells_checked: int


def calc_reference(ds: Dataset, row: CalcRow, sku_index: dict[str, int]) -> dict[str, object]:
    sku = ds.skus[sku_index[row.sku_id]]
    o = ds.origin(row.origin)
    c = row.cost
    return {
        "key": f"{row.sku_id}|{row.origin}",
        "annual_demand": sku.annual_demand,
        "weekly_demand_sd": sku.weekly_demand_sd,
        "unit_cube": sku.unit_cube,
        "order_qty": sku.order_qty,
        "usmca_qualifying": int(sku.usmca_qualifying),
        "fob_local": ds.quotes[(row.sku_id, row.origin)],
        "fx": ds.fx[o.currency],
        "customs_value": c.customs_value,
        "freight": c.freight,
        "base_duty": ds.base_duty[sku.hts_group],
        "additional_tariff": row.additional_tariff,
        "duty": c.duty,
        "port": c.port,
        "landed": c.landed,
        "transit_days_mean": o.transit_days_mean,
        "transit_days_sd": o.transit_days_sd,
        "pipeline": c.pipeline,
        "z": z_score(ds.service_level),
        "safety_stock_units": c.safety_stock_units,
        "safety_stock": c.safety_stock,
        "cycle": c.cycle,
        "total": c.total,
        "tariff_slope": c.tariff_slope,
    }


def compare_reference(ds: Dataset, row: CompareRow) -> dict[str, object]:
    sku = next(s for s in ds.skus if s.sku_id == row.sku_id)
    origins = [o.name for o in ds.origins]
    line = tariff_line(ds, sku, ds.incumbent)
    ref: dict[str, object] = {}
    for o in origins:
        ref[f"total:{o}"] = row.total[o]
        ref[f"landed:{o}"] = row.landed[o]
    ref.update(
        best_origin=row.best_origin,
        best_total=row.best_total,
        saving_per_unit=row.saving_per_unit,
        annual_saving=row.annual_saving,
        price_pick=row.price_pick,
        flip=int(row.flip),
        incumbent_tariff=ds.additional_tariff(sku, ds.incumbent),
        slope=line.slope,
        intercept=line.intercept,
    )
    for o in origins[1:]:
        ref[f"raw_breakeven:{o}"] = raw_breakeven(ds, sku, o)
        ref[f"breakeven:{o}"] = breakeven(ds, sku, o)
    return ref


def _close(expected: object, actual: object) -> bool:
    if expected is None:
        return actual is None or actual == ""
    if isinstance(expected, str):
        return actual == expected
    if actual is None or isinstance(actual, str):
        return False
    return math.isclose(float(expected), float(actual), rel_tol=REL_TOL, abs_tol=ABS_TOL)


def _check_formulas(path: Path, ds: Dataset) -> int:
    """Every derived cell on Calc and Compare must still hold a formula."""
    wb = load_workbook(path, data_only=False)
    origins = [o.name for o in ds.origins]
    checked = 0
    calc = wb[L.CALC_SHEET]
    for r in range(L.CALC_FIRST_ROW, L.calc_last_row(ds) + 1):
        for idx, name in enumerate(L.CALC_COLUMNS, start=1):
            if name in L.CALC_VALUE_COLUMNS:
                continue
            v = calc.cell(row=r, column=idx).value
            if not (isinstance(v, str) and v.startswith("=")):
                ref = f"{L.CALC_SHEET}!{get_column_letter(idx)}{r}"
                raise VerifyError(f"{ref} ({L.CALC_HEADERS[name]}) is not a formula")
            checked += 1
    cmp_ws = wb[L.COMPARE_SHEET]
    cols = L.compare_columns(origins)
    for r in range(L.COMPARE_FIRST_ROW, L.compare_last_row(ds) + 1):
        for idx, name in enumerate(cols, start=1):
            if name == "sku_id":
                continue
            v = cmp_ws.cell(row=r, column=idx).value
            if not (isinstance(v, str) and v.startswith("=")):
                raise VerifyError(f"{L.COMPARE_SHEET}!{get_column_letter(idx)}{r} is not a formula")
            checked += 1
    return checked


def _recalculate(path: Path):
    # The formulas package prints a progress bar and, on some Python versions, emits syntax
    # warnings while compiling its own modules; neither is about the workbook.
    with warnings.catch_warnings(), contextlib.redirect_stderr(io.StringIO()):
        warnings.simplefilter("ignore")
        import formulas

        model = formulas.ExcelModel().loads(str(path)).finish()
        solution = model.calculate()
    book = path.name

    def value(sheet: str, ref: str) -> object:
        cell = solution.get(f"'[{book}]{sheet.upper()}'!{ref}")
        if cell is None:
            return None
        v = cell.value[0, 0]
        return None if hasattr(v, "dtype") and str(v) == "empty" else v

    return value


def verify(path: Path) -> VerifyReport:
    """Raise ``VerifyError`` naming the first mismatched cell, else return a report."""
    path = Path(path)
    ds = read_dataset(path)
    checked = _check_formulas(path, ds)
    value = _recalculate(path)
    origins = [o.name for o in ds.origins]

    calc_rows = compute_all(ds)
    sku_index = {s.sku_id: i for i, s in enumerate(ds.skus)}
    for r, row in enumerate(calc_rows, start=L.CALC_FIRST_ROW):
        ref = calc_reference(ds, row, sku_index)
        for idx, name in enumerate(L.CALC_COLUMNS, start=1):
            if name in L.CALC_VALUE_COLUMNS:
                continue
            cell = f"{get_column_letter(idx)}{r}"
            actual = value(L.CALC_SHEET, cell)
            if not _close(ref[name], actual):
                raise VerifyError(
                    f"{L.CALC_SHEET}!{cell} ({L.CALC_HEADERS[name]}, {row.sku_id} {row.origin}): "
                    f"workbook {actual!r}, reference {ref[name]!r}"
                )
            checked += 1

    cols = L.compare_columns(origins)
    for r, crow in enumerate(compare(ds, calc_rows), start=L.COMPARE_FIRST_ROW):
        ref = compare_reference(ds, crow)
        for idx, name in enumerate(cols, start=1):
            if name == "sku_id":
                continue
            cell = f"{get_column_letter(idx)}{r}"
            actual = value(L.COMPARE_SHEET, cell)
            if not _close(ref[name], actual):
                raise VerifyError(
                    f"{L.COMPARE_SHEET}!{cell} ({name}, {crow.sku_id}): "
                    f"workbook {actual!r}, reference {ref[name]!r}"
                )
            checked += 1

    lay = L.scenario_layout(len(origins), len(ds.skus), len(SCENARIO_STEPS))
    wb = load_workbook(path, data_only=False)
    what_if = wb[L.SCENARIO_SHEET]["B3"].value
    tariffs = [*SCENARIO_STEPS, float(what_if)]
    for i, t in enumerate(tariffs):
        counts = win_counts(ds, t)
        col = get_column_letter(lay["first_col"] + i)
        for k, origin in enumerate(origins):
            cell = f"{col}{lay['first_win'] + k}"
            actual = value(L.SCENARIO_SHEET, cell)
            if not _close(counts[origin], actual):
                raise VerifyError(
                    f"{L.SCENARIO_SHEET}!{cell} (SKUs won by {origin} at {t:.0%}): "
                    f"workbook {actual!r}, reference {counts[origin]!r}"
                )
            checked += 1
    return VerifyReport(len(calc_rows), len(ds.skus), len(tariffs), checked)
