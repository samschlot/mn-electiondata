"""Minnesota Election Results & Shifts (2022-2026).

Run with:  streamlit run app.py
Data is built by build_data.py into ./data.
"""
import json
import re
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

DATA = Path(__file__).parent / "data"
YEARS = [2022, 2024, 2026]
DFL_BLUE, GOP_RED, NEUTRAL = "#2f6bd8", "#d33a32", "#e9e8e4"
# Diverging scale: R red -> neutral gray at 50% -> DFL blue
DIVERGING = [[0, "#a8231d"], [0.3, "#e8857e"], [0.5, NEUTRAL], [0.7, "#7fa6ec"], [1, "#1c4aa6"]]
OFFICE_ORDER = ["President", "Governor", "U.S. Senate", "Attorney General", "Secretary of State",
                "State Auditor", "U.S. House", "State Senate", "State House"]
# Klobuchar was on the 2024 ballot for U.S. Senate; the sidebar toggle drops that race from 2024 metrics
KLOBUCHAR_2024_RACE = "U.S. Senate"
MAP_OPTIONS = ["2026 DFL Performance", "2024 → 2026 shift", "2026 legislative winner"]

st.set_page_config(page_title="MN Election Results & Shifts", page_icon="🗳️", layout="wide")


# ---------- data ----------

def dist_sort_key(d):
    m = re.fullmatch(r"(\d+)([AB]?)", str(d))
    return (int(m.group(1)), m.group(2))


@st.cache_data
def load():
    res = pd.read_csv(DATA / "results.csv", dtype={"hd": str, "office_district": str})
    res["office_district"] = res["office_district"].fillna("")
    res["sd"] = res["sd"].astype(str)
    turnout = pd.read_csv(DATA / "turnout_sos.csv", dtype={"hd": str, "sd": str})
    loc = pd.read_csv(DATA / "locations.csv", dtype={"district": str})
    geo = {c: json.load(open(DATA / f"{c.lower()}.geojson")) for c in ("House", "Senate")}
    return res, turnout, loc, geo


def key_col(chamber):
    return "hd" if chamber == "House" else "sd"


def dfl_perf(res, key, exclude=None):
    """DFL share of all votes cast across every partisan race (the workbook's 'DFL Performance')."""
    d = res if exclude is None else res[res["office"] != exclude]
    g = d.groupby(["year", key])
    return (d[d["party"] == "DFL"].groupby(["year", key])["votes"].sum() / g["votes"].sum()).fillna(0)


def leg_winners(res, chamber):
    """Winner, margin and contested flag for each district's own legislative race, by year."""
    key, office = key_col(chamber), f"State {chamber}"
    d = res[res["office"] == office]
    rows = []
    for (year, dist), g in d.groupby(["year", key]):
        # Senate rows are split by House district (A/B), so total each candidate before picking the winner
        by_cand = g.groupby(["candidate", "party"], as_index=False)["votes"].sum()
        by_party = g.groupby("party")["votes"].sum()
        total = g["votes"].sum()
        top = by_cand.sort_values("votes", ascending=False).iloc[0]
        dfl, gop = by_party.get("DFL", 0), by_party.get("R", 0)
        rows.append({"year": year, "district": dist, "winner": top["candidate"], "winner_party": top["party"],
                     "dfl_pct": dfl / total, "r_pct": gop / total, "contested": dfl > 0 and gop > 0})
    return pd.DataFrame(rows)


@st.cache_data
def district_table(chamber, sans_klobuchar):
    """One row per district: DFL Performance by year, the 2024 -> 2026 shift, and legislative winners."""
    res = load()[0]
    key = key_col(chamber)
    p = dfl_perf(res, key).unstack(0)
    p.columns = [f"perf_{y}" for y in p.columns]
    if sans_klobuchar:
        p["perf_2024"] = dfl_perf(res[res["year"] == 2024], key, exclude=KLOBUCHAR_2024_RACE).unstack(0)[2024]
    p["shift_24_26"] = p["perf_2026"] - p["perf_2024"]
    w = leg_winners(res, chamber)
    for y in YEARS:
        wy = w[w["year"] == y].set_index("district")
        p[f"winner_{y}"] = wy["winner"]
        p[f"party_{y}"] = wy["winner_party"]
        p[f"contested_{y}"] = wy["contested"]
        p[f"leg_dfl_{y}"] = wy["dfl_pct"]
    p.index.name = "district"
    p = p.reset_index()
    return p.iloc[sorted(range(len(p)), key=lambda i: dist_sort_key(p["district"].iat[i]))].reset_index(drop=True)



