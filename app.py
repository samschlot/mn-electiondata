"""Minnesota Legislative Elections Explorer (2022-2026).

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
# The "sans Klobuchar" race to drop each year (she ran for U.S. Senate in 2024, Governor in 2026)
KLOBUCHAR_RACE = {2024: "U.S. Senate", 2026: "Governor"}

st.set_page_config(page_title="MN Legislative Elections", page_icon="🗳️", layout="wide")


# ---------- data ----------

def dist_sort_key(d):
    m = re.fullmatch(r"(\d+)([AB]?)", str(d))
    return (int(m.group(1)), m.group(2))


@st.cache_data
def load():
    res = pd.read_csv(DATA / "results.csv", dtype={"hd": str, "office_district": str})
    res["office_district"] = res["office_district"].fillna("")
    res["sd"] = res["sd"].astype(str)
    turnout = pd.read_csv(DATA / "turnout.csv", dtype={"district": str})
    ie = pd.read_csv(DATA / "ie.csv", dtype={"district": str})
    loc = pd.read_csv(DATA / "locations.csv", dtype={"district": str})
    geo = {c: json.load(open(DATA / f"{c.lower()}.geojson")) for c in ("House", "Senate")}
    return res, turnout, ie, loc, geo


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
        by_party = g.groupby("party")["votes"].sum()
        total = g["votes"].sum()
        top = g.sort_values("votes", ascending=False).iloc[0]
        dfl, gop = by_party.get("DFL", 0), by_party.get("R", 0)
        rows.append({"year": year, "district": dist, "winner": top["candidate"], "winner_party": top["party"],
                     "dfl_pct": dfl / total, "r_pct": gop / total, "contested": dfl > 0 and gop > 0})
    return pd.DataFrame(rows)


@st.cache_data
def district_table(chamber):
    """One row per district: DFL Performance by year, the workbook's 2026 estimates, and how they did."""
    res = load()[0]
    key = key_col(chamber)
    p = dfl_perf(res, key).unstack(0)
    p.columns = [f"perf_{y}" for y in p.columns]
    for y, office in KLOBUCHAR_RACE.items():
        p[f"perf_{y}_sans"] = dfl_perf(res[res["year"] == y], key, exclude=office).unstack(0)[y]
    p["shift_22_24"] = p["perf_2024_sans"] - p["perf_2022"]
    p["est_shift"] = p["perf_2024_sans"] + p["shift_22_24"]
    p["est_plus2"] = p["est_shift"] + 0.02
    p["est_plus5"] = p["est_shift"] + 0.05
    p["shift_24_26"] = p["perf_2026"] - p["perf_2024"]
    p["est_error"] = p["perf_2026"] - p["est_shift"]
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


def pct(v, signed=False, digits=1):
    if v is None or pd.isna(v):
        return "—"
    return f"{v * 100:+.{digits}f}" if signed else f"{v * 100:.{digits}f}%"


def party_label(p):
    return {"DFL": "DFL", "R": "Republican"}.get(p, p or "—")


# ---------- views ----------

res, turnout, ie, loc, geo = load()
SURFACE_NOTE = ("2026 results are **unofficial** (MN Secretary of State, all precincts reporting) until the "
                "State Canvassing Board certifies them. Re-run `build_data.py` afterward to refresh.")

st.title("Minnesota Legislative Elections, 2022–2026")
st.caption(SURFACE_NOTE)

with st.sidebar:
    st.header("District")
    chamber = st.radio("Chamber", ["House", "Senate"], horizontal=True)
    table = district_table(chamber)
    districts = table["district"].tolist()
    dkey = f"district_{chamber}"
    if dkey not in st.session_state:
        st.session_state[dkey] = "36A" if chamber == "House" else "24"
    district = st.selectbox("District", districts, key=dkey,
                            format_func=lambda d: f"{'HD' if chamber == 'House' else 'SD'} {d}")
    compare = st.selectbox("Compare to", ["(none)"] + [d for d in districts if d != district],
                           key=f"compare_{chamber}")
    st.divider()
    map_metric = st.selectbox("Map color", ["2026 DFL Performance", "2024 → 2026 shift",
                                            "2026 result vs. workbook estimate", "2026 legislative winner"])
    st.caption("Click a district on the map to open it.")

