# Minnesota Legislative Elections Explorer

A Streamlit version of the MN Elections Database workbook: 2022, 2024 and 2026 state legislative results by district, with a clickable district map.

## Run it

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
```

## Refresh the data (e.g. after the 2026 canvass)

1. Download `allracesbyprecinct.txt` from https://electionresultsfiles.sos.mn.gov/20261103/ into a folder (e.g. `raw/`).
2. Download and unzip the district shapes from https://gis.lcc.mn.gov/data/geojson/L2023_0hse.zip and `L2023_0sen.zip` into a folder (e.g. `geo/`). These only change with redistricting.
3. Run:

```bash
.venv/bin/python build_data.py --workbook MNElectionsDatabase.xlsx --sos-dir raw --geo-dir geo
```

## Files

- `app.py`: the Streamlit app
- `build_data.py`: builds everything in `data/` from the workbook, SOS results, and LCC boundaries
- `data/results.csv`: every partisan race by House district, 2022–2026 (Senate = sum of A + B)
- `data/turnout.csv`, `data/ie.csv`, `data/locations.csv`: carried over from the workbook
- `data/house.geojson`, `data/senate.geojson`: simplified district boundaries

## Deploying

Push this folder to a GitHub repo and deploy it on Streamlit Community Cloud (share.streamlit.io). Only `app.py`, `data/`, and `requirements.txt` are needed at runtime.
