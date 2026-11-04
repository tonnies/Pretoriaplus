"""Build ward tables, FF+ support tiers, notional results on 2026 wards and the
2021 -> 2026 comparison.

Inputs  data/tshwane/results/results_{2016,2021[,2026]}.csv.gz
        data/tshwane/geo/*.geojson
Outputs outputs/*.csv, outputs/REPORT.md, web/data.json

Usage:  python pipeline/analyse.py
"""
from __future__ import annotations

import json

import geopandas as gpd
import numpy as np
import pandas as pd

from common import FFP, GEO, METRIC_CRS, OUTPUTS, RESULTS, TSH, WEB

# FF+ support tiers, by share of the PR (party list) ballot in the ward.
# The PR ballot is the same in every ward, so it measures party support
# independent of who the ward candidate was.
TIERS = [  # (label, lower bound in %)
    ("Stronghold", 15.0),
    ("Solid", 5.0),
    ("Marginal", 1.0),
    ("Negligible", 0.0),
]
MIN_WEIGHT = 0.02  # drop VD slivers smaller than 2% of the VD's area in the overlay
KEY_PARTIES = ["DA", "ANC", "EFF", "ActionSA", FFP, "ACDP", "MK", "PA", "COPE", "BOSA", "Rise Mzansi"]


def tier(share_pct: float) -> str:
    for label, lo in TIERS:
        if share_pct >= lo:
            return label
    return TIERS[-1][0]


# ---------------------------------------------------------------- loading

def load_results() -> dict[int, pd.DataFrame]:
    out = {}
    for year in (2016, 2021, 2026):
        p = RESULTS / f"results_{year}.csv.gz"
        if p.exists():
            out[year] = pd.read_csv(p)
    return out


def load_geo(name: str) -> gpd.GeoDataFrame:
    return gpd.read_file(GEO / f"{name}.geojson")


# ---------------------------------------------------------------- tables

