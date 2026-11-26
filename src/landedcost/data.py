"""Input records, the dataset container, and CSV/JSON persistence."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Sku:
    sku_id: str
    description: str
    category: str
    hts_group: str
    usmca_qualifying: bool
    annual_demand: float
    weekly_demand_sd: float
    unit_cube: float
    order_qty: float


@dataclass(frozen=True)
class Origin:
    name: str
    currency: str
    mode: str
    transit_days_mean: float
    transit_days_sd: float
    container_cost: float
    usable_cube: float
    port_per_unit: float


@dataclass(frozen=True)
class Tariff:
    """Additional (policy) tariff for an origin, by USMCA status of the SKU."""

    origin: str
    qualifying: float
    non_qualifying: float


@dataclass(frozen=True)
class Dataset:
    skus: tuple[Sku, ...]
    origins: tuple[Origin, ...]
    quotes: dict[tuple[str, str], float]  # (sku_id, origin) -> FOB price, local currency
    base_duty: dict[str, float]  # HTS group -> base duty rate
    tariffs: dict[str, Tariff]  # origin -> additional tariff
    fx: dict[str, float]  # currency -> USD per unit of local currency
    carrying_rate: float
    service_level: float

    @property
    def incumbent(self) -> str:
        """The incumbent origin is the first one listed."""
        return self.origins[0].name

    def origin(self, name: str) -> Origin:
        for o in self.origins:
            if o.name == name:
                return o
        raise KeyError(name)

    def additional_tariff(self, sku: Sku, origin: str) -> float:
        t = self.tariffs[origin]
        return t.qualifying if sku.usmca_qualifying else t.non_qualifying


def _write_csv(path: Path, header: list[str], rows: list[list[object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _num(x: float) -> str:
    """Shortest round-trip text for a float, with whole numbers written without a point."""
    return str(int(x)) if float(x).is_integer() else repr(float(x))


def save_dataset(ds: Dataset, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    _write_csv(
        out / "skus.csv",
        [
            "sku_id",
            "description",
            "category",
            "hts_group",
            "usmca_qualifying",
            "annual_demand",
            "weekly_demand_sd",
            "unit_cube",
            "order_qty",
        ],
        [
            [
                s.sku_id,
                s.description,
                s.category,
                s.hts_group,
                int(s.usmca_qualifying),
                _num(s.annual_demand),
                _num(s.weekly_demand_sd),
                _num(s.unit_cube),
                _num(s.order_qty),
            ]
            for s in ds.skus
        ],
    )
    _write_csv(
        out / "origins.csv",
        [
            "origin",
            "currency",
            "mode",
            "transit_days_mean",
            "transit_days_sd",
            "container_cost",
            "usable_cube",
            "port_per_unit",
        ],
        [
            [
                o.name,
                o.currency,
                o.mode,
                _num(o.transit_days_mean),
                _num(o.transit_days_sd),
                _num(o.container_cost),
                _num(o.usable_cube),
                _num(o.port_per_unit),
            ]
            for o in ds.origins
        ],
    )
    _write_csv(
        out / "quotes.csv",
        ["sku_id", "origin", "fob_local"],
        [[sku, origin, _num(p)] for (sku, origin), p in ds.quotes.items()],
    )
    _write_csv(
        out / "duties.csv",
        ["hts_group", "base_duty"],
        [[g, _num(r)] for g, r in ds.base_duty.items()],
    )
    _write_csv(
        out / "tariffs.csv",
        ["origin", "additional_qualifying", "additional_non_qualifying"],
        [[t.origin, _num(t.qualifying), _num(t.non_qualifying)] for t in ds.tariffs.values()],
    )
    _write_csv(
        out / "fx.csv",
        ["currency", "usd_per_unit"],
        [[c, _num(r)] for c, r in ds.fx.items()],
    )
    (out / "params.json").write_text(
        json.dumps(
            {"carrying_rate": ds.carrying_rate, "service_level": ds.service_level},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def load_dataset(directory: Path) -> Dataset:
    d = Path(directory)
    skus = tuple(
        Sku(
            sku_id=r["sku_id"],
            description=r["description"],
            category=r["category"],
            hts_group=r["hts_group"],
            usmca_qualifying=r["usmca_qualifying"] == "1",
            annual_demand=float(r["annual_demand"]),
            weekly_demand_sd=float(r["weekly_demand_sd"]),
            unit_cube=float(r["unit_cube"]),
            order_qty=float(r["order_qty"]),
        )
        for r in _read_csv(d / "skus.csv")
    )
    origins = tuple(
        Origin(
            name=r["origin"],
            currency=r["currency"],
            mode=r["mode"],
            transit_days_mean=float(r["transit_days_mean"]),
            transit_days_sd=float(r["transit_days_sd"]),
            container_cost=float(r["container_cost"]),
            usable_cube=float(r["usable_cube"]),
            port_per_unit=float(r["port_per_unit"]),
        )
        for r in _read_csv(d / "origins.csv")
    )
    quotes = {
        (r["sku_id"], r["origin"]): float(r["fob_local"]) for r in _read_csv(d / "quotes.csv")
    }
    base_duty = {r["hts_group"]: float(r["base_duty"]) for r in _read_csv(d / "duties.csv")}
    tariffs = {
        r["origin"]: Tariff(
            r["origin"], float(r["additional_qualifying"]), float(r["additional_non_qualifying"])
        )
        for r in _read_csv(d / "tariffs.csv")
    }
    fx = {r["currency"]: float(r["usd_per_unit"]) for r in _read_csv(d / "fx.csv")}
    params = json.loads((d / "params.json").read_text(encoding="utf-8"))
    return Dataset(
        skus=skus,
        origins=origins,
        quotes=quotes,
        base_duty=base_duty,
        tariffs=tariffs,
        fx=fx,
        carrying_rate=float(params["carrying_rate"]),
        service_level=float(params["service_level"]),
    )