row = table.set_index("district").loc[district]
tab_district, tab_all, tab_state = st.tabs(["District view", "All districts", "Statewide summary"])

# ---- District view ----
with tab_district:
    map_col, info_col = st.columns([1, 1], gap="large")

    with map_col:
        m = table.copy()
        hover_extra = {}
        if map_metric == "2026 DFL Performance":
            m["value"] = m["perf_2026"]
            scale, rng, fmt = DIVERGING, (0.25, 0.75), ":.1%"
        elif map_metric == "2024 → 2026 shift":
            m["value"] = m["shift_24_26"]
            scale, rng, fmt = DIVERGING, (-0.12, 0.12), ":+.1%"
        elif map_metric == "2026 result vs. workbook estimate":
            m["value"] = m["est_error"]
            scale, rng, fmt = DIVERGING, (-0.12, 0.12), ":+.1%"
        else:
            m["value"] = m["party_2026"].map({"DFL": 1.0, "R": 0.0}).fillna(0.5)
            scale, rng, fmt = [[0, GOP_RED], [0.5, NEUTRAL], [1, DFL_BLUE]], (0, 1), None
        m["label"] = ("HD " if chamber == "House" else "SD ") + m["district"]
        m["winner"] = m["winner_2026"].fillna("—") + " (" + m["party_2026"].fillna("—") + ")"
        m["perf"] = m["perf_2026"].map(pct)
        m["shift"] = m["shift_24_26"].map(lambda v: pct(v, signed=True) + " pts")
        fig = px.choropleth(
            m, geojson=geo[chamber], locations="district", color="value",
            color_continuous_scale=scale, range_color=rng,
            hover_name="label", hover_data={"district": False, "value": False, "winner": True,
                                            "perf": True, "shift": True},
            labels={"winner": "2026 winner", "perf": "2026 DFL Perf.", "shift": "Shift vs 2024"},
        )
        # Outline the selected district
        sel = m[m["district"] == district]
        fig.add_trace(go.Choropleth(geojson=geo[chamber], locations=sel["district"], z=[1],
                                    colorscale=[[0, "rgba(0,0,0,0)"], [1, "rgba(0,0,0,0)"]],
                                    marker_line_color="#111", marker_line_width=2.5, showscale=False,
                                    hoverinfo="skip"))
        fig.update_geos(fitbounds="locations", visible=False, projection_type="mercator")
        fig.update_layout(height=560, margin=dict(l=0, r=0, t=0, b=0),
                          coloraxis_colorbar=dict(title="", thickness=10, len=0.6,
                                                  tickformat="+.0%" if "shift" in map_metric or "vs." in map_metric else ".0%"),
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

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("2022 DFL Perf.", pct(row["perf_2022"]))
        c2.metric("2024 DFL Perf.", pct(row["perf_2024"]),
                  delta=f"{pct(row['perf_2024'] - row['perf_2022'], True)} pts", delta_color="off")
        c3.metric("2026 DFL Perf.", pct(row["perf_2026"]), delta=f"{pct(row['shift_24_26'], True)} pts", delta_color="off")
        c4.metric("2026 estimate", pct(row["est_shift"]),
                  delta=f"actual {pct(row['est_error'], True)} pts", delta_color="off")

        # Trend chart: district vs comparison vs statewide
        state = dfl_perf(res.assign(all="MN"), "all").unstack(0).iloc[0]
        trend = [go.Scatter(x=YEARS, y=[row[f"perf_{y}"] for y in YEARS], name=label, mode="lines+markers",
                            line=dict(color=DFL_BLUE, width=2), marker=dict(size=8))]
        if compare != "(none)":
            crow = table.set_index("district").loc[compare]
            trend.append(go.Scatter(x=YEARS, y=[crow[f"perf_{y}"] for y in YEARS],
                                    name=f"{'HD' if chamber == 'House' else 'SD'} {compare}", mode="lines+markers",
                                    line=dict(color="#7a5cc4", width=2), marker=dict(size=8)))
        trend.append(go.Scatter(x=YEARS, y=[state[y] for y in YEARS], name="Statewide", mode="lines+markers",
                                line=dict(color="#8a8a85", width=2, dash="dot"), marker=dict(size=8)))
        tf = go.Figure(trend)
        tf.add_hline(y=0.5, line_color="#c9c8c3", line_width=1)
        tf.update_layout(height=260, margin=dict(l=0, r=0, t=30, b=0), hovermode="x unified",
                         title=dict(text="DFL Performance over time", font=dict(size=14)),
                         yaxis=dict(tickformat=".0%", gridcolor="#eeede9"), xaxis=dict(tickvals=YEARS),
                         legend=dict(orientation="h", y=-0.2), plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(tf, config={"displayModeBar": False})

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

    # Turnout, win number, IE, comparison
    t_col, ie_col, cmp_col = st.columns(3, gap="large")
    with t_col:
        st.markdown("#### Turnout")
        t = turnout[(turnout["chamber"] == chamber) & (turnout["district"] == district)]
        cast_2026 = res[(res["year"] == 2026) & (res[key_col(chamber)] == district)].groupby("office")["votes"].sum().max()
        if len(t):
            t = t.iloc[0]
            st.markdown(
                f"- 2022 turnout: **{pct(t['t2022'])}**\n"
                f"- 2024 turnout: **{pct(t['t2024'])}**\n"
                f"- Workbook projected 2026 ballots: **{t['projected_ballots']:,.0f}** "
                f"(win number {t['win_number']:,.0f})\n"
                f"- Actual 2026 votes in top race: **{cast_2026:,.0f}**"
                + (f" ({(cast_2026 / t['projected_ballots'] - 1) * 100:+.0f}% vs. projection)"
                   if t["projected_ballots"] else "")
            )
    with ie_col:
        cyc = 2024 if chamber == "House" else 2022
        st.markdown(f"#### {cyc} independent expenditures")
        e = ie[(ie["chamber"] == chamber) & (ie["district"] == district)]
        if e.empty:
            st.caption("No IE spending recorded for this district.")
        else:
            for _, r in e.iterrows():
                st.markdown(f"**{r['candidate']}** ({r['party']}): ${r['for_amt']:,.0f} for / ${r['against_amt']:,.0f} against")
            dfl_help = e.loc[e["party"] == "DFL", "for_amt"].sum() + e.loc[e["party"] == "R", "against_amt"].sum()
            r_help = e.loc[e["party"] == "R", "for_amt"].sum() + e.loc[e["party"] == "DFL", "against_amt"].sum()
            st.markdown(f"Net spending gap (pro-DFL minus pro-R): **${dfl_help - r_help:,.0f}**")
        st.caption("2026 IE data isn't included yet; post-general reports come from the Campaign Finance Board.")
    with cmp_col:
        st.markdown("#### Comparison")
        if compare == "(none)":
            st.caption("Pick a district under **Compare to** in the sidebar.")
        else:
            crow = table.set_index("district").loc[compare]
            metrics = [("2022 DFL Perf.", "perf_2022"), ("2024 DFL Perf.", "perf_2024"),
                       ("2026 DFL Perf.", "perf_2026"), ("2024 → 2026 shift", "shift_24_26"),
                       ("2026 DFL leg. candidate", "leg_dfl_2026")]
            ct = pd.DataFrame({
                "Metric": [m_[0] for m_ in metrics],
                district: [pct(row[k], "shift" in k) for _, k in metrics],
                compare: [pct(crow[k], "shift" in k) for _, k in metrics],
            })
            st.dataframe(ct, hide_index=True, width="stretch")

# ---- All districts ----
with tab_all:
    st.markdown(
        "Every district's DFL Performance, the three 2026 estimates from the original workbook, and how 2026 "
        "actually turned out. *Sans Klobuchar* drops the race she was on the ballot for (U.S. Senate in 2024, "
        "Governor in 2026)."
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
    show = v[["district", "perf_2022", "perf_2024", "perf_2024_sans", "est_shift", "est_plus2", "est_plus5",
              "perf_2026", "perf_2026_sans", "est_error", "party_2026", "winner_2026", "Flipped", "contested_2026"]]
    show = show.rename(columns={
        "district": "District", "perf_2022": "2022", "perf_2024": "2024", "perf_2024_sans": "2024 sans Klobuchar",
        "est_shift": "2026 est. (two-year shift)", "est_plus2": "2026 est. (+2%)", "est_plus5": "2026 est. (+5%)",
        "perf_2026": "2026 actual", "perf_2026_sans": "2026 sans Klobuchar", "est_error": "Actual − est.",
        "party_2026": "2026 winner party", "winner_2026": "2026 winner", "contested_2026": "Contested",
    })
    pcfg = {c: st.column_config.NumberColumn(c, format="percent") for c in show.columns
            if c[:4].isdigit() or c == "Actual − est."}
    st.dataframe(show, hide_index=True, width="stretch", height=560, column_config=pcfg)
    st.caption(f"{len(show)} districts shown. DFL Performance is skewed in districts where a major party "
               "fielded no legislative candidate (see *Contested*).")

# ---- Statewide summary ----
with tab_state:
    st.markdown(f"#### {chamber} seats")
    seats = len(table)
    majority = seats // 2 + 1
    actual = int((table["party_2026"] == "DFL").sum())
    est_rows = [
        ("Based on 2024 DFL Performance", (table["perf_2024"] > 0.5).sum()),
        ("Two-year shift estimate", (table["est_shift"] > 0.5).sum()),
        ("Two-year shift +2%", (table["est_plus2"] > 0.5).sum()),
        ("Two-year shift +5%", (table["est_plus5"] > 0.5).sum()),
        ("2026 actual (unofficial)", actual),
    ]
    s1, s2, s3 = st.columns(3)
    prev_seats = int((table[prev] == "DFL").sum())
    s1.metric("DFL seats after 2026", f"{actual} of {seats}", delta=f"{actual - prev_seats:+d} vs {prev[-4:]}",
              delta_color="off")
    s2.metric("Republican seats after 2026", f"{int((table['party_2026'] == 'R').sum())} of {seats}")
    s3.metric("Majority line", majority)

    ef = go.Figure(go.Bar(
        y=[r[0] for r in est_rows], x=[r[1] for r in est_rows], orientation="h",
        marker=dict(color=[DFL_BLUE] * 4 + ["#163f8f"], cornerradius=4),
        text=[str(r[1]) for r in est_rows], textposition="outside",
        hovertemplate="%{y}: %{x} DFL seats<extra></extra>",
    ))
    ef.add_vline(x=majority, line_dash="dot", line_color="#8a8a85",
                 annotation_text=f"Majority ({majority})", annotation_position="top")
    ef.update_layout(height=300, margin=dict(l=0, r=40, t=30, b=0), title="DFL seats: estimates vs. actual",
                     xaxis=dict(range=[0, seats], gridcolor="#eeede9"), yaxis=dict(autorange="reversed"),
                     plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(ef, config={"displayModeBar": False})
    st.caption("Estimates count districts where the estimated DFL Performance is above 50%, as in the workbook's "
               "Targeted Seats summary.")

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
  (federal, statewide and legislative), the same measure the original workbook used. Totals here include
  third-party and write-in votes. In the workbook, the "Total Votes" column for some districts didn't match the
  sum of votes (a few districts showed DFL Performance above 100%), so 2022 and 2024 values may differ slightly
  from the spreadsheet.
- **2026 estimates** use the workbook's method: 2024 DFL Performance without Klobuchar, plus the 2022→2024
  shift; then +2% and +5% variants.
- **Sources:** 2022 and 2024 precinct results from the original workbook; 2026 results from the
  Minnesota Secretary of State; district boundaries from the Legislative Coordinating Commission (2023
  plan, used for the 2022–2026 elections).
- {SURFACE_NOTE}
"""
    )
