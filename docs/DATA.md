# Data: what we have and what is still needed

## In the repo

| Data | Coverage | Official source | Where we got it |
|---|---|---|---|
| LGE 2021 detailed results (VD × ballot × party) | Gauteng, filtered to Tshwane | IEC results site, "Downloadable results" | GitHub mirror `Don4chnge/Eduvos-Team-DIRISA-2026` (raw IEC CSV, generated 23 Nov 2021) |
| LGE 2016 detailed results | National, filtered to Tshwane | IEC | same mirror (raw IEC CSV, generated 16 Feb 2017) |
| Ward boundaries 2016, 2020 (used in 2021), 2026 | National, filtered to Tshwane | Municipal Demarcation Board | GitHub mirror `j-norwood-young/SA-Maps` |
| Voting district boundaries 2016, 2021, 2026 | National, filtered to Tshwane | IEC | same mirror |
| Suburb (sub-place) boundaries and names | Census 2011, filtered to Tshwane | Stats SA | same mirror |
| FF+ candidate list, LGE 2026 (party list + ward candidates) | Tshwane | IEC certified candidate list, 23 Oct 2026 | supplied by the project owner; ID numbers are not stored |

Checks done: every 2021 result VD (778) matches a 2021 VD polygon; city totals match the
IEC file (FF+ 52,458 PR votes = 7.79%; DA 31.8%); 107 wards in each boundary set.

The IEC and MDB websites were blocked from the environment this was built in, so the
files came from public mirrors of the original IEC/MDB downloads. When you have access,
download the originals and drop them into `data/sources/` (names in `pipeline/fetch.py`)
to rebuild from first-hand copies.

Ward names: findmyward.co.za and gauteng.net were also blocked, so names are generated
from the census suburbs. Paste better names into `data/tshwane/ward_names_override.csv`.

## Still needed

1. **2026 results** (after 4 Nov 2026). The IEC detailed results CSV for Gauteng, or
   per-VD results as they are captured. See README "Election night".
2. Optional: **other parties' candidate lists** (same IEC format), to compare how many
   wards each party contests and with how many different people.
3. **The campaign's target wards.** Which wards the FF+ campaign focused on. With this,
   the report can compare target wards with similar non-target wards.
4. Optional: **by-election results in Tshwane since 2021** (e.g. Ward 57, Jan 2026, where
   FF+ reported 44%). Useful as interim data points.
5. Optional: **2024 national/provincial results per VD for Tshwane** (IEC). A third data
   point on FF+ trends between 2021 and 2026.
