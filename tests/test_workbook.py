from __future__ import annotations

import re

import pytest
from openpyxl import load_workbook

from landedcost import layout as L
from landedcost.model import compare
from landedcost.scenario import SCENARIO_STEPS
from landedcost.verify import VerifyError, _recalculate, verify
from landedcost.workbook import read_dataset

ALLOWED_LITERALS = {"0", "1", "2", "7", "52", "100", "365"}
CELL_REF = re.compile(r"\$?[A-Z]{1,3}\$?\d+")
STRING = re.compile(r'"[^"]*"')
NUMBER = re.compile(r"(?<![A-Za-z_.])\d+(?:\.\d+)?")


def numeric_literals(formula: str) -> set[str]:
    text = STRING.sub("", formula)
    text = CELL_REF.sub("", text)
    return set(NUMBER.findall(text))


def formula_cells(ws, first_row: int):
    for row in ws.iter_rows(min_row=first_row):
        for cell in row:
            if isinstance(cell.value, str) and cell.value.startswith("="):
                yield cell


@pytest.fixture(scope="module")
def wb(workbook_path):
    return load_workbook(workbook_path)


def test_sheets_exist_in_documented_order(wb):
    assert wb.sheetnames == [
        "Inputs_SKU",
        "Inputs_Origin",
        "Quotes",
        "Tariffs",
        "FX",
        "Params",
        "Calc",
        "Compare",
        "Scenario",
        "Notes",
    ]


def test_params_are_defined_names(wb):
    assert wb.defined_names["Carrying_Rate"].attr_text == "Params!$B$2"
    assert wb.defined_names["Service_Level"].attr_text == "Params!$B$3"
    assert wb["Params"]["B2"].value == 0.22 and wb["Params"]["B3"].value == 0.97


def test_calc_has_one_row_per_sku_and_origin(wb):
    ws = wb["Calc"]
    assert ws.max_row == 121
    pairs = {(ws.cell(r, 2).value, ws.cell(r, 3).value) for r in range(2, 122)}
    assert len(pairs) == 120


def test_compare_has_one_row_per_sku(wb):
    ws = wb["Compare"]
    assert ws.max_row == 42
    assert ws["A3"].value and ws["A42"].value


def test_calc_and_compare_derived_cells_are_all_formulas(wb):
    calc = wb["Calc"]
    for r in range(2, 122):
        for idx, name in enumerate(L.CALC_COLUMNS, start=1):
            if name in L.CALC_VALUE_COLUMNS:
                continue
            assert str(calc.cell(r, idx).value).startswith("="), (r, name)
    compare_ws = wb["Compare"]
    for r in range(3, 43):
        for idx in range(2, compare_ws.max_column + 1):
            assert str(compare_ws.cell(r, idx).value).startswith("="), (r, idx)


def test_formulas_use_required_functions_with_xlfn_prefix(wb):
    calc_text = " ".join(c.value for c in formula_cells(wb["Calc"], 2))
    assert "_xlfn.NORM.S.INV(Service_Level)" in calc_text
    assert "INDEX(" in calc_text and "MATCH(" in calc_text and "SQRT(" in calc_text
    assert "NORM.S.INV" not in calc_text.replace("_xlfn.NORM.S.INV", "")
    scenario_text = " ".join(c.value for c in formula_cells(wb["Scenario"], 1))
    assert "SUMPRODUCT(" in scenario_text


def test_no_stray_numeric_literals_in_calc_and_compare_formulas(wb):
    offenders = {}
    for sheet, first in (("Calc", 2), ("Compare", 3)):
        for cell in formula_cells(wb[sheet], first):
            extra = numeric_literals(cell.value) - ALLOWED_LITERALS
            if extra:
                offenders[f"{sheet}!{cell.coordinate}"] = (cell.value, extra)
    assert not offenders


def test_literal_scanner_catches_a_hard_coded_rate():
    assert numeric_literals("=A2*0.22+B$3/365") == {"0.22", "365"}
    assert numeric_literals('=IF(A2<>"x1","",C2^2)') == {"2"}


