"""Load 2026 results into data/tshwane/results/results_2026.csv.gz.

Accepts one or more files (CSV or zipped CSV) in the IEC "detailed results"
layout, the same layout used for 2016 and 2021:

  Province, Municipality, Ward, VotingDistrict, VotingStationName,
  RegisteredVoters, BallotType, SpoiltVotes, PartyName, TotalValidVotes

Only VotingDistrict, BallotType, PartyName and TotalValidVotes are required.
Missing Ward / Municipality columns are filled from the 2026 voting district
map, so a hand-typed file from results slips also works (see
data/templates/results_2026_template.csv). Files are merged; if the same
voting district + ballot appears twice, the later file wins, so you can keep
adding files as results come in.

Usage:  python pipeline/ingest_2026.py path/to/GP.csv [more.csv ...]
        python pipeline/analyse.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import geopandas as gpd
import pandas as pd

from common import GEO, RESULTS, read_iec_results

REQUIRED = ["VotingDistrict", "BallotType", "PartyName", "TotalValidVotes"]


def normalise_file(path: Path, vd_lookup: pd.Series) -> pd.DataFrame:
    raw = pd.read_csv(path, encoding="utf-8-sig", dtype=str, low_memory=False)
    raw.columns = [c.strip() for c in raw.columns]
    missing = [c for c in REQUIRED if c not in raw.columns]
    if missing:
        raise SystemExit(f"{path}: missing columns {missing}. Expected the IEC detailed-results layout.")
    vd = raw["VotingDistrict"].str.strip().astype(int)
    if "Municipality" not in raw.columns:
        raw["Municipality"] = "TSH - City of Tshwane"
    if "Ward" not in raw.columns:
        ward = vd.map(vd_lookup)
        if ward.isna().any():
            bad = sorted(vd[ward.isna()].unique())[:10]
            raise SystemExit(f"{path}: voting districts not on the 2026 Tshwane map: {bad}")
        raw["Ward"] = "Ward " + ward.astype(int).astype(str)
    for col, default in [("VotingStationName", ""), ("RegisteredVoters", "0"), ("SpoiltVotes", "0")]:
        if col not in raw.columns:
            raw[col] = default
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d) / "results.csv"
        raw.to_csv(tmp, index=False)
        return read_iec_results(tmp, 2026)


def main(paths: list[str]) -> int:
    if not paths:
        print(__doc__)
        return 1
    vd26 = gpd.read_file(GEO / "vd_2026.geojson")
    vd_lookup = vd26.set_index("vd")["ward_id"]

    frames = [normalise_file(Path(p), vd_lookup).assign(_file=i) for i, p in enumerate(paths)]
    df = pd.concat(frames, ignore_index=True)
    # later files replace earlier ones for the same VD + ballot
    latest = df.groupby(["vd", "ballot"])["_file"].transform("max")
    df = df[df["_file"] == latest].drop(columns="_file")

    if df.empty:
        raise SystemExit("No City of Tshwane rows found. Check the Municipality column starts with 'TSH'.")

    unknown = set(df["vd"]) - set(vd26["vd"])
    if unknown:
        print(f"warning: {len(unknown)} voting districts are not on the 2026 map: {sorted(unknown)[:10]}")
    wrong_ward = df.merge(vd_lookup.rename("map_ward"), left_on="vd", right_index=True)
    wrong_ward = wrong_ward[wrong_ward["ward_id"] != wrong_ward["map_ward"]]["vd"].unique()
    if len(wrong_ward):
        print(f"warning: {len(wrong_ward)} voting districts sit in a different ward than the 2026 map says")

    out = RESULTS / "results_2026.csv.gz"
    df.to_csv(out, index=False)
    n_exp = vd26["vd"].nunique()
    print(f"{out.relative_to(RESULTS.parents[2])}: {df['vd'].nunique()} of {n_exp} voting districts, "
          f"{df['ward_id'].nunique()} wards, ballots {sorted(df['ballot'].unique())}")
    print("next: python pipeline/analyse.py")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
