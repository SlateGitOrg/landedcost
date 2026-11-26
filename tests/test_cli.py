from __future__ import annotations

import json

import pytest
from openpyxl import load_workbook
from typer.testing import CliRunner

from landedcost.cli import app
from landedcost.report import build_report

runner = CliRunner()


@pytest.fixture(scope="module")
def data_dir(tmp_path_factory):
    out = tmp_path_factory.mktemp("data")
    result = runner.invoke(app, ["generate", "--seed", "7", "--out", str(out)])
    assert result.exit_code == 0, result.output
    return out


def test_generate_reports_what_it_wrote(data_dir):
    assert (data_dir / "truth.json").exists()
    assert json.loads((data_dir / "truth.json").read_text())["seed"] == 7


def test_compute_lists_largest_savings_first(data_dir):
    result = runner.invoke(app, ["compute", "--data", str(data_dir), "--top", "3"])
    assert result.exit_code == 0
    lines = [ln for ln in result.output.splitlines() if ln.startswith("| ") and "---" not in ln]
    assert len(lines) == 4  # header + 3
    savings = [float(ln.split("|")[5].strip().strip("$").replace(",", "")) for ln in lines[1:]]
    assert savings == sorted(savings, reverse=True)


def test_breakeven_prints_one_row_per_sku(data_dir):
    result = runner.invoke(app, ["breakeven", "--data", str(data_dir)])
    assert result.exit_code == 0
    rows = result.output.strip().splitlines()
    assert rows[0] == "sku_id,Vietnam,Mexico"
    assert len(rows) == 41
    assert any(r.endswith(",") for r in rows[1:])  # a blank break-even is an empty field


def test_build_workbook_writes_an_xlsx_with_formulas(data_dir, tmp_path):
    out = tmp_path / "x" / "landedcost.xlsx"
    result = runner.invoke(app, ["build-workbook", "--data", str(data_dir), "--out", str(out)])
    assert result.exit_code == 0, result.output
    wb = load_workbook(out)
    assert wb["Calc"]["Y2"].value.startswith("=")


def test_verify_exits_non_zero_and_names_the_cell(data_dir, tmp_path):
    out = tmp_path / "landedcost.xlsx"
    runner.invoke(app, ["build-workbook", "--data", str(data_dir), "--out", str(out)])
    wb = load_workbook(out)
    wb["Calc"]["Y5"] = 9.99
    wb.save(out)
    result = runner.invoke(app, ["verify", str(out)])
    assert result.exit_code == 1
    assert "Calc!Y5" in result.output


def test_report_contains_moves_breakeven_and_flip_sections(data_dir, ds):
    result = runner.invoke(app, ["report", "--data", str(data_dir)])
    assert result.exit_code == 0
    text = result.output
    for heading in ("## Recommended moves", "## Break-even distribution", "## Landed-cost flips"):
        assert heading in text
    assert "35 of 40 SKUs" in text
    assert text == build_report(ds)


def test_report_can_be_written_to_a_file(data_dir, tmp_path):
    out = tmp_path / "r" / "report.md"
    result = runner.invoke(app, ["report", "--data", str(data_dir), "--out", str(out)])
    assert result.exit_code == 0
    assert out.read_text().startswith("# Landed-cost report")
