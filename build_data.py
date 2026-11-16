"""Build the app's data files.

Sources
  - 2022 and 2024: precinct-level tabs in the original Excel workbook
  - 2026: MN Secretary of State results files (electionresultsfiles.sos.mn.gov/20261103/)
  - Maps: LCC current legislative districts (gis.lcc.mn.gov/data/geojson/L2023_0hse.zip, L2023_0sen.zip)

Usage
  python build_data.py --workbook MNElectionsDatabase.xlsx --sos-dir raw/ --geo-dir geo/

Re-run after the State Canvassing Board certifies results to swap unofficial 2026 numbers
for official ones (re-download allracesbyprecinct.txt first).
"""
import argparse
import json
import re
from pathlib import Path

import openpyxl
import pandas as pd
from shapely.geometry import MultiPolygon, mapping, shape
from shapely.geometry.polygon import orient

OUT = Path(__file__).parent / "data"

# Normalize office names across years
OFFICES = {
    "U.S. President & Vice President": "President",
    "U.S. Senator": "U.S. Senate",
    "U.S. Representative": "U.S. House",
    "Governor & Lt Governor": "Governor",
    "Attorney General": "Attorney General",
    "Secretary of State": "Secretary of State",
    "State Auditor": "State Auditor",
    "State Senator": "State Senate",
    "State Representative": "State House",
}


def norm_hd(v):
    """'01A' / '1A' -> '1A'; anything unparseable -> None."""
    m = re.fullmatch(r"0*(\d+)([AB])", str(v).strip().upper())
    return f"{int(m.group(1))}{m.group(2)}" if m else None


def split_office(raw):
    """'U.S. Representative District 8' -> ('U.S. House', '8')."""
    m = re.match(r"(.*?)(?: District (\w+))?$", str(raw).strip())
    return OFFICES.get(m.group(1)), m.group(2)


def workbook_results(wb):
    """Precinct rows from the workbook's raw-data tabs, aggregated to House district."""
    specs = {  # tab: (year, office col, HD col, name col, party col, votes col)
        "2022 Raw Data": (2022, 7, 4, 8, 9, 10),
        "2024 Raw Data": (2024, 3, 4, 6, 7, 8),
    }
    rows = []
    for tab, (year, oc, hc, nc, pc, vc) in specs.items():
        for r in wb[tab].iter_rows(min_row=2, values_only=True):
            office, odist = split_office(r[oc]) if r[oc] else (None, None)
            hd = norm_hd(r[hc])
            if office and hd:
                rows.append((year, hd, office, odist, r[nc], r[pc], r[vc] or 0))
    return rows


def sos_results(path):
    """2026 SOS precinct file -> rows aggregated to House district.

    Statewide/federal rows don't carry a legislative district, so each precinct is mapped
    to its House district using that precinct's State Representative rows.
    """
    cols = ["state", "county", "precinct", "office_id", "office", "district", "cand_id", "name",
            "suffix", "incumbent", "party", "rep", "tot", "votes", "pct", "office_total"]
    df = pd.read_csv(path, sep=";", header=None, names=cols, dtype=str, encoding="latin-1")
    df["votes"] = df["votes"].astype(int)
    df["pkey"] = df["county"] + "-" + df["precinct"]
    sh = df[df["office"].str.startswith("State Representative")]
    pct_to_hd = sh.drop_duplicates("pkey").set_index("pkey")["district"].map(norm_hd)
    df["hd"] = df["pkey"].map(pct_to_hd)
    split = df["office"].map(split_office)
    df["office_n"] = split.str[0]
    df["odist"] = split.str[1]
    df = df[df["office_n"].notna() & df["hd"].notna()]
    return [(2026, r.hd, r.office_n, r.odist, r.name, r.party, r.votes) for r in df.itertuples()]


def tidy_results(rows):
    df = pd.DataFrame(rows, columns=["year", "hd", "office", "office_district", "candidate", "party", "votes"])
    df["party"] = df["party"].fillna("").str.upper().replace({"GOP": "R", "REP": "R"})
    df["candidate"] = df["candidate"].fillna("").str.strip()
    df["office_district"] = df["office_district"].fillna("").astype(str).str.lstrip("0")
    df["sd"] = df["hd"].str[:-1].astype(int)
    return (df.groupby(["year", "hd", "sd", "office", "office_district", "candidate", "party"], as_index=False)
              ["votes"].sum())


