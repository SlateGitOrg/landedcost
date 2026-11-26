"""Build ``landedcost.xlsx``: inputs as values, every derived number as a live formula."""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation

from landedcost import layout as L
from landedcost.data import Dataset, Origin, Sku, Tariff
from landedcost.scenario import SCENARIO_STEPS

MONEY = '"$"#,##0.0000'
MONEY2 = '"$"#,##0.00'
PCT = "0.0%"
UNITS = "#,##0.0"
INT = "#,##0"

HEADER_FONT = Font(bold=True, color="FFFFFF")
HEADER_FILL = PatternFill("solid", fgColor="1F3864")
INPUT_FONT = Font(color="0000FF")
CAPTION_FILL = PatternFill("solid", fgColor="D9E1F2")

CALC_FORMATS = {
    "annual_demand": INT,
    "weekly_demand_sd": UNITS,
    "unit_cube": "0.0000",
    "order_qty": INT,
    "fob_local": "#,##0.000",
    "fx": "0.0000",
    "customs_value": MONEY,
    "freight": MONEY,
    "base_duty": PCT,
    "additional_tariff": PCT,
    "duty": MONEY,
    "port": MONEY,
    "landed": MONEY,
    "transit_days_mean": "0.0",
    "transit_days_sd": "0.0",
    "pipeline": MONEY,
    "z": "0.0000",
    "safety_stock_units": UNITS,
    "safety_stock": MONEY,
    "cycle": MONEY,
    "total": MONEY,
    "tariff_slope": MONEY,
}


def _abs(sheet: str, col: str, first: int, last: int) -> str:
    return f"{sheet}!${col}${first}:${col}${last}"


class _Ranges:
    """Absolute ranges on the input sheets, for INDEX/MATCH lookups."""

    def __init__(self, ds: Dataset) -> None:
        n_sku, n_org = len(ds.skus), len(ds.origins)
        self.n_sku, self.n_org = n_sku, n_org
        self.sku_last = n_sku + 1
        self.org_last = n_org + 1
        self.quote_last = n_sku * n_org + 1
        self.duty_last = len(ds.base_duty) + 1
        self.fx_last = len(ds.fx) + 1

    def sku(self, name: str) -> str:
        col = get_column_letter(L.SKU_COLUMNS.index(name) + 1)
        return _abs(L.SKU_SHEET, col, 2, self.sku_last)

    def origin(self, name: str) -> str:
        col = get_column_letter(L.ORIGIN_COLUMNS.index(name) + 1)
        return _abs(L.ORIGIN_SHEET, col, 2, self.org_last)

    def quote(self, col: str) -> str:
        return _abs(L.QUOTES_SHEET, col, 2, self.quote_last)

    def duty(self, col: str) -> str:
        return _abs(L.TARIFF_SHEET, col, 2, self.duty_last)

    def tariff(self, col: str) -> str:
        return _abs(L.TARIFF_SHEET, col, 2, self.org_last)

    def fx(self, col: str) -> str:
        return _abs(L.FX_SHEET, col, 2, self.fx_last)


def _lookup(result: str, key_range: str, key: str) -> str:
    return f"INDEX({result},MATCH({key},{key_range},0))"


