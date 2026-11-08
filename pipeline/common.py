"""Shared paths, party names and the IEC results reader."""
from __future__ import annotations

import os
import re
from pathlib import Path

import pandas as pd

# PRETORIAPLUS_ROOT lets tests run the pipeline on a temporary copy of the data
ROOT = Path(os.environ.get("PRETORIAPLUS_ROOT", Path(__file__).resolve().parents[1]))
SOURCES = ROOT / "data" / "sources"
TSH = ROOT / "data" / "tshwane"
GEO = TSH / "geo"
RESULTS = TSH / "results"
OUTPUTS = ROOT / "outputs"
WEB = ROOT / "web"

MUNI_CODE = "TSH"
WARD_PREFIX = 799  # Tshwane ward IDs are 79900001 .. 79900107

# Metric CRS for areas/overlays (UTM 35S covers Tshwane)
METRIC_CRS = "EPSG:32735"

FFP = "FF+"

# IEC party name -> short label used everywhere in this project.
PARTY_SHORT = {
    "VRYHEIDSFRONT PLUS": FFP,
    "FREEDOM FRONT PLUS": FFP,
    "DEMOCRATIC ALLIANCE": "DA",
    "AFRICAN NATIONAL CONGRESS": "ANC",
    "ECONOMIC FREEDOM FIGHTERS": "EFF",
    "ACTIONSA": "ActionSA",
    "AFRICAN CHRISTIAN DEMOCRATIC PARTY": "ACDP",
    "CONGRESS OF THE PEOPLE": "COPE",
    "PATRIOTIC ALLIANCE": "PA",
    "INKATHA FREEDOM PARTY": "IFP",
    "CHRISTIAN DEMOCRATIC PARTY": "CDP",
    "UNITED DEMOCRATIC MOVEMENT": "UDM",
    "PAN AFRICANIST CONGRESS OF AZANIA": "PAC",
    "AFRICAN TRANSFORMATION MOVEMENT": "ATM",
    "SOUTH AFRICAN COMMUNIST PARTY": "SACP",
    "GOOD": "GOOD",
    "INDEPENDENT": "Independent",
    "UMKHONTO WESIZWE": "MK",
    "UMKHONTO WESIZWE PARTY": "MK",
    "UMKHONTO WE SIZWE": "MK",
    "BUILD ONE SOUTH AFRICA": "BOSA",
    "BUILD ONE SOUTH AFRICA WITH MMUSI MAIMANE": "BOSA",
    "RISE MZANSI": "Rise Mzansi",
    "AFRICAN CHRISTIAN ALLIANCE-AFRIKANER CHRISTEN ALLIANSIE": "ACA",
    "AZANIAN PEOPLE'S ORGANISATION": "AZAPO",
    "AFRICAN INDEPENDENT CONGRESS": "AIC",
    "REPUBLICAN CONFERENCE OF TSHWANE": "RCT",
    "AL JAMA-AH": "Al Jama-ah",
    "AFRICAN COVENANT": "African Covenant",
    "FEDERAL PARTY SA": "Federal Party",
}


def short_party(name: str) -> str:
    # 2026 files give both names: "VRYHEIDSFRONT PLUS | FREEDOM FRONT PLUS"
    names = [re.sub(r"\s+", " ", n).strip().upper() for n in str(name).split("|")]
    for n in names:
        if n in PARTY_SHORT:
            return PARTY_SHORT[n]
    key = names[0]
    if key in PARTY_SHORT:
        return PARTY_SHORT[key]
    if key.startswith("UMKHONTO"):
        return "MK"
    return " ".join(w.capitalize() for w in key.split())


def read_iec_results(path: Path | str, year: int) -> pd.DataFrame:
    """Read an IEC 'detailed results' CSV and return tidy Tshwane rows.

    Works for the 2016 and 2021 files, and for the 2026 file as long as the IEC
    keeps the same columns (Municipality, Ward, VotingDistrict, BallotType,
    PartyName, TotalValidVotes, RegisteredVoters, SpoiltVotes).
    """
    df = pd.read_csv(path, encoding="utf-8-sig", low_memory=False, dtype=str)
    df.columns = [c.strip() for c in df.columns]
    df = df[df["Municipality"].str.strip().str.upper().str.startswith(MUNI_CODE)]
    out = pd.DataFrame(
        {
            "year": year,
            "ward_id": df["Ward"].str.extract(r"(\d+)")[0].astype(int),
            "vd": df["VotingDistrict"].str.strip().astype(int),
            "station": df["VotingStationName"].str.strip(),
            "registered": pd.to_numeric(df["RegisteredVoters"], errors="coerce").fillna(0).astype(int),
            "ballot": df["BallotType"].str.strip().str.title(),  # "Pr" / "Ward"
            "spoilt": pd.to_numeric(df["SpoiltVotes"], errors="coerce").fillna(0).astype(int),
            "party_iec": df["PartyName"].str.strip(),
            "votes": pd.to_numeric(df["TotalValidVotes"], errors="coerce").fillna(0).astype(int),
        }
    )
    out["ballot"] = out["ballot"].replace({"Pr": "PR"})
    out = out[out["ballot"].isin(["PR", "Ward"])]
    out["party"] = out["party_iec"].map(short_party)
    out["ward_no"] = out["ward_id"] % 1000
    return out.reset_index(drop=True)
