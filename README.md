# Pretoriaplus: Tshwane election tracker

Ward-level analysis of the City of Tshwane local government elections, built to
compare the 2016 and 2021 results with the 4 November 2026 election, with a
focus on the Freedom Front Plus (FF+ / Vryheidsfront Plus).

- `outputs/REPORT.md`: the baseline findings (support tiers, growth, pockets, no-candidate wards)
- `web/index.html`: a self-contained 3D ward map (open it in a browser)
- `outputs/*.csv`: the tables behind both

## Quick start

```bash
pip install -r requirements.txt
python pipeline/analyse.py      # tables + report + web/data.json (uses committed Tshwane data)
python pipeline/build_web.py    # web/index.html
python -m pytest -q tests       # checks, including the 2026 flow on synthetic data
```

To rebuild the Tshwane data from the national source files:

```bash
python pipeline/fetch.py        # ~370 MB into data/sources/ (not committed)
python pipeline/prepare.py      # cuts it down to Tshwane: data/tshwane/
```

## Election night / after 4 November 2026

1. Download the IEC detailed results file for Gauteng from
   <https://results.elections.org.za/home/downloads/me-results> (same layout as 2016/2021).
   A hand-typed file of results slips also works: see `data/templates/results_2026_template.csv`.
2. `python pipeline/ingest_2026.py path/to/file.csv [more files...]`
   Later files replace earlier ones for the same voting district, so you can re-run as results arrive.
3. `python pipeline/analyse.py && python pipeline/build_web.py`

This adds 2026 columns, the swing per ward (`outputs/ffplus_wards_2026_comparison.csv`),
a same-voting-district comparison (`outputs/ffplus_vd_2021_vs_2026.csv`), a
"2021 → 2026 by tier" table in the report, and the 2026 and change views on the map.
Partial results are handled: each 2026 ward shows `vds_counted` vs `vds_expected`.

## Method

**Unit of analysis.** The IEC reports results per voting district (VD), per ballot, per
party. Tshwane had 732 VDs in 2016, 778 in 2021 and 796 in 2026, across 107 wards each time.

**Two ballots.** Every voter casts a PR (party list) ballot and a ward ballot. The PR ballot
offers the same parties everywhere, so FF+ support is measured on the PR ballot. The ward
ballot is used to tell whether FF+ had a ward candidate: a party without a candidate gets
zero ward-ballot votes in the IEC file.

**Support tiers** (FF+ share of the PR vote in the ward): Stronghold ≥ 15%, Solid 5–15%,
Marginal 1–5%, Negligible < 1%. Thresholds are in `pipeline/analyse.py` (`TIERS`).

**2026 boundaries.** The 2026 wards were redrawn (still 107 wards). To compare like with
like, 2016 and 2021 VD results are overlaid on the 2026 wards and split by area
(`outputs/crosswalk_vd*_to_wards2026.csv`). 85% of 2021 PR votes come from VDs that sit at
least 95% inside a single 2026 ward, so only a small share of votes is estimated. As a
check that needs no estimation, the 759 VDs that exist in both 2021 and 2026 are also
compared directly.

## Layout

```
pipeline/   fetch → prepare → (ingest_2026) → analyse → build_web
data/tshwane/results/   tidy VD-level results per election (committed, small)
data/tshwane/geo/       ward + VD boundaries per election (GeoJSON)
data/templates/         template for hand-entered 2026 results
outputs/                generated tables and REPORT.md
web/                    template.html → index.html (3D map, deck.gl)
docs/DATA.md            sources, gaps, and what is still needed
```