def race_table(res, chamber, district, year):
    """DFL vs R result for every race in a district for one year."""
    key = key_col(chamber)
    d = res[(res["year"] == year) & (res[key] == district)].copy()
    # In the Senate view, show each House race (A and B) separately
    d["race"] = d["office"]
    cd = d["office"] == "U.S. House"
    d.loc[cd, "race"] = "U.S. House (CD " + d.loc[cd, "office_district"] + ")"
    if chamber == "Senate":
        hs = d["office"] == "State House"
        d.loc[hs, "race"] = "State House " + d.loc[hs, "hd"]
    rows = []
    for race, g in d.groupby("race"):
        total = g["votes"].sum()
        row = {"Race": race, "order": OFFICE_ORDER.index(g["office"].iat[0])}
        for party, label in (("DFL", "DFL"), ("R", "Republican")):
            gp = g[g["party"] == party]
            if len(gp):
                top = gp.groupby("candidate")["votes"].sum().idxmax()
                row[label] = top
                row[f"{label} %"] = gp["votes"].sum() / total
            else:
                row[label], row[f"{label} %"] = "(no candidate)", None
        row["Other %"] = 1 - (row["DFL %"] or 0) - (row["Republican %"] or 0)
        row["Total votes"] = total
        rows.append(row)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["order", "Race"]).drop(columns="order")


def turnout_table(turnout, chamber, district):
    """One row per year: registered voters, ballots cast and turnout from SOS precinct statistics."""
    s = turnout[turnout[key_col(chamber)] == district].groupby("year")[["registered", "ballots"]].sum()
    s["turnout"] = s["ballots"] / s["registered"]
    s = s.sort_index(ascending=False).reset_index()
    s["year"] = s["year"].astype(str).where(s["year"] != 2026, "2026 (unofficial)")
    return s.rename(columns={"year": "Year", "registered": "Registered voters", "ballots": "Ballots cast",
                             "turnout": "Turnout"})


def pct(v, signed=False, digits=1):
    if v is None or pd.isna(v):
        return "—"
    return f"{v * 100:+.{digits}f}" if signed else f"{v * 100:.{digits}f}%"


def shift_text(v):
    """0.012 -> 'Shifted 1.2 points more blue from 2024'."""
    if v is None or pd.isna(v):
        return "No 2024 comparison"
    if round(abs(v) * 100, 1) == 0:
        return "No change from 2024"
    return f"Shifted {abs(v) * 100:.1f} points more {'blue' if v > 0 else 'red'} from 2024"


def party_label(p):
    return {"DFL": "DFL", "R": "Republican"}.get(p, p or "—")


# ---------- views ----------

res, turnout, loc, geo = load()
SURFACE_NOTE = ("2026 results are **unofficial** (MN Secretary of State, all precincts reporting) until the "
                "State Canvassing Board certifies them. Re-run `build_data.py` afterward to refresh.")

st.title("Minnesota Election Results & Shifts")
st.caption(SURFACE_NOTE)

with st.sidebar:
    st.header("District")
    chamber = st.radio("Chamber", ["House", "Senate"], horizontal=True)
    sans_klobuchar = st.toggle("Exclude Klobuchar from 2024", key="sans_klobuchar",
                               help="Drops the 2024 U.S. Senate race (Klobuchar) from every 2024 DFL Performance "
                                    "number and the 2024 → 2026 shift.")
    table = district_table(chamber, sans_klobuchar)
    districts = table["district"].tolist()
    dkey = f"district_{chamber}"
    if dkey not in st.session_state:
        st.session_state[dkey] = "36A" if chamber == "House" else "24"
    district = st.selectbox("District", districts, key=dkey,
                            format_func=lambda d: f"{'HD' if chamber == 'House' else 'SD'} {d}")
    compare = st.selectbox("Compare to", ["(none)"] + [d for d in districts if d != district],
                           key=f"compare_{chamber}")
    st.divider()
    map_metric = st.selectbox("Map", MAP_OPTIONS)
    st.caption("Click a district on the map to open it.")

PERF_2024_LABEL = "2024 DFL Perf." + (" (sans Klobuchar)" if sans_klobuchar else "")
row = table.set_index("district").loc[district]
tab_district, tab_all, tab_state = st.tabs(["District view", "All districts", "Statewide summary"])