def calc_formula(name: str, r: int, rg: _Ranges) -> str:
    """Formula text (with leading '=') for one Calc cell in row ``r``."""
    c = {n: f"${L.calc_letter(n)}{r}" for n in L.CALC_COLUMNS}

    def sku_attr(attr: str) -> str:
        return _lookup(rg.sku(attr), rg.sku("sku_id"), c["sku_id"])

    def origin_attr(attr: str) -> str:
        return _lookup(rg.origin(attr), rg.origin("origin"), c["origin"])

    def tariff_col(col: str) -> str:
        return _lookup(rg.tariff(col), rg.tariff("D"), c["origin"])

    formulas = {
        "key": f'={c["sku_id"]}&"|"&{c["origin"]}',
        "annual_demand": "=" + sku_attr("annual_demand"),
        "weekly_demand_sd": "=" + sku_attr("weekly_demand_sd"),
        "unit_cube": "=" + sku_attr("unit_cube"),
        "order_qty": "=" + sku_attr("order_qty"),
        "usmca_qualifying": "=" + sku_attr("usmca_qualifying"),
        "fob_local": "=" + _lookup(rg.quote("D"), rg.quote("A"), c["key"]),
        "fx": "=" + _lookup(rg.fx("B"), rg.fx("A"), origin_attr("currency")),
        "customs_value": f"={c['fob_local']}*{c['fx']}",
        "freight": (
            f"={origin_attr('container_cost')}/{origin_attr('usable_cube')}*{c['unit_cube']}"
        ),
        "base_duty": "=" + _lookup(rg.duty("B"), rg.duty("A"), sku_attr("hts_group")),
        "additional_tariff": (
            f"=IF({c['usmca_qualifying']}=1,{tariff_col('E')},{tariff_col('F')})"
        ),
        "duty": f"={c['customs_value']}*({c['base_duty']}+{c['additional_tariff']})",
        "port": "=" + origin_attr("port_per_unit"),
        "landed": f"={c['customs_value']}+{c['freight']}+{c['duty']}+{c['port']}",
        "transit_days_mean": "=" + origin_attr("transit_days_mean"),
        "transit_days_sd": "=" + origin_attr("transit_days_sd"),
        "pipeline": f"={c['transit_days_mean']}/365*{c['landed']}*Carrying_Rate",
        "z": "=_xlfn.NORM.S.INV(Service_Level)",
        "safety_stock_units": (
            f"={c['z']}*SQRT({c['transit_days_mean']}/7*{c['weekly_demand_sd']}^2"
            f"+({c['annual_demand']}/52)^2*({c['transit_days_sd']}/7)^2)"
        ),
        "safety_stock": (
            f"={c['safety_stock_units']}*{c['landed']}*Carrying_Rate/{c['annual_demand']}"
        ),
        "cycle": f"={c['order_qty']}/2*{c['landed']}*Carrying_Rate/{c['annual_demand']}",
        "total": f"={c['landed']}+{c['pipeline']}+{c['safety_stock']}+{c['cycle']}",
        "tariff_slope": f"={c['customs_value']}*{c['total']}/{c['landed']}",
    }
    return formulas[name]


def compare_formula(name: str, r: int, ds: Dataset, rg: _Ranges) -> str:
    """Formula text for one Compare cell in row ``r``."""
    origins = [o.name for o in ds.origins]
    n = len(origins)
    last = L.calc_last_row(ds)
    cl = L.compare_letter
    name_row = L.COMPARE_NAME_ROW

    def calc_rng(col: str) -> str:
        return _abs(L.CALC_SHEET, L.calc_letter(col), L.CALC_FIRST_ROW, last)

    def row_rng(first: str, count: int) -> str:
        start = L.compare_letter(origins, first)
        end = get_column_letter(L.compare_columns(origins).index(first) + count)
        return f"${start}{r}:${end}{r}"

    def names_rng(first: str, count: int) -> str:
        start = L.compare_letter(origins, first)
        end = get_column_letter(L.compare_columns(origins).index(first) + count)
        return f"${start}${name_row}:${end}${name_row}"

    sku = f"$A{r}"
    incumbent = f"${cl(origins, 'total:' + origins[0])}${name_row}"
    inc_key = f'{sku}&"|"&{incumbent}'
    totals = row_rng(f"total:{origins[0]}", n)
    landed = row_rng(f"landed:{origins[0]}", n)
    me = {k: f"${cl(origins, k)}{r}" for k in L.compare_columns(origins) if k != "sku_id"}

    if name.startswith(("total:", "landed:")):
        kind, origin = name.split(":")
        col = cl(origins, name)
        calc_col = "total" if kind == "total" else "landed"
        key = f'{sku}&"|"&{col}${name_row}'
        return "=" + _lookup(calc_rng(calc_col), calc_rng("key"), key)
    if name == "best_origin":
        return f"=INDEX({names_rng(f'total:{origins[0]}', n)},MATCH(MIN({totals}),{totals},0))"
    if name == "best_total":
        return f"=MIN({totals})"
    if name == "saving_per_unit":
        return f"={me[f'total:{origins[0]}']}-{me['best_total']}"
    if name == "annual_saving":
        demand = _lookup(rg.sku("annual_demand"), rg.sku("sku_id"), sku)
        return f"={me['saving_per_unit']}*{demand}"
    if name == "price_pick":
        return f"=INDEX({names_rng(f'landed:{origins[0]}', n)},MATCH(MIN({landed}),{landed},0))"
    if name == "flip":
        return f"=IF(AND({me['price_pick']}<>{incumbent},{me['best_origin']}={incumbent}),1,0)"
    if name == "incumbent_tariff":
        return "=" + _lookup(calc_rng("additional_tariff"), calc_rng("key"), inc_key)
    if name == "slope":
        return "=" + _lookup(calc_rng("tariff_slope"), calc_rng("key"), inc_key)
    if name == "intercept":
        return f"={me[f'total:{origins[0]}']}-{me['slope']}*{me['incumbent_tariff']}"
    if name.startswith("raw_breakeven:"):
        alt = name.split(":")[1]
        return f"=({me['total:' + alt]}-{me['intercept']})/{me['slope']}"
    if name.startswith("breakeven:"):
        raw = me["raw_breakeven:" + name.split(":")[1]]
        return f'=IF(OR({raw}<0,{raw}>1),"",{raw})'
    raise KeyError(name)