def vd_votes(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """-> (votes: vd, ballot, party, votes), (meta: vd, ballot, ward_id, registered, spoilt)."""
    votes = df.groupby(["ward_id", "vd", "ballot", "party"], as_index=False)["votes"].sum()
    meta = df.groupby(["vd", "ballot"], as_index=False).agg(
        ward_id=("ward_id", "first"), registered=("registered", "max"), spoilt=("spoilt", "max"))
    return votes, meta


def aggregate(votes: pd.DataFrame, meta: pd.DataFrame, unit: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Sum VD-level rows up to `unit` (a column present in both frames)."""
    v = votes.groupby([unit, "ballot", "party"], as_index=False)["votes"].sum()
    m = meta.groupby([unit, "ballot"], as_index=False)[["registered", "spoilt"]].sum()
    return v, m


def summarise(votes: pd.DataFrame, meta: pd.DataFrame, unit: str) -> pd.DataFrame:
    """One row per unit with turnout, winners and FF+/key-party numbers."""
    valid = votes.groupby([unit, "ballot"])["votes"].sum().rename("valid")
    v = votes.join(valid, on=[unit, "ballot"])
    v["share"] = np.where(v["valid"] > 0, v["votes"] / v["valid"] * 100, 0.0)
    v["rank"] = v.groupby([unit, "ballot"])["votes"].rank(ascending=False, method="min")

    rows = []
    for (u, ballot), g in v.groupby([unit, "ballot"]):
        g = g.sort_values("votes", ascending=False)
        ff = g[g["party"] == FFP]
        r = {
            unit: u, "ballot": ballot, "valid": int(round(g["valid"].iloc[0])),
            "winner": g["party"].iloc[0], "winner_share": g["share"].iloc[0],
            "runner_up": g["party"].iloc[1] if len(g) > 1 else None,
            "ffp_votes": float(ff["votes"].sum()), "ffp_share": float(ff["share"].sum()),
            "ffp_rank": int(ff["rank"].iloc[0]) if len(ff) and ff["votes"].sum() > 0 else None,
        }
        for p in KEY_PARTIES:
            if p != FFP:
                r[f"{p}_share"] = float(g.loc[g["party"] == p, "share"].sum())
        rows.append(r)
    s = pd.DataFrame(rows)

    pr = s[s["ballot"] == "PR"].drop(columns="ballot").set_index(unit)
    wd = s[s["ballot"] == "Ward"].drop(columns="ballot").set_index(unit)
    out = pr.add_prefix("pr_").join(wd[["valid", "winner", "winner_share", "ffp_votes", "ffp_share", "ffp_rank"]]
                                    .add_prefix("ward_"), how="outer")
    mpr = meta[meta["ballot"] == "PR"].set_index(unit)
    out["registered"] = mpr["registered"]
    out["pr_spoilt"] = mpr["spoilt"]
    out["turnout"] = (out["pr_valid"] + out["pr_spoilt"]) / out["registered"] * 100
    # FF+ fielded a ward candidate if it received any ward-ballot votes. The IEC
    # file lists every party, so a party without a candidate shows 0 votes.
    out["ffp_stood"] = out["ward_ffp_votes"].fillna(0) > 0
    out["ffp_tier"] = out["pr_ffp_share"].fillna(0).map(tier)
    return out.reset_index()


def party_long(votes: pd.DataFrame, unit: str, dataset: str) -> pd.DataFrame:
    valid = votes.groupby([unit, "ballot"])["votes"].transform("sum")
    out = votes.assign(share=np.where(valid > 0, votes["votes"] / valid * 100, 0.0), dataset=dataset)
    return out.rename(columns={unit: "unit_id"})[["dataset", "unit_id", "ballot", "party", "votes", "share"]]


# ---------------------------------------------------------------- crosswalk

def crosswalk(vd_geo: gpd.GeoDataFrame, wards26: gpd.GeoDataFrame) -> pd.DataFrame:
    """Area-weighted share of each voting district that falls in each 2026 ward."""
    vd = vd_geo[["vd", "geometry"]].to_crs(METRIC_CRS)
    vd["vd_area"] = vd.area
    w = wards26[["ward_id", "geometry"]].to_crs(METRIC_CRS).rename(columns={"ward_id": "ward26"})
    x = gpd.overlay(vd, w, how="intersection", keep_geom_type=True)
    x["weight"] = x.area / x["vd_area"]
    x = x[x["weight"] >= MIN_WEIGHT]
    x["weight"] = x["weight"] / x.groupby("vd")["weight"].transform("sum")
    return pd.DataFrame(x[["vd", "ward26", "weight"]])


def notional(votes: pd.DataFrame, meta: pd.DataFrame, cw: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    missing = set(votes["vd"]) - set(cw["vd"])
    if missing:
        raise ValueError(f"{len(missing)} VDs have no polygon in the crosswalk: {sorted(missing)[:5]}")
    v = votes.merge(cw, on="vd")
    v["votes"] = v["votes"] * v["weight"]
    m = meta.merge(cw, on="vd")
    m[["registered", "spoilt"]] = m[["registered", "spoilt"]].mul(m["weight"], axis=0)
    return aggregate(v.drop(columns="ward_id", errors="ignore"), m.drop(columns="ward_id"), "ward26")


# ---------------------------------------------------------------- main

def main() -> None:
    OUTPUTS.mkdir(exist_ok=True)
    WEB.mkdir(exist_ok=True)
    res = load_results()
    wards26 = load_geo("wards_2026")
    vd_geo = {y: load_geo(f"vd_{y}") for y in (2016, 2021, 2026)}

    summaries, longs, cw_stats = {}, [], {}
    vdsum = {}

    for year, df in res.items():
        votes, meta = vd_votes(df)
        # 1. on that election's own wards
        wv, wm = aggregate(votes, meta, "ward_id")
        key = f"{year}_own"
        summaries[key] = summarise(wv, wm, "ward_id").rename(columns={"ward_id": "unit_id"})
        longs.append(party_long(wv, "ward_id", key))
        # 2. voting-district level
        vkey = f"{year}_vd"
        vdsum[year] = summarise(votes, meta, "vd").rename(columns={"vd": "unit_id"})
        summaries[vkey] = vdsum[year]
        longs.append(party_long(votes, "vd", vkey))
        # 3. notional on 2026 wards (2026 itself is already on 2026 wards)
        if year < 2026:
            cw = crosswalk(vd_geo[year], wards26)
            cw.assign(year=year).to_csv(OUTPUTS / f"crosswalk_vd{year}_to_wards2026.csv", index=False)
            clean = cw.groupby("vd")["weight"].max() >= 0.95
            pr_valid = votes[votes["ballot"] == "PR"].groupby("vd")["votes"].sum()
            cw_stats[year] = float(pr_valid[clean.reindex(pr_valid.index, fill_value=False)].sum() / pr_valid.sum() * 100)
            nv, nm = notional(votes, meta, cw)
            nkey = f"{year}_on2026"
            summaries[nkey] = summarise(nv, nm, "ward26").rename(columns={"ward26": "unit_id"})
            longs.append(party_long(nv, "ward26", nkey))
        else:
            summaries["2026_on2026"] = summaries[key]

    all_long = pd.concat(longs, ignore_index=True)
    all_long.to_csv(OUTPUTS / "party_results_long.csv", index=False, float_format="%.3f")

    # ---------------- FF+ outputs
    names = ward_names()

    def ward_view(key: str) -> pd.DataFrame:
        s = summaries[key].copy()
        s.insert(1, "ward_no", s["unit_id"] % 1000)
        s.insert(2, "area", s["unit_id"].map(names.get(boundary_of(key), {})))
        return s.rename(columns={"unit_id": "ward_id"})

    w21 = ward_view("2021_own").sort_values("pr_ffp_share", ascending=False)
    w21.to_csv(OUTPUTS / "ffplus_wards_2021.csv", index=False, float_format="%.2f")
    w16 = ward_view("2016_own").sort_values("pr_ffp_share", ascending=False)
    w16.to_csv(OUTPUTS / "ffplus_wards_2016.csv", index=False, float_format="%.2f")
    vd21 = vdsum[2021].rename(columns={"unit_id": "vd"}).merge(
        res[2021].groupby("vd", as_index=False).agg(ward_id=("ward_id", "first"), station=("station", "first")), on="vd")
    vd21.sort_values("pr_ffp_share", ascending=False).to_csv(OUTPUTS / "ffplus_vd_2021.csv", index=False, float_format="%.2f")

    # No ward candidate, but PR votes
    nc = []
    for key, label in [("2016_own", 2016), ("2021_own", 2021), ("2026_own", 2026)]:
        if key not in summaries:
            continue
        s = ward_view(key)
        hit = s[(~s["ffp_stood"]) & (s["pr_ffp_votes"] > 0)]
        nc.append(hit.assign(year=label)[["year", "ward_id", "ward_no", "area", "pr_ffp_votes", "pr_ffp_share", "pr_winner", "ffp_tier"]])
    no_cand = pd.concat(nc, ignore_index=True)
    no_cand.to_csv(OUTPUTS / "ffplus_no_ward_candidate.csv", index=False, float_format="%.2f")
    stood = {int(k[:4]): int(ward_view(k)["ffp_stood"].sum()) for k in ("2016_own", "2021_own", "2026_own") if k in summaries}

    # 2026-ward baseline + comparison
    b = ward_view("2021_on2026")[["ward_id", "ward_no", "area", "registered", "turnout", "pr_valid", "pr_winner",
                                  "pr_ffp_votes", "pr_ffp_share", "pr_DA_share", "pr_ANC_share", "ffp_tier"]]
    b = b.rename(columns=lambda c: c if c in ("ward_id", "ward_no", "area") else f"n21_{c}")
    n16 = ward_view("2016_on2026")[["ward_id", "pr_ffp_votes", "pr_ffp_share"]].rename(
        columns={"pr_ffp_votes": "n16_pr_ffp_votes", "pr_ffp_share": "n16_pr_ffp_share"})
    b = b.merge(n16, on="ward_id", how="left")
    b["growth_16_21_pp"] = b["n21_pr_ffp_share"] - b["n16_pr_ffp_share"]
    has26 = "2026_on2026" in summaries
    if has26:
        a = ward_view("2026_on2026")[["ward_id", "registered", "turnout", "pr_valid", "pr_winner", "pr_ffp_votes",
                                      "pr_ffp_share", "ward_ffp_share", "ffp_stood", "ward_winner"]]
        a = a.rename(columns=lambda c: c if c == "ward_id" else f"r26_{c}")
        exp = vd_geo[2026].groupby("ward_id")["vd"].nunique().rename("vds_expected")
        got = res[2026].groupby("ward_id")["vd"].nunique().rename("vds_counted")
        b = b.merge(a, on="ward_id", how="left").join(exp, on="ward_id").join(got, on="ward_id")
        b["swing_pp"] = b["r26_pr_ffp_share"] - b["n21_pr_ffp_share"]
        b["vote_change"] = b["r26_pr_ffp_votes"] - b["n21_pr_ffp_votes"]
        b["complete"] = b["vds_counted"] >= b["vds_expected"]
    b.sort_values("ward_no").to_csv(OUTPUTS / "ffplus_wards_2026_comparison.csv", index=False, float_format="%.2f")

    # Same-VD comparison (VD numbers that exist in both elections)
    vd_cmp = None
    if has26:
        x = vdsum[2021][["unit_id", "pr_ffp_share", "pr_ffp_votes", "turnout", "ffp_tier"]].merge(
            vdsum[2026][["unit_id", "pr_ffp_share", "pr_ffp_votes", "turnout"]], on="unit_id", suffixes=("_2021", "_2026"))
        x["swing_pp"] = x["pr_ffp_share_2026"] - x["pr_ffp_share_2021"]
        vd_cmp = x.rename(columns={"unit_id": "vd"})
        vd_cmp.to_csv(OUTPUTS / "ffplus_vd_2021_vs_2026.csv", index=False, float_format="%.2f")

    write_vote_tables(summaries, all_long, ward_view)
    cands = ffplus_candidates(ward_view)
    write_report(res, summaries, ward_view, b, no_cand, stood, cw_stats, vd_cmp, vd21, cands)
    write_web(res, summaries, all_long, cw_stats, cands)
    print("wrote outputs/ and web/data.json")


def ffplus_candidates(ward_view):
    """FF+ 2026 candidates joined to the 2026 wards (from data/tshwane/candidates_2026.csv).

    Returns (ward table, PR list table) or None, and writes both to outputs/."""
    p = TSH / "candidates_2026.csv"
    if not p.exists():
        return None
    c = pd.read_csv(p)
    c = c[c["party"] == FFP]
    if c.empty:
        return None
    pr = c[c["list"] == "PR"].set_index("person")["pr_position"]
    w = c[c["list"] == "Ward"].copy()
    w["pr_position"] = w["person"].map(pr).astype("Int64")
    w["wards_standing"] = w.groupby("person")["ward_no"].transform("count")
    others = w.groupby("person")["ward_no"].apply(lambda s: sorted(int(x) for x in s))
    w["other_wards"] = [", ".join(str(x) for x in others[pe] if x != wn) for pe, wn in zip(w["person"], w["ward_no"])]
    base = ward_view("2021_on2026")[["ward_id", "ward_no", "area", "ffp_tier", "pr_ffp_votes", "pr_ffp_share", "pr_valid", "pr_winner"]]
    wards = base.merge(w[["ward_id", "name", "pr_position", "wards_standing", "other_wards", "person"]], on="ward_id", how="left")
    wards = wards.rename(columns={"ffp_tier": "tier_2021", "pr_ffp_votes": "ffp_votes_2021_est", "pr_ffp_share": "ffp_share_2021_est",
                                  "pr_valid": "valid_votes_2021_est", "pr_winner": "winner_2021", "name": "ffp_candidate",
                                  "pr_position": "candidate_pr_position"})
    order = {t: i for i, (t, _) in enumerate(TIERS)}
    wards = wards.sort_values(["tier_2021", "ward_no"], key=lambda col: col.map(order) if col.name == "tier_2021" else col)
    da = pd.read_csv(p)
    da = da[(da["party"] == "DA") & (da["list"] == "Ward")].set_index("ward_id")["name"]
    if len(da):
        wards.insert(wards.columns.get_loc("ffp_candidate") + 1, "da_candidate", wards["ward_id"].map(da))
    wards["ffp_votes_2021_est"] = wards["ffp_votes_2021_est"].round().astype(int)
    wards["valid_votes_2021_est"] = wards["valid_votes_2021_est"].round().astype(int)
    wards.drop(columns="person").to_csv(OUTPUTS / "ffplus_candidates_2026_by_ward.csv", index=False, float_format="%.2f")

    tier_of = dict(zip(wards["ward_no"], wards["tier_2021"]))
    plist = c[c["list"] == "PR"][["pr_position", "name", "person"]].copy()
    plist["ward_numbers"] = plist["person"].map(lambda pe: ", ".join(str(x) for x in others.get(pe, [])))
    plist["ward_groups_2021"] = plist["person"].map(lambda pe: ", ".join(sorted({tier_of[x] for x in others.get(pe, [])}, key=order.get)))
    plist["pr_position"] = plist["pr_position"].astype(int)
    plist = plist.sort_values("pr_position").drop(columns="person")
    plist.to_csv(OUTPUTS / "ffplus_pr_list_2026.csv", index=False)
    return wards, plist


TABLE_PARTIES = [FFP, "DA", "ANC", "EFF", "ActionSA", "ACDP", "MK", "PA", "BOSA", "Rise Mzansi", "COPE"]


def write_vote_tables(summaries, all_long, ward_view) -> None:
    """outputs/ward_votes_<dataset>.csv: PR votes per party per ward, grouped by FF+ tier.

    Tiers come from the 2021 FF+ share on the same ward map (2016 wards use 2016)."""
    tier_source = {"2016_own": "2016_own", "2021_own": "2021_own", "2021_on2026": "2021_on2026",
                   "2026_own": "2021_on2026"}
    order = {t: i for i, (t, _) in enumerate(TIERS)}
    for key, src in tier_source.items():
        if key not in summaries:
            continue
        w = ward_view(key)
        tiers = ward_view(src).set_index("ward_id")["ffp_tier"]
        v = all_long[(all_long["dataset"] == key) & (all_long["ballot"] == "PR")]
        piv = v.pivot_table(index="unit_id", columns="party", values="votes", aggfunc="sum", fill_value=0)
        cols = [p for p in TABLE_PARTIES if p in piv.columns]
        piv["Other"] = piv.drop(columns=cols).sum(axis=1)
        out = pd.DataFrame({
            "tier": w["ward_id"].map(tiers), "ward_no": w["ward_no"], "area": w["area"],
            "registered": w["registered"].round(), "turnout_pct": w["turnout"].round(1),
            "valid_votes": w["pr_valid"],
        })
        for p in cols + ["Other"]:
            out[f"{p} votes"] = w["ward_id"].map(piv[p]).round().astype(int)
        out["FF+ %"] = w["pr_ffp_share"].round(2)
        out["winner"] = w["pr_winner"]
        out = out.sort_values(["tier", "FF+ votes"], key=lambda c: c.map(order) if c.name == "tier" else -c)
        out.to_csv(OUTPUTS / f"ward_votes_{key}.csv", index=False)


def boundary_of(dataset_key: str) -> int:
    """Which ward map a dataset is on: '2016_own' -> 2016, '2021_on2026' -> 2026."""
    return 2026 if dataset_key.endswith("on2026") else int(dataset_key[:4])


def ward_names() -> dict[int, dict[int, str]]:
    """{boundary year: {ward_id: area name}} from data/tshwane/ward_areas.csv (see ward_names.py)."""
    p = TSH / "ward_areas.csv"
    if not p.exists():
        return {}
    d = pd.read_csv(p)
    return {int(b): dict(zip(g["ward_id"], g["name"])) for b, g in d.groupby("boundary")}


# ---------------------------------------------------------------- report

def citywide(df: pd.DataFrame, ballot="PR") -> pd.Series:
    v = df[df["ballot"] == ballot].groupby("party")["votes"].sum()
    return (v / v.sum() * 100).sort_values(ascending=False)


def md_table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        cells = []
        for c in cols:
            v = r[c]
            cells.append(f"{v:.1f}" if isinstance(v, float) else str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def write_report(res, summaries, ward_view, b, no_cand, stood, cw_stats, vd_cmp, vd21, cands=None) -> None:
    w21 = ward_view("2021_own")
    w16 = ward_view("2016_own")
    cw21, cw16 = citywide(res[2021]), citywide(res[2016])
    L = []
    L.append("# FF+ in Tshwane: baseline report\n")
    L.append("Generated by `pipeline/analyse.py`. Shares are of valid votes on the PR (party list) ballot "
             "unless stated. Source: IEC detailed results files for LGE 2016 and LGE 2021.\n")
    L.append("## City-wide\n")
    L.append(f"- 2016: FF+ {cw16.get(FFP, 0):.2f}% of PR votes ({int(res[2016].query('ballot==\"PR\" and party==@FFP').votes.sum()):,} votes)")
    L.append(f"- 2021: FF+ {cw21.get(FFP, 0):.2f}% of PR votes ({int(res[2021].query('ballot==\"PR\" and party==@FFP').votes.sum()):,} votes)")
    if 2026 in res:
        cw26 = citywide(res[2026])
        L.append(f"- 2026: FF+ {cw26.get(FFP, 0):.2f}% of PR votes ({int(res[2026].query('ballot==\"PR\" and party==@FFP').votes.sum()):,} votes)"
                 f" from {res[2026].vd.nunique()} voting districts counted")
    L.append("")
    L.append("## Support tiers in 2021 (2021 ward boundaries)\n")
    L.append("Tiers: " + ", ".join(f"{t} ≥ {lo:g}%" for t, lo in TIERS[:-1]) + f", {TIERS[-1][0]} < {TIERS[-2][1]:g}%.\n")
    order = [t for t, _ in TIERS]
    g = w21.groupby("ffp_tier").agg(wards=("ward_id", "count"), ffp_votes=("pr_ffp_votes", "sum"),
                                    valid=("pr_valid", "sum"), registered=("registered", "sum")).reindex(order)
    g["ffp_share"] = g["ffp_votes"] / g["valid"] * 100
    g["share_of_ffp_vote"] = g["ffp_votes"] / g["ffp_votes"].sum() * 100
    g = g.reset_index().rename(columns={"ffp_tier": "tier"})
    g[["ffp_votes", "valid", "registered"]] = g[["ffp_votes", "valid", "registered"]].astype(int)
    L.append(md_table(g[["tier", "wards", "ffp_votes", "ffp_share", "share_of_ffp_vote", "registered"]]))
    L.append("")
    for t in order:
        ws = w21[w21["ffp_tier"] == t].sort_values("pr_ffp_share", ascending=False)
        L.append(f"### {t} ({len(ws)} wards)\n")
        L.append(md_table(pd.DataFrame({"ward": ws["ward_no"], "area": ws["area"].fillna(""),
                                        "FF+ votes": ws["pr_ffp_votes"].astype(int), "FF+ %": ws["pr_ffp_share"],
                                        "valid votes": ws["pr_valid"].astype(int), "winner": ws["pr_winner"]})))
        L.append("")
    ranks = w21["pr_ffp_rank"].value_counts()
    L.append(f"FF+ placement on the PR ballot in 2021: first in {int(ranks.get(1, 0))} wards, second in "
             f"{int(ranks.get(2, 0))}, third in {int(ranks.get(3, 0))}. Every Negligible ward was won by "
             + ", ".join(f"{p} ({n})" for p, n in w21[w21["ffp_tier"] == "Negligible"]["pr_winner"].value_counts().items()) + ".\n")
    won = vd21[vd21["pr_winner"] == FFP]
    if len(won):
        L.append(f"Voting districts FF+ won outright in 2021: " + ", ".join(
            f"{r.station.title()} (VD {r.vd}, ward {r.ward_id % 1000}, {r.pr_ffp_share:.1f}%)" for r in won.itertuples()) + ".\n")
    low = set(w21.loc[w21["ffp_tier"].isin(["Marginal", "Negligible"]), "ward_id"])
    pockets = vd21[vd21["ward_id"].isin(low) & (vd21["pr_ffp_share"] >= 5)].sort_values("pr_ffp_share", ascending=False)
    L.append("## Pockets: voting districts with 5%+ FF+ inside Marginal or Negligible wards\n")
    L.append(md_table(pd.DataFrame({"ward": pockets["ward_id"] % 1000, "vd": pockets["vd"],
                                    "station": pockets["station"].str.title(), "FF+ %": pockets["pr_ffp_share"],
                                    "FF+ votes": pockets["pr_ffp_votes"].astype(int)})))
    L.append("")
    L.append("## Growth 2016 → 2021 (both mapped onto 2026 wards)\n")
    top = b.sort_values("growth_16_21_pp", ascending=False).head(15)[
        ["ward_no", "n16_pr_ffp_share", "n21_pr_ffp_share", "growth_16_21_pp", "n21_pr_winner"]]
    L.append(md_table(top.rename(columns={"ward_no": "ward 2026", "n16_pr_ffp_share": "FF+ 2016 %",
                                          "n21_pr_ffp_share": "FF+ 2021 %", "growth_16_21_pp": "change (pp)",
                                          "n21_pr_winner": "2021 winner"})))
    L.append("")
    L.append("## Wards where FF+ had no ward candidate but still got PR votes\n")
    for y in sorted(stood):
        L.append(f"- {y}: FF+ stood a ward candidate in {stood[y]} of {len(ward_view(f'{y}_own'))} wards.")
    if len(no_cand):
        L.append("")
        L.append(md_table(no_cand.assign(pr_ffp_votes=no_cand["pr_ffp_votes"].astype(int))
                          [["year", "ward_no", "pr_ffp_votes", "pr_ffp_share", "pr_winner"]]))
    L.append("\nA party without a candidate in a ward gets 0 ward-ballot votes in the IEC file, so "
             "'stood' means FF+ received at least one ward-ballot vote.\n")
    L.append("## 2026 wards\n")
    L.append(f"The 2026 election uses new ward boundaries (107 wards, many redrawn). 2016 and 2021 results are "
             f"mapped onto them by overlaying voting-district polygons on the 2026 wards and splitting votes by "
             f"area. {cw_stats.get(2021, 0):.0f}% of 2021 PR votes come from voting districts that fall at least "
             f"95% inside one 2026 ward; only the rest is split.\n")
    tb = b.groupby("n21_ffp_tier").agg(wards=("ward_id", "count")).reindex(order)
    L.append("2026 wards by notional 2021 FF+ tier: " + ", ".join(f"{t} {int(n)}" for t, n in tb["wards"].items()) + "\n")
    if cands is not None:
        cw, plist = cands
        L.append("## FF+ candidates in 2026\n")
        L.append(f"FF+ has a ward candidate in {cw['ffp_candidate'].notna().sum()} of {len(cw)} wards "
                 f"({cw['person'].nunique()} different people) and {len(plist)} names on its party list. "
                 "Groups are the 2021 FF+ support, estimated on the 2026 wards.\n")
        order = [t for t, _ in TIERS]
        g = cw.groupby("tier_2021").agg(wards=("ward_no", "count"), people=("person", "nunique"),
                                        multi=("wards_standing", lambda s: int((s > 1).sum())),
                                        on_list=("candidate_pr_position", lambda s: int(s.notna().sum()))).reindex(order).fillna(0).astype(int)
        L.append(md_table(g.reset_index().rename(columns={"tier_2021": "group", "people": "different candidates",
                                                          "multi": "wards whose candidate stands in several wards",
                                                          "on_list": "wards whose candidate is also on the party list"})))
        multi = cw[cw["wards_standing"] > 1].groupby("ffp_candidate")["ward_no"].apply(lambda s: ", ".join(str(int(x)) for x in sorted(s)))
        if len(multi):
            L.append("\nCandidates standing in more than one ward: " + "; ".join(f"{n} (wards {w})" for n, w in multi.items()) + ".\n")
        L.append("### Ward candidates\n")
        L.append(md_table(cw.assign(pr=cw["candidate_pr_position"].astype("string").fillna("–"))[
            ["tier_2021", "ward_no", "area", "ffp_candidate", "pr", "ffp_votes_2021_est", "ffp_share_2021_est"]].rename(
            columns={"tier_2021": "group", "ward_no": "ward", "ffp_candidate": "candidate", "pr": "list #",
                     "ffp_votes_2021_est": "FF+ votes 2021 (est.)", "ffp_share_2021_est": "FF+ % 2021"})))
        L.append("")
    if "swing_pp" in b:
        L.append("## 2021 → 2026 by 2021 tier\n")
        agg = b.groupby("n21_ffp_tier").agg(wards=("ward_id", "count"), ffp_2021=("n21_pr_ffp_votes", "sum"),
                                            ffp_2026=("r26_pr_ffp_votes", "sum"), valid_2021=("n21_pr_valid", "sum"),
                                            valid_2026=("r26_pr_valid", "sum"), complete=("complete", "sum")).reindex(order)
        agg["share_2021"] = agg["ffp_2021"] / agg["valid_2021"] * 100
        agg["share_2026"] = agg["ffp_2026"] / agg["valid_2026"] * 100
        agg["swing_pp"] = agg["share_2026"] - agg["share_2021"]
        agg = agg.reset_index().rename(columns={"n21_ffp_tier": "2021 tier"})
        L.append(md_table(agg[["2021 tier", "wards", "complete", "share_2021", "share_2026", "swing_pp"]]))
        L.append("\nBiggest FF+ gains (pp):\n")
        L.append(md_table(b.dropna(subset=["swing_pp"]).sort_values("swing_pp", ascending=False).head(15)
                          [["ward_no", "n21_ffp_tier", "n21_pr_ffp_share", "r26_pr_ffp_share", "swing_pp", "r26_pr_winner"]]))
        if vd_cmp is not None and len(vd_cmp):
            L.append(f"\nSame-VD check: {len(vd_cmp)} voting districts reported in both years; median FF+ swing "
                     f"{vd_cmp['swing_pp'].median():+.2f} pp.\n")
    (OUTPUTS / "REPORT.md").write_text("\n".join(L) + "\n")


# ---------------------------------------------------------------- web data

def simplify(gdf: gpd.GeoDataFrame, tol=0.00008) -> dict:
    g = gdf.copy()
    g["geometry"] = g.geometry.simplify(tol, preserve_topology=True)
    js = json.loads(g.to_json(drop_id=True))
    def rnd(c):
        return [rnd(x) for x in c] if isinstance(c[0], list) else [round(c[0], 5), round(c[1], 5)]
    for f in js["features"]:
        f["geometry"]["coordinates"] = rnd(f["geometry"]["coordinates"])
    return js


def write_web(res, summaries, all_long, cw_stats, cands=None) -> None:
    names = ward_names()
    areas = pd.read_csv(TSH / "ward_areas.csv") if (TSH / "ward_areas.csv").exists() else None
    geos = {}
    for year in (2016, 2021, 2026):
        g = load_geo(f"wards_{year}")[["ward_id", "geometry"]].rename(columns={"ward_id": "id"})
        g["name"] = g["id"].map(names.get(year, {})).fillna("")
        if areas is not None:
            g["areas"] = g["id"].map(areas[areas["boundary"] == year].set_index("ward_id")["areas"]).fillna("")
        geos[f"wards_{year}"] = g

    # (key, label, ward map, election year, estimated?)
    datasets = [
        ("2016_own", "2016 election", "wards_2016", 2016, False),
        ("2021_own", "2021 election", "wards_2021", 2021, False),
        ("2021_on2026", "2021 election, estimated on 2026 wards", "wards_2026", 2021, True),
    ]
    if 2026 in res:
        datasets.append(("2026_own", "2026 election", "wards_2026", 2026, False))

    # parties shown by name: the key parties plus any that won >= 0.5% city-wide in some election
    own = all_long[(all_long["ballot"] == "PR") & all_long["dataset"].str.endswith("_own")]
    city = own.groupby(["dataset", "party"])["votes"].sum()
    city = (city / city.groupby(level=0).transform("sum") * 100).groupby(level=1).max().sort_values(ascending=False)
    parties = [p for p in KEY_PARTIES if p in city.index]
    parties += [p for p in city[city >= 0.5].index if p not in parties]

    out_ds = []
    for key, label, geo, year, notional_flag in datasets:
        L = all_long[all_long["dataset"] == key]
        s = summaries[key].set_index("unit_id")
        units = {}
        for uid, g in L.groupby("unit_id"):
            rec = {}
            for ballot, gb in g.groupby("ballot"):
                d = {p: int(round(v)) for p, v in zip(gb["party"], gb["votes"]) if p in parties and round(v) > 0}
                other = int(round(gb.loc[~gb["party"].isin(parties), "votes"].sum()))
                if other > 0:
                    d["Other"] = other
                rec["p" if ballot == "PR" else "w"] = d
            if uid in s.index:
                r = s.loc[uid]
                rec["reg"] = int(round(r["registered"])) if pd.notna(r["registered"]) else None
                rec["to"] = round(float(r["turnout"]), 1) if pd.notna(r["turnout"]) else None
                rec["st"] = bool(r["ffp_stood"])
            units[str(int(uid))] = rec
        out_ds.append({"key": key, "label": label, "geo": geo, "year": year, "notional": notional_flag, "units": units})

    data = {
        "parties": parties + ["Other"],
        "tiers": [{"label": t, "min": lo} for t, lo in TIERS],
        "geos": {k: simplify(v) for k, v in geos.items()},
        "datasets": out_ds,
        "notes": {"crosswalk_clean_pct": {str(k): round(v, 1) for k, v in cw_stats.items()}},
        "has2026": 2026 in res,
    }
    if cands is not None:
        cw, plist = cands
        data["candidates"] = {
            "ward": {str(int(r.ward_id)): {"n": r.ffp_candidate, "pr": None if pd.isna(r.candidate_pr_position) else int(r.candidate_pr_position),
                                           "k": int(r.wards_standing), "o": r.other_wards}
                     for r in cw.itertuples() if isinstance(r.ffp_candidate, str)},
            "pr": [[int(r.pr_position), r.name, r.ward_numbers] for r in plist.itertuples()],
        }
    # other parties' 2026 ward candidates (e.g. the DA), keyed by party then 2026 ward ID
    cp = TSH / "candidates_2026.csv"
    if cp.exists():
        c = pd.read_csv(cp)
        pr = c[c["list"] == "PR"].set_index(["party", "person"])["pr_position"]
        other = {}
        for party, g in c[(c["list"] == "Ward") & (c["party"] != FFP)].groupby("party"):
            other[party] = {str(int(r.ward_id)): {"n": r.name, "pr": None if pd.isna(pr.get((party, r.person))) else int(pr.get((party, r.person)))}
                            for r in g.itertuples()}
        if other:
            data.setdefault("candidates", {"ward": {}, "pr": []})["other"] = other
    (WEB / "data.json").write_text(json.dumps(data, separators=(",", ":")))


if __name__ == "__main__":
    main()
