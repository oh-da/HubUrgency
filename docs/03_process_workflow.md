# 3. Process Workflow — Start to Finish

This is the heart of the documentation: **every step, in order, and what each step
does.** The pipeline has two stages. Stage 1 links projects to hubs; Stage 2 scores
each hub's progress.

## Process at a glance

```
INPUTS                         STAGE 1: LINKER                  STAGE 2: CALCULATOR              OUTPUTS
────────────────────────────────────────────────────────────────────────────────────────────────────────

Hubs CSV ─────────────┐
(group, h3_index list)│
                      ▼
              ┌──────────────────┐
              │ 1.1 Load & parse │
              │     H3 lists     │
              │ 1.2 Explode to   │
              │     one row/cell │
              └────────┬─────────┘
                       │
Inventar shapefiles ──►│ 1.3 Load points / lines / multilines
(uid + geometry)       │
                       ▼
              ┌──────────────────┐
              │ 1.4 H3 cell →    │
              │     polygon      │
              │ 1.5 Spatial      │
              │     intersect    │
              │     (R-tree)     │
              └────────┬─────────┘
                       ▼
              intersecting_points / lines / multilines  ──►  base / combined / exploded CSVs
                       │
                       └──────────────────────────────────────┐
                                                               ▼
project data CSV ─────────────────────────────────►  ┌──────────────────┐
(uid, Proj_status, …)                                │ 2.1 Combine UIDs │
                                                      │ 2.2 Explode      │
status weights CSV ──────────────────────────────►   │ 2.3 Join project │
(Proj_status, weight)                                │     attributes   │
                                                      │ 2.4 Map status   │
                                                      │     → weight     │
                                                      │ 2.5 Aggregate    │
                                                      │     per hub      │
                                                      │ 2.6 Breakdown    │
                                                      │ 2.7 Status-zero  │
                                                      └────────┬─────────┘
                                                               ▼
                                          joined / progress / breakdown / status-zero CSVs
```

---

## STAGE 1 — Inventar Hub Linker

**Module:** `src/inventar_hub_linker.py`
**Orchestrator:** `InventarHubLinker.process()`
**Goal:** for every hub hexagon, list the project UIDs whose geometry intersects
it.

### Step 1.0 — Validate configuration
`ProcessingConfig.validate()` checks that the hubs CSV and the Inventar directory
exist before any work begins, failing fast with a clear `FileNotFoundError`.

### Step 1.1 — Load and parse hubs
`HubDataLoader.load()`:
1. Reads the hubs CSV with the configured encoding (`windows-1255` by default).
2. Parses the `h3_index` column from a string like `"['8a..a', '8a..b']"` into a
   real Python list via `H3ListParser.parse()` (strips brackets, quotes,
   whitespace; `NaN`/non-strings → empty list).
3. Keeps only the relevant columns that are present: `group`, `x`, `y`,
   `HubNameHE`, `h3_index`.

### Step 1.2 — Explode to one row per H3 cell
The list-valued `h3_index` column is `explode()`-ed so that each row now
represents **a single hexagon** belonging to a hub group. A hub with 5 hexagons
becomes 5 rows sharing the same `group`. This is what lets the intersection run
cell-by-cell.

### Step 1.3 — Load the Inventar geometries
`InventarLoaderFactory.create_all_loaders()` builds one `ShapefileLoader` per
geometry type (`points`, `lines`, `multilines`). Each loads its shapefile into a
GeoDataFrame. A missing file → empty GeoDataFrame + warning (run continues).

### Step 1.4 — Convert H3 cells to polygons
`H3PolygonConverter.convert_series()` turns each H3 index string into a Shapely
`Polygon`:
- `h3.cell_to_boundary(index)` returns the hexagon's vertices as **(lat, lon)**.
- Shapely needs **(lon, lat) = (x, y)**, so coordinates are swapped.
- Result is a polygon in **WGS84 (EPSG:4326)**. Invalid indices → `None` (skipped).

This temporary `h3_polygon` column is dropped at the end of the stage.

### Step 1.5 — Spatial intersection (the linking)
For each geometry type, a `SpatialIntersector` wraps the GeoDataFrame and, for
each hub polygon, finds intersecting project UIDs using a **two-stage strategy**:

1. **Bounding-box pre-filter** via the R-tree spatial index:
   `gdf.sindex.intersection(polygon.bounds)` — cheap, `O(log n)`, narrows millions
   of candidates to a handful.
2. **Precise test** on only those candidates: `candidates.intersects(polygon)`.
3. Returns the `uid` list of the survivors.

The orchestrator (`_compute_all_intersections`) loops over every hub hexagon and
every geometry type, producing three new columns:
`intersecting_points`, `intersecting_lines`, `intersecting_multilines`
— each a list of project UIDs. Progress is logged every 1,000 rows, and a summary
counts how many hexagons had intersections per type.

### Step 1.6 — Produce output formats
`process_and_save_all_formats()` writes three views (see
[Chapter 5](05_outputs.md) for full schemas):

| View | Built by | Shape |
|------|----------|-------|
| **base** | `process()` | one row per hexagon, three list columns |
| **combined** | `ResultTransformer.combine_project_uids()` | base + `all_project_uids` (deduped union across the three types) |
| **exploded** | `ResultTransformer.explode_by_project()` | one row per (hexagon, single `project_uid`); hexagons with zero projects are **kept with `NaN`** |