# ---- District view ----
with tab_district:
    map_col, info_col = st.columns([1, 1], gap="large")

    with map_col:
        m = table.copy()
        if map_metric == "2026 DFL Performance":
            m["value"] = m["perf_2026"]
            scale, rng = DIVERGING, (0.25, 0.75)
        elif map_metric == "2024 → 2026 shift":
            m["value"] = m["shift_24_26"]
            scale, rng = DIVERGING, (-0.12, 0.12)
        else:
            m["value"] = m["party_2026"].map({"DFL": 1.0, "R": 0.0}).fillna(0.5)
            scale, rng = [[0, GOP_RED], [0.5, NEUTRAL], [1, DFL_BLUE]], (0, 1)
        m["label"] = ("House District " if chamber == "House" else "Senate District ") + m["district"]
        m["winner"] = m["winner_2026"].fillna("—") + " (" + m["party_2026"].fillna("—") + ")"
        m["perf"] = m["perf_2026"].map(pct)
        m["shift"] = m["shift_24_26"].map(shift_text)
        fig = px.choropleth(
            m, geojson=geo[chamber], locations="district", color="value",
            color_continuous_scale=scale, range_color=rng, custom_data=["winner", "label", "perf", "shift"],
        )
        fig.update_traces(hovertemplate=(
            "<b>%{customdata[0]}</b><br>"
            "<span style='color:#6b6b66;font-size:11px'>%{customdata[1]}</span><br><br>"
            "2026 DFL Performance: %{customdata[2]}<br>"
            "%{customdata[3]}<extra></extra>"
        ))
        fig.update_layout(hoverlabel=dict(bgcolor="white", bordercolor="#d6d5d0", align="left",
                                          font=dict(size=13, color="#1f1f1c")))
        # Outline the selected district
        sel = m[m["district"] == district]
        fig.add_trace(go.Choropleth(geojson=geo[chamber], locations=sel["district"], z=[1],
                                    colorscale=[[0, "rgba(0,0,0,0)"], [1, "rgba(0,0,0,0)"]],
                                    marker_line_color="#111", marker_line_width=2.5, showscale=False,
                                    hoverinfo="skip"))
        fig.update_geos(fitbounds="locations", visible=False, projection_type="mercator")
        fig.update_layout(height=560, margin=dict(l=0, r=0, t=0, b=0),
                          coloraxis_colorbar=dict(title="", thickness=10, len=0.6,
                                                  tickformat="+.0%" if "shift" in map_metric else ".0%"),
                          coloraxis_showscale=map_metric != "2026 legislative winner")
        fig.update_traces(marker_line_width=0.4, marker_line_color="white", selector=0)
        fig.update_traces(unselected=dict(marker_opacity=1))  # don't dim the map after a click
        def open_clicked_district():
            # Runs before the next rerun, so it may set the sidebar selectbox's value
            pts = st.session_state[f"map_{chamber}"]["selection"]["points"]
            clicked = pts[0].get("location") if pts else None
            if clicked in districts:
                st.session_state[dkey] = clicked

        st.plotly_chart(fig, on_select=open_clicked_district, selection_mode="points", key=f"map_{chamber}",
                        config={"scrollZoom": True, "displayModeBar": False})
        st.caption("Scroll or pinch to zoom into the metro. Gray = near 50/50.")

    with info_col:
        label = f"{'House District' if chamber == 'House' else 'Senate District'} {district}"
        place = loc[(loc["chamber"] == chamber) & (loc["district"] == district)]["location"]
        st.subheader(label)
        if len(place):
            st.caption(place.iat[0])

        w26, p26 = row["winner_2026"], row["party_2026"]
        prev_year = 2024 if chamber == "House" else 2022
        flipped = pd.notna(row[f"party_{prev_year}"]) and row[f"party_{prev_year}"] != p26
        st.markdown(
            f"**2026 winner:** {w26} ({party_label(p26)})"
            + (f" — **flipped** from {party_label(row[f'party_{prev_year}'])}" if flipped else "")
            + ("" if row["contested_2026"] else "  \n*Uncontested by one major party in 2026.*")
        )

        c1, c2, c3 = st.columns(3)
        c1.metric("2022 DFL Perf.", pct(row["perf_2022"]))
        c2.metric(PERF_2024_LABEL, pct(row["perf_2024"]),
                  delta=f"{pct(row['perf_2024'] - row['perf_2022'], True)} pts", delta_color="off")
        c3.metric("2026 DFL Perf.", pct(row["perf_2026"]), delta=f"{pct(row['shift_24_26'], True)} pts", delta_color="off")

        st.markdown("#### Comparison")
        if compare == "(none)":
            st.caption("Pick a district under **Compare to** in the sidebar.")
        else:
            crow = table.set_index("district").loc[compare]
            metrics = [("2022 DFL Perf.", "perf_2022"), (PERF_2024_LABEL, "perf_2024"),
                       ("2026 DFL Perf.", "perf_2026"), ("2024 → 2026 shift", "shift_24_26"),
                       ("2026 DFL leg. candidate", "leg_dfl_2026")]
            ct = pd.DataFrame({
                "Metric": [m_[0] for m_ in metrics],
                district: [pct(row[k], "shift" in k) for _, k in metrics],
                compare: [pct(crow[k], "shift" in k) for _, k in metrics],
            })
            st.dataframe(ct, hide_index=True, width="stretch")

    # Results by year
    st.markdown("#### Results")
    pct_cols = {c: st.column_config.NumberColumn(c, format="percent") for c in ("DFL %", "Republican %", "Other %")}
    year_tabs = st.tabs([f"{y}" + (" (unofficial)" if y == 2026 else "") for y in reversed(YEARS)])
    for yt, y in zip(year_tabs, reversed(YEARS)):
        with yt:
            rt = race_table(res, chamber, district, y)
            if rt.empty:
                st.info("No results for this district.")
            else:
                st.dataframe(rt, hide_index=True, width="stretch",
                             column_config={**pct_cols, "Total votes": st.column_config.NumberColumn(format="localized")})
                if y == 2024 and sans_klobuchar:
                    st.caption("The U.S. Senate race is shown here but excluded from 2024 DFL Performance.")

    # Turnout
    st.markdown("#### Turnout")
    tt = turnout_table(turnout, chamber, district)
    st.dataframe(tt, hide_index=True, width="stretch", column_config={
        "Registered voters": st.column_config.NumberColumn(format="localized"),
        "Ballots cast": st.column_config.NumberColumn(format="localized"),
        "Turnout": st.column_config.NumberColumn(format="percent"),
    })
    st.caption("Turnout = ballots cast ÷ (voters registered at 7am + election-day registrations), from the "
               "Secretary of State's precinct statistics.")

