"""End-to-end checks, including the 2026 path on SYNTHETIC results.

The synthetic 2026 file is built from the 2021 results (shared voting
districts only, FF+ PR votes doubled). It exists only inside a temp folder
to prove that ingest -> analyse -> comparison works before real results exist.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
PIPE = REPO / "pipeline"


def run(script: str, *args: str, root: Path) -> str:
    env = {**os.environ, "PRETORIAPLUS_ROOT": str(root)}
    r = subprocess.run([sys.executable, str(PIPE / script), *args], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr[-2000:]
    return r.stdout


@pytest.fixture(scope="module")
def baseline(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("base")
    shutil.copytree(REPO / "data" / "tshwane", root / "data" / "tshwane")
    run("analyse.py", root=root)
    return root


def test_2021_totals_match_iec_file(baseline):
    raw = pd.read_csv(REPO / "data/tshwane/results/results_2021.csv.gz")
    w = pd.read_csv(baseline / "outputs/ffplus_wards_2021.csv")
    assert len(w) == 107
    assert w["pr_ffp_votes"].sum() == raw.query("ballot=='PR' and party=='FF+'")["votes"].sum() == 52458
    assert w["ffp_stood"].all()  # FF+ contested every Tshwane ward in 2021


def test_notional_preserves_votes(baseline):
    raw = pd.read_csv(REPO / "data/tshwane/results/results_2021.csv.gz")
    b = pd.read_csv(baseline / "outputs/ffplus_wards_2026_comparison.csv")
    assert len(b) == 107
    total = raw.query("ballot=='PR' and party=='FF+'")["votes"].sum()
    assert abs(b["n21_pr_ffp_votes"].sum() - total) < 1


def test_ward_names_cover_every_ward():
    d = pd.read_csv(REPO / "data/tshwane/ward_areas.csv")
    for b in (2016, 2021, 2026):
        x = d[d["boundary"] == b]
        assert len(x) == 107 and x["name"].str.len().min() > 2
    assert "Waverley" in d.query("boundary==2021 and ward_no==52")["name"].iloc[0]


def test_ward_vote_table_groups(baseline):
    t = pd.read_csv(baseline / "outputs/ward_votes_2021_own.csv")
    assert t["FF+ votes"].sum() == 52458
    assert t["tier"].value_counts().to_dict() == {"Negligible": 58, "Solid": 21, "Stronghold": 19, "Marginal": 9}
    party_cols = [c for c in t.columns if c.endswith(" votes")]
    assert (t[party_cols].sum(axis=1) == t["valid_votes"]).all()


def test_2016_no_candidate_wards(baseline):
    nc = pd.read_csv(baseline / "outputs/ffplus_no_ward_candidate.csv")
    assert set(nc.query("year==2016")["ward_no"]) == {12, 21}
    assert nc.query("year==2021").empty


def test_2026_flow_with_synthetic_results(tmp_path):
    root = tmp_path
    shutil.copytree(REPO / "data" / "tshwane", root / "data" / "tshwane")
    r21 = pd.read_csv(REPO / "data/tshwane/results/results_2021.csv.gz")
    vd26 = gpd.read_file(REPO / "data/tshwane/geo/vd_2026.geojson").set_index("vd")["ward_id"]
    s = r21[r21["vd"].isin(vd26.index)].copy()
    s.loc[(s["party"] == "FF+") & (s["ballot"] == "PR"), "votes"] *= 2
    fake = pd.DataFrame({
        "VotingDistrict": s["vd"], "BallotType": s["ballot"], "PartyName": s["party_iec"],
        "TotalValidVotes": s["votes"], "RegisteredVoters": s["registered"], "SpoiltVotes": s["spoilt"],
    })  # no Ward column: ingest must fill it from the 2026 map
    f = tmp_path / "synthetic_2026.csv"
    fake.to_csv(f, index=False)

    out = run("ingest_2026.py", str(f), root=root)
    assert "759 of 796" in out
    run("analyse.py", root=root)

    b = pd.read_csv(root / "outputs/ffplus_wards_2026_comparison.csv")
    assert {"swing_pp", "r26_pr_ffp_share", "vds_counted", "complete"} <= set(b.columns)
    assert b["swing_pp"].dropna().median() >= 0  # FF+ doubled, so swing is up
    vd = pd.read_csv(root / "outputs/ffplus_vd_2021_vs_2026.csv")
    assert len(vd) == 759
    assert (vd["pr_ffp_votes_2026"] == vd["pr_ffp_votes_2021"] * 2).all()
    assert "2021 → 2026 by 2021 tier" in (root / "outputs/REPORT.md").read_text()
