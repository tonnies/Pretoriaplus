"""Give every ward an area name built from the suburbs it covers.

Suburb names come from the Stats SA Census 2011 sub-places. Each suburb is
weighted by the registered voters living in it, not by land area, so a
built-up suburb outranks a large farm area. Voters are spread over each voting
district's area.

Writes data/tshwane/ward_areas.csv:
  boundary   2016 | 2021 | 2026 (which ward map)
  ward_id, ward_no
  name       short label, e.g. "Waverley, Villieria, Koedoespoort"
  areas      every suburb with its share of the ward's voters

Names in data/tshwane/ward_names_override.csv (boundary, ward_no, name)
replace the generated label, e.g. to use names from findmyward.co.za.

Usage:  python pipeline/ward_names.py
"""
from __future__ import annotations

import re

import geopandas as gpd
import pandas as pd

from common import GEO, METRIC_CRS, RESULTS, TSH

# Ward map -> (ward geojson, VD geojson and results year used for voter weights)
BOUNDARIES = {2016: ("wards_2016", 2016), 2021: ("wards_2021", 2021), 2026: ("wards_2026", 2021)}
MIN_SHARE = 0.03   # leave out suburbs with under 3% of a ward's voters
LABEL_PARTS = 3


def clean(name: str) -> str:
    n = re.sub(r"\s+", " ", str(name)).strip()
    n = re.sub(r"\s+SP\d*$", "", n)              # "Mamelodi SP" -> "Mamelodi", "Centurion SP3" -> "Centurion"
    n = re.sub(r"\s+(AH|SH)$", "", n)            # agricultural holdings / smallholdings
    n = re.sub(r"^Tshwane NU$", "Rural Tshwane", n)
    n = re.sub(r"\s+NU$", " (rural)", n)
    n = " ".join(w[:1].upper() + w[1:] if w.islower() and len(w) > 3 else w for w in n.split())
    return n


# Uninhabited places: their "voters" are an artefact of spreading a large
# voting district's voters by area, so they never name a ward.
UNINHABITED = re.compile(r"nature reserve|protected natural|game reserve|national park|\bdam\b|botanical", re.I)


def base_and_ext(name: str) -> tuple[str, str | None]:
    """'Danville Ext 5' -> ('Danville', '5'); 'Ga-Rankuwa Unit 2' -> ('Ga-Rankuwa', 'Unit 2')."""
    m = re.match(r"^(.*?)\s+(Ext\.?|Extension)\s+(.+)$", name, flags=re.I)
    if m:
        return m.group(1).strip(), m.group(3).strip()
    m = re.match(r"^(.*?)\s+(Unit|Zone|Block|Section)\s+(.+)$", name, flags=re.I)
    if m:
        return m.group(1).strip(), f"{m.group(2).title()} {m.group(3).strip()}"
    return name, None


def label(rows: pd.DataFrame) -> str:
    """Top suburbs by voters, merging extensions of the same suburb."""
    groups: dict[str, list] = {}
    canon: dict[str, str] = {}
    order: list[str] = []
    for name, share in zip(rows["area"], rows["share"]):
        base, ext = base_and_ext(name)
        base = canon.setdefault(re.sub(r"[^a-z]", "", base.lower()), base)  # GaRankuwa == Ga-Rankuwa
        if base not in groups:
            groups[base] = [0.0, []]
            order.append(base)
        groups[base][0] += share
        if ext:
            groups[base][1].append(ext)
    order.sort(key=lambda b: -groups[b][0])
    parts = []
    for b in order[:LABEL_PARTS]:
        exts = groups[b][1]
        # one base name for the whole ward (e.g. all Mamelodi): show which extensions
        if len(order) == 1 and exts:
            word = "Ext " if all(re.match(r"^\d", e) for e in exts) else ""
            parts.append(f"{b} {word}{', '.join(exts[:4])}{'…' if len(exts) > 4 else ''}")
        else:
            parts.append(b)
    return ", ".join(parts)


def main() -> None:
    sp = gpd.read_file(GEO / "subplaces_2011.geojson").to_crs(METRIC_CRS)
    sp["area"] = sp["sp_name"].map(clean)
    sp = sp[~sp["area"].str.contains(UNINHABITED)]
    out = []
    for boundary, (ward_file, vd_year) in BOUNDARIES.items():
        wards = gpd.read_file(GEO / f"{ward_file}.geojson").to_crs(METRIC_CRS)
        vd = gpd.read_file(GEO / f"vd_{vd_year}.geojson").to_crs(METRIC_CRS)[["vd", "geometry"]]
        res = pd.read_csv(RESULTS / f"results_{vd_year}.csv.gz")
        reg = res.groupby("vd")["registered"].max()
        vd["reg"] = vd["vd"].map(reg).fillna(0)
        vd["vd_area"] = vd.area
        # voters per piece of (VD x suburb x ward), spread by area within the VD
        pieces = gpd.overlay(vd, sp[["area", "geometry"]], how="intersection", keep_geom_type=True)
        pieces = gpd.overlay(pieces, wards[["ward_id", "geometry"]], how="intersection", keep_geom_type=True)
        pieces["voters"] = pieces["reg"] * pieces.area / pieces["vd_area"]
        # suburbs by area too, for wards with no voters on record
        pieces["m2"] = pieces.area
        g = pieces.groupby(["ward_id", "area"], as_index=False)[["voters", "m2"]].sum()
        tot = g.groupby("ward_id")[["voters", "m2"]].transform("sum")
        g["share"] = (g["voters"] / tot["voters"]).where(tot["voters"] > 0, g["m2"] / tot["m2"])
        for wid, rows in g.groupby("ward_id"):
            rows = rows.sort_values("share", ascending=False)
            keep = rows[rows["share"] >= MIN_SHARE]
            if keep.empty:
                keep = rows.head(1)
            out.append({
                "boundary": boundary, "ward_id": int(wid), "ward_no": int(wid) % 1000,
                "name": label(keep),
                "areas": "; ".join(f"{a} {s*100:.0f}%" for a, s in zip(keep["area"], keep["share"])),
            })
    df = pd.DataFrame(out).sort_values(["boundary", "ward_no"])

    override = TSH / "ward_names_override.csv"
    if override.exists():
        o = pd.read_csv(override)
        o = o.dropna(subset=["name"])
        o = o[o["name"].astype(str).str.strip() != ""]
        key = ["boundary", "ward_no"]
        df = df.merge(o[key + ["name"]].rename(columns={"name": "override"}), on=key, how="left")
        df["name"] = df["override"].fillna(df["name"])
        df = df.drop(columns="override")
        print(f"applied {len(o)} names from {override.name}")
    df.to_csv(TSH / "ward_areas.csv", index=False)
    for b in BOUNDARIES:
        print(f"{b}: {int((df['boundary'] == b).sum())} wards named")


if __name__ == "__main__":
    main()