# ---- All districts ----
with tab_all:
    st.markdown(
        "Every district's DFL Performance by year, the 2024 → 2026 shift, and who won the 2026 legislative race."
        + (" 2024 numbers exclude Klobuchar's U.S. Senate race." if sans_klobuchar else "")
    )
    f1, f2, f3 = st.columns(3)
    only_close = f1.toggle("Only competitive (2026 DFL Perf. 40–60%)")
    only_flips = f2.toggle("Only seats that changed party")
    search = f3.text_input("Search district", placeholder="e.g. 36A or 24")
    prev = "party_2024" if chamber == "House" else "party_2022"
    v = table.copy()
    v["Flipped"] = v[prev].notna() & v["party_2026"].notna() & (v[prev] != v["party_2026"])
    if only_close:
        v = v[v["perf_2026"].between(0.4, 0.6)]
    if only_flips:
        v = v[v["Flipped"]]
    if search:
        v = v[v["district"].str.upper().str.contains(search.strip().upper().removeprefix("HD ").removeprefix("SD "))]
    show = v[["district", "perf_2022", "perf_2024", "perf_2026", "shift_24_26",
              "party_2026", "winner_2026", "Flipped", "contested_2026"]]
    show = show.rename(columns={
        "district": "District", "perf_2022": "2022", "perf_2024": "2024" + (" sans Klobuchar" if sans_klobuchar else ""),
        "perf_2026": "2026", "shift_24_26": "Shift 2024 → 2026",
        "party_2026": "2026 winner party", "winner_2026": "2026 winner", "contested_2026": "Contested",
    })
    pcfg = {c: st.column_config.NumberColumn(c, format="percent") for c in show.columns
            if c[:4].isdigit() or c.startswith("Shift")}
    st.dataframe(show, hide_index=True, width="stretch", height=560, column_config=pcfg)
    st.caption(f"{len(show)} districts shown. DFL Performance is skewed in districts where a major party "
               "fielded no legislative candidate (see *Contested*).")

