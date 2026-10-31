"""Cut the national/provincial source files down to the City of Tshwane.

Reads data/sources/ (see fetch.py) and writes small, committed files:
  data/tshwane/results/results_{2016,2021}.csv.gz   tidy VD x ballot x party rows
  data/tshwane/geo/wards_{2016,2021,2026}.geojson   ward boundaries per election
  data/tshwane/geo/vd_{2016,2021,2026}.geojson      voting district boundaries

Usage:  python pipeline/prepare.py
"""
from __future__ import annotations

import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd

from common import GEO, RESULTS, SOURCES, WARD_PREFIX, read_iec_results

PRECISION = 5  # ~1 m; plenty for ward maps and keeps files small


def unzip(zpath: Path, tmp: Path) -> Path:
    d = tmp / zpath.stem
    with zipfile.ZipFile(zpath) as z:
        members = [m for m in z.namelist() if not m.startswith("__MACOSX") and ".." not in m]
        z.extractall(d, members)
    return d


def find(d: Path, name: str) -> Path:
    hits = [p for p in d.rglob(name) if "__MACOSX" not in p.parts]
    if not hits:
        raise FileNotFoundError(f"{name} not found in {d}")
    return hits[0]


def is_tsh(series) -> "gpd.pd.Series":
    return series.astype("int64") // 100000 == WARD_PREFIX


def write_geo(gdf: gpd.GeoDataFrame, name: str) -> None:
    gdf = gdf.to_crs("EPSG:4326")
    gdf["geometry"] = gdf.geometry.make_valid()
    out = GEO / name
    gdf.to_file(out, driver="GeoJSON", COORDINATE_PRECISION=PRECISION, engine="pyogrio")
    print(f"  {out.relative_to(GEO.parents[2])}: {len(gdf)} features, {out.stat().st_size/1e6:.1f} MB")


def main() -> None:
    GEO.mkdir(parents=True, exist_ok=True)
    RESULTS.mkdir(parents=True, exist_ok=True)

    print("results")
    for year, src in [(2016, "results_2016_national.csv.zip"), (2021, "results_2021_GP.csv.zip")]:
        df = read_iec_results(SOURCES / src, year)
        out = RESULTS / f"results_{year}.csv.gz"
        df.to_csv(out, index=False)
        print(f"  {out.name}: {len(df)} rows, {df.ward_id.nunique()} wards, {df.vd.nunique()} VDs")

    print("boundaries")
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)

        w20 = gpd.read_file(SOURCES / "wards_2020" / "MDB_Wards_2020.shp")
        w20 = w20[w20["CAT_B"] == "TSH"]
        write_geo(gpd.GeoDataFrame({"ward_id": w20["WardID"].astype(int), "ward_no": w20["WardNo"].astype(int)},
                                   geometry=w20.geometry), "wards_2021.geojson")

        w26 = gpd.read_file(SOURCES / "wards_2026" / "Wards_2026.shp")
        w26 = w26[w26["MunicCode"] == "TSH"]
        write_geo(gpd.GeoDataFrame({"ward_id": w26["pklWardId"].astype(int), "ward_no": w26["WardNo"].astype(int)},
                                   geometry=w26.geometry), "wards_2026.geojson")

        d16 = unzip(SOURCES / "vd_2016.zip", tmp)
        w16 = gpd.read_file(find(d16, "ward_2016.shp"))
        w16 = w16[is_tsh(w16["WARD_CODE"])]
        write_geo(gpd.GeoDataFrame({"ward_id": w16["WARD_CODE"].astype(int),
                                    "ward_no": w16["WARD_CODE"].astype(int) % 1000}, geometry=w16.geometry),
                  "wards_2016.geojson")
        v16 = gpd.read_file(find(d16, "votingdistrict_2016.shp"))
        v16 = v16[is_tsh(v16["WARD_CODE"])]
        write_geo(gpd.GeoDataFrame({"vd": v16["VD_CODE"].astype(int), "ward_id": v16["WARD_CODE"].astype(int),
                                    "name": v16["VD_NAME"]}, geometry=v16.geometry), "vd_2016.geojson")

        d21 = unzip(SOURCES / "vd_2021.zip", tmp)
        v21 = gpd.read_file(find(d21, "vd2021.shp"))
        v21 = v21[is_tsh(v21["WARD"])]
        write_geo(gpd.GeoDataFrame({"vd": v21["CODE"].astype(int), "ward_id": v21["WARD"].astype(int),
                                    "name": v21["NAME"]}, geometry=v21.geometry), "vd_2021.geojson")

        d26 = unzip(SOURCES / "vd_2026.zip", tmp)
        v26 = gpd.read_file(find(d26, "Voting_Districts_2026.shp"))
        v26 = v26[v26["MunicCode"] == "TSH"]
        write_geo(gpd.GeoDataFrame({"vd": v26["VDNumber"].astype(int), "ward_id": v26["WardId"].astype(int)},
                                   geometry=v26.geometry), "vd_2026.geojson")


if __name__ == "__main__":
    main()
