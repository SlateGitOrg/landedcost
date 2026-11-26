"""Command line interface."""

from __future__ import annotations

from pathlib import Path

import typer

from landedcost import generate as gen
from landedcost.breakeven import breakeven_table
from landedcost.data import load_dataset
from landedcost.model import compare, compute_all
from landedcost.report import build_report, compare_table
from landedcost.verify import VerifyError, verify
from landedcost.workbook import build_workbook

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Landed-cost workbook tools.")

DATA_OPT = typer.Option(Path("data"), "--data", "-d", help="Directory holding the input CSV files.")


@app.command()
def generate(
    seed: int = typer.Option(7, help="Random seed."),
    out: Path = typer.Option(Path("data"), help="Output directory."),
) -> None:
    """Write synthetic inputs (and truth.json with the planted patterns)."""
    ds = gen.write(seed, out)
    typer.echo(f"wrote {len(ds.skus)} SKUs x {len(ds.origins)} origins to {out}")


@app.command()
def compute(data: Path = DATA_OPT, top: int = typer.Option(10, help="Rows to show.")) -> None:
    """Price every SKU x origin and list the largest savings."""
    ds = load_dataset(data)
    rows = compare(ds, compute_all(ds))
    typer.echo(compare_table(ds, rows, limit=top))


@app.command("breakeven")
def breakeven_cmd(data: Path = DATA_OPT) -> None:
    """Print the break-even incumbent tariff for every SKU and alternative origin."""
    ds = load_dataset(data)
    alts = [o.name for o in ds.origins[1:]]
    typer.echo("sku_id," + ",".join(alts))
    for sku_id, row in breakeven_table(ds).items():
        typer.echo(sku_id + "," + ",".join("" if row[a] is None else f"{row[a]:.4f}" for a in alts))


@app.command("build-workbook")
def build_workbook_cmd(
    data: Path = DATA_OPT,
    out: Path = typer.Option(Path("out/landedcost.xlsx"), help="Workbook path."),
) -> None:
    """Write the .xlsx with live formulas."""
    path = build_workbook(load_dataset(data), out)
    typer.echo(f"wrote {path}")


@app.command("verify")
def verify_cmd(workbook: Path = typer.Argument(Path("out/landedcost.xlsx"))) -> None:
    """Recalculate the workbook and compare it with the Python reference."""
    try:
        report = verify(workbook)
    except VerifyError as exc:
        typer.echo(f"MISMATCH {exc}", err=True)
        raise typer.Exit(1) from exc
    typer.echo(
        f"OK: {report.calc_rows} Calc rows and {report.compare_rows} Compare rows match the "
        f"reference within 1e-9 ({report.cells_checked} cells, {report.scenario_columns} "
        "scenario columns)"
    )


@app.command()
def report(
    data: Path = DATA_OPT,
    out: Path = typer.Option(None, help="Write the Markdown here instead of stdout."),
) -> None:
    """Markdown summary: moves, break-even distribution, scenario sweep and flips."""
    text = build_report(load_dataset(data))
    if out is None:
        typer.echo(text, nl=False)
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        typer.echo(f"wrote {out}")


if __name__ == "__main__":  # pragma: no cover
    app()