def _style_header(ws, row: int, ncols: int) -> None:
    for col in range(1, ncols + 1):
        cell = ws.cell(row=row, column=col)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(wrap_text=True, vertical="center")


def _widths(ws, widths: dict[int, float] | float, ncols: int) -> None:
    for i in range(1, ncols + 1):
        w = widths if isinstance(widths, (int, float)) else widths.get(i, 14)
        ws.column_dimensions[get_column_letter(i)].width = w


def _write_inputs(wb: Workbook, ds: Dataset) -> None:
    ws = wb.create_sheet(L.SKU_SHEET)
    ws.append(L.SKU_COLUMNS)
    for s in ds.skus:
        ws.append(
            [
                s.sku_id,
                s.description,
                s.category,
                s.hts_group,
                int(s.usmca_qualifying),
                s.annual_demand,
                s.weekly_demand_sd,
                s.unit_cube,
                s.order_qty,
            ]
        )
    _style_header(ws, 1, len(L.SKU_COLUMNS))
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.font = INPUT_FONT
        row[5].number_format = INT
        row[6].number_format = UNITS
        row[7].number_format = "0.0000"
        row[8].number_format = INT
    ws.freeze_panes = "B2"
    _widths(ws, {1: 10, 2: 36, 3: 14, 4: 11}, len(L.SKU_COLUMNS))
    dv = DataValidation(type="list", formula1='"0,1"', allow_blank=False)
    dv.error = "USMCA qualifying must be 0 or 1"
    ws.add_data_validation(dv)
    dv.add(f"E2:E{len(ds.skus) + 1}")

    ws = wb.create_sheet(L.ORIGIN_SHEET)
    ws.append(L.ORIGIN_COLUMNS)
    for o in ds.origins:
        ws.append(
            [
                o.name,
                o.currency,
                o.mode,
                o.transit_days_mean,
                o.transit_days_sd,
                o.container_cost,
                o.usable_cube,
                o.port_per_unit,
            ]
        )
    _style_header(ws, 1, len(L.ORIGIN_COLUMNS))
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.font = INPUT_FONT
        row[5].number_format = MONEY2
        row[7].number_format = MONEY2
    ws.freeze_panes = "B2"
    _widths(ws, 16, len(L.ORIGIN_COLUMNS))

    ws = wb.create_sheet(L.QUOTES_SHEET)
    ws.append(["key", "sku_id", "origin", "fob_local"])
    for s in ds.skus:
        for o in ds.origins:
            ws.append([f"{s.sku_id}|{o.name}", s.sku_id, o.name, ds.quotes[(s.sku_id, o.name)]])
    _style_header(ws, 1, 4)
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.font = INPUT_FONT
        row[3].number_format = "#,##0.000"
    ws.freeze_panes = "B2"
    _widths(ws, {1: 18, 2: 10, 3: 10, 4: 12}, 4)

    ws = wb.create_sheet(L.TARIFF_SHEET)
    ws.append(
        [
            "hts_group",
            "base_duty",
            None,
            "origin",
            "additional_qualifying",
            "additional_non_qualifying",
        ]
    )
    rows = max(len(ds.base_duty), len(ds.tariffs))
    duties = list(ds.base_duty.items())
    tariffs = list(ds.tariffs.values())
    for i in range(rows):
        d = duties[i] if i < len(duties) else (None, None)
        t = tariffs[i] if i < len(tariffs) else None
        ws.append(
            [
                d[0],
                d[1],
                None,
                t.origin if t else None,
                t.qualifying if t else None,
                t.non_qualifying if t else None,
            ]
        )
    _style_header(ws, 1, 2)
    _style_header(ws, 1, 6)
    ws.cell(row=1, column=3).fill = PatternFill()
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.font = INPUT_FONT
        row[1].number_format = PCT
        row[4].number_format = PCT
        row[5].number_format = PCT
    _widths(ws, {1: 11, 2: 11, 3: 3, 4: 12, 5: 22, 6: 26}, 6)
    dv = DataValidation(type="decimal", operator="between", formula1="0", formula2="1")
    dv.error = "Tariff and duty rates are fractions between 0 and 1"
    ws.add_data_validation(dv)
    dv.add(f"B2:B{len(duties) + 1}")
    dv.add(f"E2:F{len(tariffs) + 1}")

    ws = wb.create_sheet(L.FX_SHEET)
    ws.append(["currency", "usd_per_unit"])
    for cur, rate in ds.fx.items():
        ws.append([cur, rate])
    _style_header(ws, 1, 2)
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.font = INPUT_FONT
        row[1].number_format = "0.0000"
    _widths(ws, 14, 2)

    ws = wb.create_sheet(L.PARAMS_SHEET)
    ws.append(["parameter", "value", "defined name"])
    ws.append(["Carrying rate (per year)", ds.carrying_rate, "Carrying_Rate"])
    ws.append(["Cycle service level", ds.service_level, "Service_Level"])
    _style_header(ws, 1, 3)
    for r in (2, 3):
        ws.cell(row=r, column=2).font = INPUT_FONT
        ws.cell(row=r, column=2).number_format = PCT
    _widths(ws, {1: 28, 2: 10, 3: 16}, 3)
    wb.defined_names["Carrying_Rate"] = DefinedName("Carrying_Rate", attr_text="Params!$B$2")
    wb.defined_names["Service_Level"] = DefinedName("Service_Level", attr_text="Params!$B$3")
    dv = DataValidation(type="decimal", operator="between", formula1="0", formula2="1")
    dv.error = "Enter a fraction between 0 and 1"
    ws.add_data_validation(dv)
    dv.add("B2")
    dv2 = DataValidation(type="decimal", operator="between", formula1="0.5", formula2="0.999")
    dv2.error = "Service level must be between 50% and 99.9%"
    ws.add_data_validation(dv2)
    dv2.add("B3")