def turnout(wb):
    h = pd.DataFrame(list(wb["House Turnout"].iter_rows(min_row=2, max_col=15, values_only=True)))
    h = h[[0, 1, 2, 3, 4, 5, 6, 7, 12, 13, 14]]
    h.columns = ["district", "t2024", "t2022", "t2020", "t2018", "t2016", "t2014", "t2012",
                 "voters", "projected_ballots", "win_number"]
    h["district"] = h["district"].map(norm_hd)
    h["chamber"] = "House"
    s = pd.DataFrame(list(wb["Senate Turnout"].iter_rows(min_row=2, max_col=20, values_only=True)))
    s = s[[0, 1, 2, 3, 4, 5, 6, 7, 17, 18, 19]]
    s.columns = h.columns[:-1].tolist()
    s["district"] = pd.to_numeric(s["district"], errors="coerce").astype("Int64").astype(str)
    s["chamber"] = "Senate"
    out = pd.concat([h, s]).dropna(subset=["district"])
    return out[out["district"].ne("<NA>")]


def ie(wb):
    rows = []
    for r in wb["2024 House IE Sums"].iter_rows(min_row=2, max_col=12, values_only=True):
        r = list(r) + [None] * 12  # read-only mode trims trailing empty cells
        for d, p, c, a, f in ((r[0], r[1], r[2], r[3], r[4]), (r[6], r[7], r[8], r[9], r[10])):
            if d and norm_hd(d):
                rows.append(("House", 2024, norm_hd(d), c, p, f or 0, a or 0))
    for r in wb["2022 Senate IE sums"].iter_rows(min_row=2, max_col=11, values_only=True):
        r = list(r) + [None] * 12
        for d, c, p, a, f in ((r[0], r[1], r[2], r[3], r[4]), (r[6], r[7], r[8], r[9], r[10])):
            if d:
                rows.append(("Senate", 2022, str(int(d)), c, p, f or 0, a or 0))
    return pd.DataFrame(rows, columns=["chamber", "cycle", "district", "candidate", "party", "for_amt", "against_amt"])


def locations(wb):
    rows = []
    for r in wb["District Locations & Other Fun "].iter_rows(min_row=2, max_col=5, values_only=True):
        r = list(r) + [None] * 5
        if r[0] and norm_hd(r[0]):
            rows.append(("House", norm_hd(r[0]), r[1]))
        if r[3]:
            rows.append(("Senate", str(int(r[3])), r[4]))
    return pd.DataFrame(rows, columns=["chamber", "district", "location"])


def simplify_geo(src, dest, is_house):
    gj = json.load(open(src))
    feats = []
    for f in gj["features"]:
        d = f["properties"]["DISTRICT"]
        geom = shape(f["geometry"]).simplify(0.002, preserve_topology=True)
        # Plotly's geo maps (d3) need clockwise outer rings, the reverse of the GeoJSON spec
        polys = geom.geoms if geom.geom_type == "MultiPolygon" else [geom]
        geom = MultiPolygon([orient(p, sign=-1.0) for p in polys])
        g = json.loads(json.dumps(mapping(geom)), parse_float=lambda x: round(float(x), 4))
        feats.append({"type": "Feature", "id": norm_hd(d) if is_house else str(int(d)),
                      "properties": {}, "geometry": g})
    json.dump({"type": "FeatureCollection", "features": feats}, open(dest, "w"), separators=(",", ":"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workbook", required=True)
    ap.add_argument("--sos-dir", required=True)
    ap.add_argument("--geo-dir", required=True)
    a = ap.parse_args()
    OUT.mkdir(exist_ok=True)

    wb = openpyxl.load_workbook(a.workbook, data_only=True, read_only=True)
    rows = workbook_results(wb) + sos_results(Path(a.sos_dir) / "allracesbyprecinct.txt")
    tidy_results(rows).to_csv(OUT / "results.csv", index=False)
    turnout(wb).to_csv(OUT / "turnout.csv", index=False)
    ie(wb).to_csv(OUT / "ie.csv", index=False)
    locations(wb).to_csv(OUT / "locations.csv", index=False)

    geo = Path(a.geo_dir)
    simplify_geo(geo / "L2023_0hse.geojson", OUT / "house.geojson", True)
    simplify_geo(geo / "L2023_0sen.geojson", OUT / "senate.geojson", False)
    print("Wrote", *sorted(p.name for p in OUT.iterdir()))


if __name__ == "__main__":
    main()
