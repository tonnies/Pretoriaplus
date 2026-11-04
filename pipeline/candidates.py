"""Parse IEC candidate lists (text copied from the IEC candidate-list PDF).

Each candidate line looks like:
  TSH - City of Tshwane VRYHEIDSFRONT PLUS | FREEDOM FRONT PLUS 3 641005****08* PETER WYNAND WARNAR MEIJER
The number before the ID is the party-list (PR) position (1, 2, 3 ...) or, for
ward candidates, the 8-digit ward ID (79900052 = Tshwane ward 52). Header and
notice lines are skipped.

The masked ID numbers are used only to tell people apart and are not written
out. Output: data/tshwane/candidates_2026.csv with one row per candidacy:
  party, list (PR | Ward), pr_position, ward_id, ward_no, name, person

Usage:  python pipeline/candidates.py data/sources/candidates/*.txt
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

from common import TSH, WARD_PREFIX, short_party

LINE = re.compile(
    # municipality name ends in a lower-case letter ("City of Tshwane"); party names are in capitals
    r"^(?P<muni>[A-Z]{3}\d* - .*?[a-z])\s+(?P<party>[^a-z]+?)\s+(?P<num>\d{1,8})\s+(?P<id>\d{6}\*{4}\d{2}\*)\s+(?P<name>.+?)\s*$")
PARTICLES = {"van", "der", "den", "de", "du", "le", "la", "von", "ter", "te"}


def nice_name(raw: str) -> str:
    """'LENOR DALEEN JANSE VAN RENSBURG' -> 'Lenor Daleen Janse van Rensburg'."""
    words = []
    for i, w in enumerate(raw.split()):
        lw = w.lower()
        if i > 0 and lw in PARTICLES:
            words.append(lw)
        else:
            words.append("-".join(p[:1].upper() + p[1:].lower() for p in w.split("-")))
    return " ".join(words)


def parse(paths: list[Path]) -> pd.DataFrame:
    rows = []
    for p in paths:
        for line in p.read_text(encoding="utf-8").splitlines():
            m = LINE.match(line.strip())
            if not m:
                continue
            party_raw = m["party"].split("|")[0].strip()
            num = int(m["num"])
            is_ward = num >= 10_000_000
            rows.append({
                "muni": m["muni"][:3], "party": short_party(party_raw),
                "list": "Ward" if is_ward else "PR",
                "pr_position": None if is_ward else num,
                "ward_id": num if is_ward else None,
                "name": nice_name(m["name"]),
                "_id": m["id"],
            })
    df = pd.DataFrame(rows)
    df = df[df["muni"] == "TSH"].drop(columns="muni")
    # one person = same masked ID + same name
    df["person"] = df.groupby(["_id", "name"]).ngroup() + 1
    clash = df.groupby("name")["_id"].nunique()
    for n in clash[clash > 1].index:
        print(f"note: two different people are both called {n}")
    df["ward_no"] = df["ward_id"].where(df["ward_id"].isna(), df["ward_id"] % 1000)
    bad = df[(df["list"] == "Ward") & (df["ward_id"] // 100000 != WARD_PREFIX)]
    if len(bad):
        raise SystemExit(f"ward IDs outside Tshwane: {bad['ward_id'].tolist()[:5]}")
    df = df.drop(columns="_id")
    for c in ("pr_position", "ward_id", "ward_no"):
        df[c] = df[c].astype("Int64")
    return df.sort_values(["party", "list", "pr_position", "ward_no"]).reset_index(drop=True)


def main(args: list[str]) -> int:
    if not args:
        print(__doc__)
        return 1
    df = parse([Path(a) for a in args])
    out = TSH / "candidates_2026.csv"
    df.to_csv(out, index=False)
    for party, g in df.groupby("party"):
        w = g[g["list"] == "Ward"]
        print(f"{party}: {int((g['list'] == 'PR').sum())} on the PR list, {w['ward_no'].nunique()} wards, "
              f"{w['person'].nunique()} different ward candidates")
    print(f"-> {out.relative_to(TSH.parents[1])}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