def _write_calc(wb: Workbook, ds: Dataset, rg: _Ranges) -> None:
    ws = wb.create_sheet(L.CALC_SHEET)
    ws.append([L.CALC_HEADERS[n] for n in L.CALC_COLUMNS])
    _style_header(ws, 1, len(L.CALC_COLUMNS))
    ws.row_dimensions[1].height = 32
    r = L.CALC_FIRST_ROW
    for s in ds.skus:
        for o in ds.origins:
            for idx, name in enumerate(L.CALC_COLUMNS, start=1):
                cell = ws.cell(row=r, column=idx)
                if name == "sku_id":
                    cell.value = s.sku_id
                elif name == "origin":
                    cell.value = o.name
                else:
                    cell.value = calc_formula(name, r, rg)
                    if name in CALC_FORMATS:
                        cell.number_format = CALC_FORMATS[name]
            r += 1
    ws.freeze_panes = "D2"
    _widths(ws, {1: 16, 2: 10, 3: 10}, len(L.CALC_COLUMNS))


def _write_compare(wb: Workbook, ds: Dataset, rg: _Ranges) -> None:
    origins = [o.name for o in ds.origins]
    cols = L.compare_columns(origins)
    ws = wb.create_sheet(L.COMPARE_SHEET)
    inc = origins[0]
    captions = {
        "sku_id": "SKU",
        "best_origin": "Best origin (total cost)",
        "best_total": "Best total / unit",
        "saving_per_unit": f"Saving / unit vs {inc}",
        "annual_saving": f"Annual saving vs {inc}",
        "price_pick": "Cheapest on landed cost",
        "flip": "Landed-cost flip",
        "incumbent_tariff": f"{inc} additional tariff",
        "slope": "Total cost per tariff point",
        "intercept": "Total cost at 0% tariff",
    }
    for idx, name in enumerate(cols, start=1):
        kind, _, origin = name.partition(":")
        if origin:
            caption = {
                "total": "Total cost / unit",
                "landed": "Landed cost / unit",
                "raw_breakeven": f"Raw break-even {inc} tariff",
                "breakeven": f"Break-even {inc} tariff",
            }[kind]
            ws.cell(row=1, column=idx, value=caption)
            ws.cell(row=2, column=idx, value=origin)
        else:
            ws.cell(row=1, column=idx, value=captions[name])
            ws.cell(row=2, column=idx, value=None)
    _style_header(ws, 1, len(cols))
    _style_header(ws, 2, len(cols))
    ws.row_dimensions[1].height = 32
    formats = {
        "best_total": MONEY,
        "saving_per_unit": MONEY,
        "annual_saving": '"$"#,##0',
        "incumbent_tariff": PCT,
        "slope": MONEY,
        "intercept": MONEY,
    }
    for r, s in enumerate(ds.skus, start=L.COMPARE_FIRST_ROW):
        ws.cell(row=r, column=1, value=s.sku_id)
        for idx, name in enumerate(cols, start=1):
            if name == "sku_id":
                continue
            cell = ws.cell(row=r, column=idx, value=compare_formula(name, r, ds, rg))
            kind = name.partition(":")[0]
            if kind in ("total", "landed"):
                cell.number_format = MONEY
            elif kind in ("breakeven", "raw_breakeven"):
                cell.number_format = PCT
            elif name in formats:
                cell.number_format = formats[name]
    last = L.compare_last_row(ds)
    flip_col = L.compare_letter(origins, "flip")
    ws.conditional_formatting.add(
        f"{flip_col}{L.COMPARE_FIRST_ROW}:{flip_col}{last}",
        CellIsRule(operator="equal", formula=["1"], fill=PatternFill("solid", bgColor="FFE699")),
    )
    ws.freeze_panes = "B3"
    _widths(ws, {1: 10}, len(cols))