# ---- Statewide summary ----
with tab_state:
    st.markdown(f"#### {chamber} seats")
    seats = len(table)
    majority = seats // 2 + 1
    actual = int((table["party_2026"] == "DFL").sum())
    s1, s2, s3 = st.columns(3)
    prev_seats = int((table[prev] == "DFL").sum())
    s1.metric("DFL seats after 2026", f"{actual} of {seats}", delta=f"{actual - prev_seats:+d} vs {prev[-4:]}",
              delta_color="off")
    s2.metric("Republican seats after 2026", f"{int((table['party_2026'] == 'R').sum())} of {seats}")
    s3.metric("Majority line", majority)

    st.markdown("#### Biggest shifts, 2024 → 2026")
    n = 12
    sw = pd.concat([table.nlargest(n, "shift_24_26"), table.nsmallest(n, "shift_24_26")]).drop_duplicates("district")
    sw = sw.sort_values("shift_24_26")
    sf = go.Figure(go.Bar(
        x=sw["shift_24_26"], y=("HD " if chamber == "House" else "SD ") + sw["district"], orientation="h",
        marker=dict(color=[DFL_BLUE if s > 0 else GOP_RED for s in sw["shift_24_26"]], cornerradius=4),
        customdata=sw[["perf_2024", "perf_2026"]].values,
        hovertemplate="%{y}: %{x:+.1%}<br>2024 %{customdata[0]:.1%} → 2026 %{customdata[1]:.1%}<extra></extra>",
    ))
    sf.update_layout(height=22 * len(sw) + 60, margin=dict(l=0, r=0, t=10, b=0), bargap=0.25,
                     xaxis=dict(tickformat="+.0%", gridcolor="#eeede9", zerolinecolor="#8a8a85"),
                     plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(sf, config={"displayModeBar": False})
    if sans_klobuchar:
        st.caption("2024 values exclude Klobuchar's U.S. Senate race.")

    st.markdown("#### Statewide races, 2026 (unofficial)")
    sr = res[(res["year"] == 2026) & res["office"].isin(["Governor", "U.S. Senate", "Attorney General",
                                                          "Secretary of State", "State Auditor"])]
    rows = []
    for office, g in sr.groupby("office"):
        tot = g["votes"].sum()
        top = g.groupby(["candidate", "party"])["votes"].sum().sort_values(ascending=False).head(2)
        (c1_, p1_), v1_ = top.index[0], top.iloc[0]
        (c2_, p2_), v2_ = top.index[1], top.iloc[1]
        rows.append({"Office": office, "Winner": f"{c1_} ({p1_})", "Winner %": v1_ / tot,
                     "Runner-up": f"{c2_} ({p2_})", "Runner-up %": v2_ / tot, "Total votes": tot,
                     "order": OFFICE_ORDER.index(office)})
    st.dataframe(pd.DataFrame(rows).sort_values("order").drop(columns="order"), hide_index=True, width="stretch",
                 column_config={"Winner %": st.column_config.NumberColumn(format="percent"),
                                "Runner-up %": st.column_config.NumberColumn(format="percent"),
                                "Total votes": st.column_config.NumberColumn(format="localized")})

with st.expander("About this data"):
    st.markdown(
        f"""
- **DFL Performance** is the DFL share of all votes cast across every partisan race on a district's ballot
  (federal, statewide and legislative), the same measure the original workbook used. The denominator is every
  vote cast in those races, including third-party and write-in votes. These match the workbook's values exactly,
  except in districts with an uncontested legislative race (26 House districts in 2022, 7 in 2024). There, the
  workbook's total counted only half of the uncontested race's votes, which inflated DFL Performance (in a few
  districts above 100%).
- **Exclude Klobuchar from 2024** (sidebar) drops the 2024 U.S. Senate race from 2024 DFL Performance and the
  2024 → 2026 shift.
- **Turnout** is ballots cast ÷ (voters registered at 7am + election-day registrations), from the Secretary
  of State's precinct statistics.
- **Sources:** 2022, 2024 and 2026 precinct results and turnout from the Minnesota Secretary of State; location
  notes from the original workbook; district boundaries from the Legislative Coordinating Commission (2023 plan,
  used for the 2022–2026 elections).
- {SURFACE_NOTE}
"""
    )
