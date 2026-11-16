# Minnesota Election Results & Shifts

A Streamlit version of the MN Elections Database workbook: 2022, 2024 and 2026 state legislative results by district, with a clickable district map.

## Run it

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
```

## Refresh the data (e.g. after the 2026 canvass)

1. Download `allracesbyprecinct.txt` and `pctstats.txt` (turnout) for each year from the Secretary of State into `raw/<year>/`:
   - https://electionresultsfiles.sos.mn.gov/20221108/allracesbyprecinct.txt → `raw/2022/`
   - https://electionresultsfiles.sos.mn.gov/20241105/allracesbyprecinct.txt → `raw/2024/`
   - https://electionresultsfiles.sos.mn.gov/20261103/allracesbyprecinct.txt → `raw/2026/`
2. Optional, only if the map files need regenerating (they change only with redistricting): download and unzip https://gis.lcc.mn.gov/data/geojson/L2023_0hse.zip and `L2023_0sen.zip` into `geo/` and add `--geo-dir geo` below.
3. Run:

```bash
.venv/bin/python build_data.py --workbook MNElectionsDatabase.xlsx --sos-dir raw
```

## Files

- `app.py`: the Streamlit app
- `build_data.py`: builds everything in `data/` from SOS precinct results (all years), the workbook (IE, locations), and LCC boundaries
- `data/results.csv`: every partisan race by House district, 2022–2026 (Senate = sum of A + B)
- `data/turnout_sos.csv`: registered voters and ballots cast by House district, 2022–2026 (SOS)
- `data/locations.csv`: carried over from the workbook
- `data/ie.csv`: workbook IE spending; built but not shown in the app for now
- `data/house.geojson`, `data/senate.geojson`: simplified district boundaries

## Deploying

Push this folder to a GitHub repo and deploy it on Streamlit Community Cloud (share.streamlit.io). Only `app.py`, `data/`, and `requirements.txt` are needed at runtime.