def _write_scenario(wb: Workbook, ds: Dataset) -> dict[str, int]:
    """Scenario sheet; returns its layout (see ``layout.scenario_layout``)."""
    origins = [o.name for o in ds.origins]
    n = len(origins)
    inc = origins[0]
    steps = SCENARIO_STEPS
    first_col, last_col = 2, 1 + len(steps) + 1  # steps plus the what-if column
    ws = wb.create_sheet(L.SCENARIO_SHEET)
    ws["A1"] = f"SKUs won by each origin as the {inc} additional tariff changes"
    ws["A1"].font = Font(bold=True, size=13)
    ws["A3"] = f"What-if {inc} additional tariff"
    ws["B3"] = ds.tariffs[inc].qualifying
    ws["B3"].number_format = PCT
    ws["B3"].font = INPUT_FONT
    wb.defined_names["Scenario_Tariff"] = DefinedName("Scenario_Tariff", attr_text="Scenario!$B$3")
    dv = DataValidation(type="decimal", operator="between", formula1="0", formula2="1")
    dv.error = "Enter a tariff between 0% and 100%"
    dv.prompt = "Type a tariff between 0% and 100%; the last column below follows it."
    ws.add_data_validation(dv)
    dv.add("B3")

    lay = L.scenario_layout(n, len(ds.skus), len(steps))
    head_row, first_win = lay["head_row"], lay["first_win"]
    ws.cell(row=head_row, column=1, value="Origin / tariff")
    for i, t in enumerate(steps):
        c = ws.cell(row=head_row, column=first_col + i, value=t)
        c.number_format = "0%"
    ws.cell(row=head_row, column=last_col, value="=Scenario_Tariff").number_format = "0%"
    ws.cell(row=head_row - 1, column=last_col, value="What-if")
    _style_header(ws, head_row, last_col)

    grid_head, grid_first = lay["grid_head"], lay["grid_first"]
    grid_last = grid_first + len(ds.skus) - 1
    cmp_cols = {k: L.compare_letter(origins, k) for k in L.compare_columns(origins)}
    alt_first = f"total:{origins[1]}"
    alt_start = cmp_cols[alt_first]
    alt_end = cmp_cols[f"total:{origins[-1]}"]
    names_rng = (
        f"{L.COMPARE_SHEET}!${alt_start}${L.COMPARE_NAME_ROW}:${alt_end}${L.COMPARE_NAME_ROW}"
    )
    inc_name = f"{L.COMPARE_SHEET}!${cmp_cols['total:' + inc]}${L.COMPARE_NAME_ROW}"

    for k, origin in enumerate(origins):
        r = first_win + k
        ws.cell(row=r, column=1, value=origin)
        for col in range(first_col, last_col + 1):
            letter = get_column_letter(col)
            ws.cell(
                row=r,
                column=col,
                value=f"=SUMPRODUCT(({letter}${grid_first}:{letter}${grid_last}=$A{r})*1)",
            ).number_format = INT
    total_row = first_win + n
    ws.cell(row=total_row, column=1, value="Total SKUs")
    for col in range(first_col, last_col + 1):
        letter = get_column_letter(col)
        ws.cell(
            row=total_row, column=col, value=f"=SUM({letter}{first_win}:{letter}{total_row - 1})"
        ).number_format = INT
    for col in range(1, last_col + 1):
        ws.cell(row=total_row, column=col).font = Font(bold=True)

    ws.cell(row=grid_head - 1, column=1, value="Winning origin per SKU (helper grid)").font = Font(
        bold=True
    )
    ws.cell(row=grid_head, column=1, value="SKU")
    for col in range(first_col, last_col + 1):
        letter = get_column_letter(col)
        ws.cell(row=grid_head, column=col, value=f"={letter}${head_row}").number_format = "0%"
    _style_header(ws, grid_head, last_col)
    for k in range(len(ds.skus)):
        r = grid_first + k
        rc = L.COMPARE_FIRST_ROW + k
        ws.cell(row=r, column=1, value=f"={L.COMPARE_SHEET}!$A{rc}")
        alts = f"{L.COMPARE_SHEET}!${alt_start}{rc}:${alt_end}{rc}"
        a = f"{L.COMPARE_SHEET}!${cmp_cols['intercept']}{rc}"
        b = f"{L.COMPARE_SHEET}!${cmp_cols['slope']}{rc}"
        for col in range(first_col, last_col + 1):
            letter = get_column_letter(col)
            line = f"{a}+{b}*{letter}${head_row}"
            ws.cell(
                row=r,
                column=col,
                value=(
                    f"=IF({line}<=MIN({alts}),{inc_name},"
                    f"INDEX({names_rng},MATCH(MIN({alts}),{alts},0)))"
                ),
            )
    ws.freeze_panes = "B6"
    _widths(ws, {1: 30}, last_col)
    for col in range(2, last_col + 1):
        ws.column_dimensions[get_column_letter(col)].width = 10
    return lay


