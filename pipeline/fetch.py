"""Download the source files into data/sources/.

The official sources are the IEC (results.elections.org.za) and the Municipal
Demarcation Board (demarcation.org.za). Their download pages are not scriptable
(and may be blocked on some networks), so this script pulls byte-identical
copies of the IEC/MDB files from public GitHub mirrors. If you download the
files from the IEC yourself, drop them in data/sources/ under the names below
and this script will skip them.

Usage:  python pipeline/fetch.py
"""
from __future__ import annotations

import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "data" / "sources"

EDUVOS = "https://raw.githubusercontent.com/Don4chnge/Eduvos-Team-DIRISA-2026/main/data/raw"
SAMAPS = "https://media.githubusercontent.com/media/j-norwood-young/SA-Maps/master"

# local name -> (url, official origin)
SOURCES: dict[str, tuple[str, str]] = {
    # IEC "Downloadable results" CSVs: one row per voting district x ballot x party
    "results_2021_GP.csv.zip": (
        f"{EDUVOS}/2021_provincial/GP.csv.zip",
        "IEC LGE 2021 detailed results, Gauteng (results.elections.org.za/home/downloads/me-results)",
    ),
    "results_2016_national.csv.zip": (
        f"{EDUVOS}/2016_LGE.csv.zip",
        "IEC LGE 2016 detailed results, national (results.elections.org.za/home/downloads/me-results)",
    ),
    # MDB 2020 ward boundaries (used for the 2021 election)
    "wards_2020/MDB_Wards_2020.shp": (f"{SAMAPS}/Wards/2020/MDB_Wards_2020.shp", "MDB wards 2020"),
    "wards_2020/MDB_Wards_2020.shx": (f"{SAMAPS}/Wards/2020/MDB_Wards_2020.shx", "MDB wards 2020"),
    "wards_2020/MDB_Wards_2020.dbf": (f"{SAMAPS}/Wards/2020/MDB_Wards_2020.dbf", "MDB wards 2020"),
    "wards_2020/MDB_Wards_2020.prj": (f"{SAMAPS}/Wards/2020/MDB_Wards_2020.prj", "MDB wards 2020"),
    # MDB 2026 ward boundaries (used for the 4 Nov 2026 election)
    "wards_2026/Wards_2026.shp": (f"{SAMAPS}/Wards/2026/Wards_2026.shp", "MDB/IEC wards 2026"),
    "wards_2026/Wards_2026.shx": (f"{SAMAPS}/Wards/2026/Wards_2026.shx", "MDB/IEC wards 2026"),
    "wards_2026/Wards_2026.dbf": (f"{SAMAPS}/Wards/2026/Wards_2026.dbf", "MDB/IEC wards 2026"),
    "wards_2026/Wards_2026.prj": (f"{SAMAPS}/Wards/2026/Wards_2026.prj", "MDB/IEC wards 2026"),
    # IEC voting district boundaries (2016 zip also contains the 2016 wards)
    "vd_2016.zip": (f"{SAMAPS}/Voting%20Districts/2016.zip", "IEC voting districts 2016"),
    "vd_2021.zip": (f"{SAMAPS}/Voting%20Districts/2021.zip", "IEC voting districts 2021"),
    "vd_2026.zip": (f"{SAMAPS}/Voting%20Districts/2026.zip", "IEC voting districts 2026"),
}


def download(url: str, out: Path) -> None:
    # media.githubusercontent.com only serves Git LFS objects; plain files 404
    # there and live on raw.githubusercontent.com instead.
    candidates = [url]
    if url.startswith("https://media.githubusercontent.com/media/"):
        candidates.append(url.replace("https://media.githubusercontent.com/media/", "https://raw.githubusercontent.com/"))
    for i, u in enumerate(candidates):
        try:
            with urllib.request.urlopen(u, timeout=600) as r, open(out, "wb") as f:
                while chunk := r.read(1 << 20):
                    f.write(chunk)
            return
        except urllib.error.HTTPError as e:
            if e.code != 404 or i == len(candidates) - 1:
                raise


def main() -> int:
    DEST.mkdir(parents=True, exist_ok=True)
    for name, (url, origin) in SOURCES.items():
        out = DEST / name
        if out.exists() and out.stat().st_size > 1024 or (out.suffix == ".prj" and out.exists()):
            print(f"skip  {name}")
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        print(f"fetch {name}  <- {origin}")
        download(url, out)
        if out.stat().st_size < 300 and out.read_bytes().startswith(b"version https://git-lfs"):
            print(f"  ERROR: got a Git LFS pointer instead of the file for {name}", file=sys.stderr)
            return 1
    print(f"done -> {DEST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