> **Code-vs-docs note.** An older guide says the exploded output "only contains
> rows where at least one project intersects." The **current code preserves**
> zero-project hexagons as `NaN` rows (so no hub silently disappears). This
> documentation follows the code.

The output of Stage 1 (typically the **combined** file, which still has the three
`intersecting_*` list columns) is the hub input to Stage 2.

---

## STAGE 2 — Hub Project Status Calculator

**Module:** `src/hub_project_status_calculator.py`
**Orchestrator (facade):** `HubProjectStatusPipeline.run()`
**Goal:** attach each linked project's status and compute per-hub progress.

### Step 2.0 — Load inputs
Load the Stage-1 hub output, the project data CSV, and the status-weights CSV.
Use the helper `load_hub_csv()` so the `intersecting_*` columns are parsed back
from strings into real lists (`ListColumnParser`). `DataLoader.load_csv()` tries
`windows-1255` and falls back to `utf-8-sig` on a decode error.

The pipeline is constructed with the three DataFrames; this immediately:
- validates the project data has the required columns (`ProjectDataJoiner`), and
- validates the weights table and builds the `Proj_status → weight` lookup and
  records `max(weight)` (`StatusProgressCalculator`).

### Step 2.1 — Combine UIDs per hexagon
`ProjectDataJoiner._combine_uids()` merges `intersecting_points`,
`intersecting_lines`, and `intersecting_multilines` into a single
`combined_uids` list per row, **de-duplicating within the row**.

### Step 2.2 — Explode to hub–project pairs
`_explode_uids()` explodes `combined_uids` so there is **one row per
(hub hexagon, project uid)**, renames the column to `uid`, and drops empty/null
UID rows. After this, the grain of the data is the individual hub–project link.

### Step 2.3 — Join project attributes
The exploded UIDs (cast to `str`) are **left-joined** to the project data on
`uid`, pulling in `proj_name`, `main_type`, `Proj_status`, `scn_year`. A match
rate is logged (`matched / total`). Unmatched links keep `NaN` attributes.

### Step 2.4 — Map status to weight
`StatusProgressCalculator._map_status_to_weight()` looks up each row's
`Proj_status` (as string) in the weights table to produce `status_weight`. Any
status with no mapping → weight `0` (with a warning). `_prepare_for_aggregation()`
then guarantees `status_weight` is numeric and `Proj_status` is string — this is
the fix that prevents the historical `TypeError: agg function failed` during
aggregation.

### Step 2.5 — Aggregate progress per hub
`calculate_hub_progress()` groups by `group` and computes:

| Metric | How |
|--------|-----|
| `total_projects` | count of `uid` |
| `current_weighted_sum` | sum of `status_weight` |
| `max_possible_sum` | `total_projects × max_weight` |
| `unique_statuses` | distinct `Proj_status` count |
| `status_progress_pct` | `100 × current_weighted_sum / max_possible_sum`, rounded to 2 dp |

This **`status_progress_pct` is the headline number** of the whole system — see
[Chapter 4](04_model_methodology.md) for the math and interpretation.

### Step 2.6 — Status breakdown
`calculate_status_breakdown()` pivots `group × Proj_status` into one column per
status — `num_proj_status_0`, `num_proj_status_1`, … — plus a `total_projects`
column. This shows the *distribution* of statuses inside each hub, not just the
single progress score.

### Step 2.7 — Status-zero extraction
`get_status_zero_projects()` returns the hub–project rows whose `status_weight`
is `0` — the not-started / cancelled / unmapped projects. This is the basis of the
stalled-project analysis (see [Chapter 4 §4.3](04_model_methodology.md#43-the-status-zero-model)).

### Step 2.8 — Save results
`save_results()` writes the joined data, the progress summary, the status
breakdown, and (optionally) the status-zero rows, all with the chosen encoding.
See [Chapter 5](05_outputs.md) for every output column.

---

## Running it

### Stage 1 — command line
```bash
python src/inventar_hub_linker.py \
    --hubs   data/Results_29-12-2025.csv \
    --inventar data/Inventar \
    --output output/Hubs_with_Inventar.csv
```
Produces `Hubs_with_Inventar.csv`, `_combined.csv`, and `_exploded.csv`.

### Stage 1 — Python
```python
from huburgency import link_inventar_to_hubs

results = link_inventar_to_hubs(
    hubs_csv="data/Results_29-12-2025.csv",
    inventar_dir="data/Inventar",
    output_csv="output/Hubs_with_Inventar.csv",
)
base_df, combined_df, exploded_df = results["base"], results["combined"], results["exploded"]
```

### Stage 2 — Python
```python
from huburgency import load_hub_csv, DataLoader, HubProjectStatusPipeline

hub_df     = load_hub_csv("output/Hubs_with_Inventar_combined.csv")   # parses list columns
project_df = DataLoader.load_csv("data/data.csv")
weights_df = DataLoader.load_csv("data/status_weights.csv")

pipeline = HubProjectStatusPipeline(hub_df, project_df, weights_df)
joined_df, progress_df, breakdown_df = pipeline.run()

pipeline.save_results(
    joined_path="output/hubs_with_project_data.csv",
    progress_path="output/hub_status_progress.csv",
    status_breakdown_path="output/hub_status_breakdown.csv",
    status_zero_path="output/hub_status_zero_report.csv",
)
```

Continue to **[4. The Model & Methodology](04_model_methodology.md)** for the math
behind the numbers.
</content>