NOTES = [
    "landedcost: assumptions",
    "",
    "All data is synthetic. Rates, prices and freight are illustrative, not a statement of "
    "any real tariff schedule or quote.",
    "",
    "Landed unit cost = FOB x FX + freight + duty + port and drayage. Duty = customs value x "
    "(base duty + additional tariff); customs value is FOB converted to USD.",
    "Freight per unit = container (or truckload) cost / usable cube x unit cube.",
    "Pipeline carrying = transit days / 365 x landed x carrying rate: goods are owned from "
    "FOB until receipt.",
    "Safety stock = z x sqrt(L x sd_d^2 + d^2 x sd_L^2), with d = annual demand / 52 and "
    "L, sd_L = days / 7. z is NORM.S.INV of the cycle service level.",
    "Safety-stock carrying = safety stock x landed x carrying rate / annual demand.",
    "Cycle-stock carrying = order quantity / 2 x landed x carrying rate / annual demand.",
    "Total cost = landed + pipeline + safety-stock + cycle-stock carrying.",
    "",
    "Simplifications: safety stock targets a cycle service level (the chance of no stockout "
    "per cycle), not a fill rate, and ignores the size of a stockout. Demand and lead time "
    "are independent and normal.",
    "Order quantities and carrying rate are the same whichever origin supplies the SKU.",
    "",
    "Break-even tariff: every carrying charge is proportional to landed cost, so total cost "
    "is linear in the incumbent's additional tariff t: TCO = a + b x t. An alternative with "
    "total cost TCO_alt ties at t* = (TCO_alt - a) / b. The cell is blank when t* is outside "
    "0-100%.",
    "Landed-cost flip: the origin that is cheapest on landed cost alone is not the incumbent, "
    "yet the incumbent has the lowest total cost.",
    "",
    "Scenario sheet: the helper grid names the winning origin per SKU at each incumbent "
    "tariff; the counts use SUMPRODUCT. Change the what-if cell (B3) to try any tariff.",
    "Inputs are blue. Every number on Calc and Compare is a formula; run 'landedcost verify' "
    "to recalculate the file and check it against the Python reference.",
]