def test_number_formats_freeze_panes_and_validation(wb):
    calc = wb["Calc"]
    assert calc.freeze_panes == "D2" and wb["Compare"].freeze_panes == "B3"
    assert calc["Q2"].number_format.startswith('"$"')  # landed cost
    assert calc["N2"].number_format == "0.0%"  # additional tariff
    validations = wb["Scenario"].data_validations.dataValidation
    assert any("B3" in str(v.sqref) and v.type == "decimal" for v in validations)
    assert wb["Scenario"]["B3"].value == 0.25


def test_scenario_layout_has_thirteen_steps_plus_what_if(wb):
    ws = wb["Scenario"]
    steps = [ws.cell(5, c).value for c in range(2, 15)]
    assert steps == list(SCENARIO_STEPS)
    assert ws.cell(5, 15).value == "=Scenario_Tariff"


def test_workbook_inputs_round_trip(workbook_path, ds):
    assert read_dataset(workbook_path) == ds


def test_verify_passes_and_recalculated_values_match_reference(workbook_path, ds):
    report = verify(workbook_path)
    assert report.calc_rows == 120 and report.compare_rows == 40
    assert report.scenario_columns == 14
    value = _recalculate(workbook_path)
    rows = compare(ds)
    # First Compare row: best total cost and best origin come from the formulas.
    origins = ["China", "Vietnam", "Mexico"]
    best_total = L.compare_letter(origins, "best_total")
    best_origin = L.compare_letter(origins, "best_origin")
    assert value("Compare", f"{best_total}3") == pytest.approx(rows[0].best_total, rel=1e-9)
    assert value("Compare", f"{best_origin}3") == rows[0].best_origin
    # Scenario columns each sum to 40 in the recalculated workbook.
    for col in "BCDEFGHIJKLMNO":
        assert sum(value("Scenario", f"{col}{r}") for r in (6, 7, 8)) == 40
        assert value("Scenario", f"{col}9") == 40


def test_recalculated_fixture_like_sku_row_is_numerically_sane(workbook_path, ds):
    value = _recalculate(workbook_path)
    first = ds.skus[0]
    assert value("Calc", "B2") == first.sku_id
    assert value("Calc", "I2") == ds.quotes[(first.sku_id, "China")]
    assert value("Calc", "U2") == pytest.approx(1.8807936081512504, rel=1e-12)


def _tampered(workbook_path, tmp_path, mutate):
    wb = load_workbook(workbook_path)
    mutate(wb)
    out = tmp_path / "tampered.xlsx"
    wb.save(out)
    return out


def test_replacing_a_formula_with_its_value_fails_naming_the_cell(workbook_path, ds, tmp_path):
    truth_total = next(r for r in compare(ds)).total["China"]
    cell = L.compare_letter(["China", "Vietnam", "Mexico"], "total:China") + "3"

    def mutate(wb):
        # Hard-code the correct value: only a formula check can notice.
        wb["Compare"][cell] = truth_total

    path = _tampered(workbook_path, tmp_path, mutate)
    with pytest.raises(VerifyError, match=rf"Compare!{cell} is not a formula"):
        verify(path)


def test_replacing_a_calc_formula_with_its_value_fails_naming_the_cell(workbook_path, tmp_path):
    def mutate(wb):
        wb["Calc"]["Y9"] = 12.34

    path = _tampered(workbook_path, tmp_path, mutate)
    with pytest.raises(VerifyError, match=r"Calc!Y9 .* is not a formula"):
        verify(path)


def test_a_wrong_formula_is_caught_by_the_recalculation(workbook_path, tmp_path):
    def mutate(wb):
        wb["Calc"]["T7"] = "=R7*2"  # pipeline carrying doubled

    path = _tampered(workbook_path, tmp_path, mutate)
    with pytest.raises(VerifyError, match=r"Calc!T7 "):
        verify(path)
