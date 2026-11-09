# RoadGap

Find missing road safety features and design fixes.

This project helps a student or planner study where people need to cross roads safely. It uses free OpenStreetMap data to find risky places near schools, hospitals, bus stops, markets and other walking areas, and then it shows where a crossing or safety feature may be missing.

## Install and run

1. Open a terminal in the project folder.
2. Install the Python packages:

```bash
python -m pip install -r requirements.txt
```

3. Run the command-line version:

```bash
python main.py "Guindy, Chennai, India"
```

4. Run the web app:

```bash
streamlit run app.py
```

The web app keeps its settings in the sidebar and runs only when **Run analysis** is pressed. After a run, switch between Combined and individual analyses, then use the Table, Charts, Report, Street View checklist, and Downloads tabs. The map and top-gap list share a compact two-column layout; checklist edits are available as a CSV download.

## Change the area or settings

Edit the values in `config.py` or pass a different area in the command line or app. The main settings are:

- `AREA_NAME`
- `GAP_DISTANCE_M`
- `TOP_N`
- `ROAD_TYPES`
- `AREA_SIZE_LIMIT_M`
- `SAVE_DOWNLOAD_CACHE`

Example:

```python
AREA_NAME = "Bengaluru, India"
GAP_DISTANCE_M = 100
TOP_N = 5
```

## How the score works

Each gap's distance, road speed, lane count, and place-type risk are converted to percentile ranks across the gaps in the current run. Those percentiles are combined with weights of 40%, 25%, 20%, and 15%, then rescaled to a 20-100 range. These are relative scores for the current run, not calibrated measures of absolute risk.

An analysis does not report gaps when its existing feature inventory is empty. Instead, it shows a low-confidence warning such as “No signs are mapped in this area, so this result is not reliable.” Place counts are tracked and shown separately for each analysis.

Places of the same type within 25 m are merged to one representative at their average location; result rows include the number of mapped points merged. The Combined view groups results by place and ranks them by the number of gap types first, then by their average score. Low mapped-feature counts lower the analysis confidence and are reported in the warning and summary.

Road results also flag mapped bridges, raised layers, and nearby trunk-road flyovers with a reminder to verify grade-separated crossings in Street View.

## Maps and charts

The generated map uses OpenStreetMap tiles and draws highway features from the loaded data as thin grey lines. Red markers show possible gaps; green markers show mapped existing features. There are separate layer controls for each analysis, and the top ten gaps are numbered. Charts use horizontal bars and rank-based labels so non-Latin place names do not render as empty boxes.

## Limits

OpenStreetMap is useful, but it is not always complete. Some crossings, signs, barriers, or speed breakers may be missing from the map. That is why the top results should always be checked in Street View before making a design decision.

## Offline mode and saved downloads

The app can use a local OSM XML `.osm` file or GeoJSON extract instead of contacting Overpass. It lists `.osm`, `.geojson`, and `.json` files in the project's `OSM/` and `data/` folders for direct selection. Or upload one of those file types.

1. Put your OSM XML file at `OSM/map.osm`, or use the upload option to select it.
2. In the app, select **Use local map data (offline)** and choose a project file or upload a file.
3. Use a place name as the extract's area label, or enter `latitude,longitude` and set a radius to select a smaller circular area from a larger extract.

The CLI accepts a local file path:

```bash
python main.py "Guindy, Chennai, India" --offline-file "OSM\map.osm"
```

In offline mode, the extract is used directly. A named area does not need geocoding or internet access; the extract should already cover that study area. Coordinate input such as `"13.0087,80.2126"` filters the extract by the default radius. `.osm.pbf` files are not currently supported.

Successful online downloads can be cached automatically. In the app, **Save downloads in cache/** controls that behavior, and `--no-cache` disables reading and saving cached downloads in the CLI. Cached data is stored in `cache/` and reused for the same area and query.

Each analysis run saves its reports, CSV files, chart, and map in a new uniquely named folder under `output/`. Running the same area or analysis again will not replace the previous run's files. The app displays the folder path after a run, and the CLI lists it with the output files.

## Run in Google Colab

1. Upload the project files or clone the repo.
2. Install the requirements:

```python
!pip install -r requirements.txt
```

3. Run the script:

```python
!python main.py "Guindy, Chennai, India"
```

## Notes

- If a place name is not found, the program shows a friendly message and gives a better suggestion.
- Place-name lookup and map-data downloads use separate OpenStreetMap services. A place can resolve correctly while Overpass (roads and features) is temporarily unavailable; the app reports that separately and does not treat a failed download as reliable empty data.
- If an Overpass instance times out, the downloader tries the other public instances listed in `config.py`. A failed instance is briefly skipped to avoid repeating the same timeout for each analysis layer.
- Offline mode supports OSM XML `.osm` and GeoJSON FeatureCollection files; it does not read `.osm.pbf` files.
- If the study area is too large, it limits the analysis to a safe radius.
- If the internet is not available, the program prints a clear error instead of crashing.