def _write_notes(wb: Workbook) -> None:
    ws = wb.create_sheet(L.NOTES_SHEET)
    for i, line in enumerate(NOTES, start=1):
        c = ws.cell(row=i, column=1, value=line)
        c.alignment = Alignment(wrap_text=True, vertical="top")
    ws["A1"].font = Font(bold=True, size=13)
    ws.column_dimensions["A"].width = 120


def build_workbook(ds: Dataset, path: Path) -> Path:
    wb = Workbook()
    wb.remove(wb.active)
    rg = _Ranges(ds)
    _write_inputs(wb, ds)
    _write_calc(wb, ds, rg)
    _write_compare(wb, ds, rg)
    _write_scenario(wb, ds)
    _write_notes(wb)
    # Order sheets as documented.
    order = [
        L.SKU_SHEET,
        L.ORIGIN_SHEET,
        L.QUOTES_SHEET,
        L.TARIFF_SHEET,
        L.FX_SHEET,
        L.PARAMS_SHEET,
        L.CALC_SHEET,
        L.COMPARE_SHEET,
        L.SCENARIO_SHEET,
        L.NOTES_SHEET,
    ]
    wb._sheets = [wb[name] for name in order]
    wb.active = wb._sheets.index(wb[L.COMPARE_SHEET])
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def read_dataset(path: Path) -> Dataset:
    """Rebuild the input dataset from a saved workbook's input sheets (values only)."""
    wb = load_workbook(path, data_only=False)

    def table(name: str) -> list[tuple]:
        return [
            row for row in wb[name].iter_rows(min_row=2, values_only=True) if row[0] is not None
        ]

    skus = tuple(
        Sku(
            r[0],
            r[1],
            r[2],
            str(r[3]),
            bool(r[4]),
            float(r[5]),
            float(r[6]),
            float(r[7]),
            float(r[8]),
        )
        for r in table(L.SKU_SHEET)
    )
    origins = tuple(
        Origin(r[0], r[1], r[2], float(r[3]), float(r[4]), float(r[5]), float(r[6]), float(r[7]))
        for r in table(L.ORIGIN_SHEET)
    )
    quotes = {(r[1], r[2]): float(r[3]) for r in table(L.QUOTES_SHEET)}
    ws = wb[L.TARIFF_SHEET]
    base_duty: dict[str, float] = {}
    tariffs: dict[str, Tariff] = {}
    for row in ws.iter_rows(min_row=2, values_only=True):
        if row[0] is not None:
            base_duty[str(row[0])] = float(row[1])
        if row[3] is not None:
            tariffs[row[3]] = Tariff(row[3], float(row[4]), float(row[5]))
    fx = {r[0]: float(r[1]) for r in table(L.FX_SHEET)}
    params = wb[L.PARAMS_SHEET]
    return Dataset(
        skus=skus,
        origins=origins,
        quotes=quotes,
        base_duty=base_duty,
        tariffs=tariffs,
        fx=fx,
        carrying_rate=float(params["B2"].value),
        service_level=float(params["B3"].value),
    )
