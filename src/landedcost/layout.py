"""Sheet layout shared by the workbook builder and the verifier.

Column names are stable identifiers; letters are derived from their position so the builder
and the verifier cannot drift apart.
"""

from __future__ import annotations

from openpyxl.utils import get_column_letter

from landedcost.data import Dataset

# Sheet names
SKU_SHEET = "Inputs_SKU"
ORIGIN_SHEET = "Inputs_Origin"
QUOTES_SHEET = "Quotes"
TARIFF_SHEET = "Tariffs"
FX_SHEET = "FX"
PARAMS_SHEET = "Params"
CALC_SHEET = "Calc"
COMPARE_SHEET = "Compare"
SCENARIO_SHEET = "Scenario"
NOTES_SHEET = "Notes"

SKU_COLUMNS = [
    "sku_id",
    "description",
    "category",
    "hts_group",
    "usmca_qualifying",
    "annual_demand",
    "weekly_demand_sd",
    "unit_cube",
    "order_qty",
]
ORIGIN_COLUMNS = [
    "origin",
    "currency",
    "mode",
    "transit_days_mean",
    "transit_days_sd",
    "container_cost",
    "usable_cube",
    "port_per_unit",
]

# Calc: one row per SKU x origin. Formula columns are everything except sku_id and origin.
CALC_COLUMNS = [
    "key",
    "sku_id",
    "origin",
    "annual_demand",
    "weekly_demand_sd",
    "unit_cube",
    "order_qty",
    "usmca_qualifying",
    "fob_local",
    "fx",
    "customs_value",
    "freight",
    "base_duty",
    "additional_tariff",
    "duty",
    "port",
    "landed",
    "transit_days_mean",
    "transit_days_sd",
    "pipeline",
    "z",
    "safety_stock_units",
    "safety_stock",
    "cycle",
    "total",
    "tariff_slope",
]
CALC_VALUE_COLUMNS = ("sku_id", "origin")

CALC_HEADERS = {
    "key": "SKU|origin",
    "sku_id": "SKU",
    "origin": "Origin",
    "annual_demand": "Annual demand",
    "weekly_demand_sd": "Weekly demand SD",
    "unit_cube": "Unit cube (m3)",
    "order_qty": "Order qty",
    "usmca_qualifying": "USMCA qualifying",
    "fob_local": "FOB (local)",
    "fx": "FX (USD per local)",
    "customs_value": "Customs value",
    "freight": "Freight / unit",
    "base_duty": "Base duty",
    "additional_tariff": "Additional tariff",
    "duty": "Duty / unit",
    "port": "Port + drayage / unit",
    "landed": "Landed / unit",
    "transit_days_mean": "Transit days",
    "transit_days_sd": "Transit SD days",
    "pipeline": "Pipeline carrying / unit",
    "z": "z (service level)",
    "safety_stock_units": "Safety stock (units)",
    "safety_stock": "Safety-stock carrying / unit",
    "cycle": "Cycle-stock carrying / unit",
    "total": "Total cost / unit",
    "tariff_slope": "d total / d tariff",
}

CALC_FIRST_ROW = 2
COMPARE_FIRST_ROW = 3  # two header rows
COMPARE_NAME_ROW = 2


def calc_letter(name: str) -> str:
    return get_column_letter(CALC_COLUMNS.index(name) + 1)


def compare_columns(origins: list[str]) -> list[str]:
    alts = origins[1:]
    return (
        ["sku_id"]
        + [f"total:{o}" for o in origins]
        + [f"landed:{o}" for o in origins]
        + [
            "best_origin",
            "best_total",
            "saving_per_unit",
            "annual_saving",
            "price_pick",
            "flip",
            "incumbent_tariff",
            "slope",
            "intercept",
        ]
        + [f"raw_breakeven:{o}" for o in alts]
        + [f"breakeven:{o}" for o in alts]
    )


def compare_letter(origins: list[str], name: str) -> str:
    return get_column_letter(compare_columns(origins).index(name) + 1)


def calc_last_row(ds: Dataset) -> int:
    return CALC_FIRST_ROW + len(ds.skus) * len(ds.origins) - 1


def compare_last_row(ds: Dataset) -> int:
    return COMPARE_FIRST_ROW + len(ds.skus) - 1


def scenario_layout(n_origins: int, n_skus: int, n_steps: int) -> dict[str, int]:
    """Row and column positions on the Scenario sheet (1-based)."""
    head_row, first_win = 5, 6
    grid_head = first_win + n_origins + 3
    return {
        "head_row": head_row,
        "first_win": first_win,
        "total_row": first_win + n_origins,
        "grid_head": grid_head,
        "grid_first": grid_head + 1,
        "grid_last": grid_head + n_skus,
        "first_col": 2,
        "last_col": 2 + n_steps,  # the steps, then the what-if column
    }
