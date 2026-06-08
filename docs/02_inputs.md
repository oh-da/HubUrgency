# 2. Inputs

This chapter lists every input the pipeline consumes, the exact schema of each,
and the assumptions the code makes about them. Schemas below reflect the
**actual columns the code reads** in `src/`.

## 2.1 Inputs at a glance

| # | Input | Used by | Form | Required columns |
|---|-------|---------|------|------------------|
| 1 | **Hubs CSV** | Stage 1 | CSV | `group`, `x`, `y`, `HubNameHE`, `h3_index` |
| 2 | **Inventar shapefiles** | Stage 1 | 3 × Shapefile | `uid` + geometry |
| 3 | **Project data CSV** (`data.csv`) | Stage 2 | CSV | `uid`, `proj_name`, `main_type`, `Proj_status`, `scn_year` |
| 4 | **Status weights CSV** | Stage 2 | CSV | `Proj_status`, `weight` |

> The output of Stage 1 becomes the hub input of Stage 2 (see
> [Chapter 3](03_process_workflow.md)). So in a full run you supply inputs 1–4;
> input "hubs" for Stage 2 is generated, not hand-authored.

---

## 2.2 Input 1 — Hubs CSV

The hub list produced by the upstream Transit Hub Processing Pipeline. **One row
per hub group**, where a single hub's footprint is a *list* of H3 cells stored as
a string.

**Default encoding:** `windows-1255` (configurable).

| Column | Type | Description |
|--------|------|-------------|
| `group` | int | Hub group ID — the unique identifier of a hub. This is the key everything is aggregated by. |
| `x` | float | Hub centroid X coordinate (Israel TM Grid, EPSG:2039, in the upstream data). |
| `y` | float | Hub centroid Y coordinate (EPSG:2039). |
| `HubNameHE` | str | Hub name in Hebrew. Reason the default encoding is windows-1255. |
| `h3_index` | str | A **string-encoded list** of H3 cell indices belonging to this hub, e.g. `"['8a2a1072b59ffff', '8a2a1072b5affff']"`. |

**Important detail — the `h3_index` column is a list-as-string.**
The loader parses it (see `H3ListParser`) accepting forms like:
- `['8a3e0a1234', '8a3e0a1235']`
- `[8a3e0a1234, 8a3e0a1235]`

After parsing, the hub row is **exploded** so there is one row per H3 cell. The
example indices (`8a...ffff`) are H3 **resolution-10** cells; the actual
resolution is whatever the upstream pipeline chose.

> **Note on column naming.** The code's `ProcessingConfig` expects the H3 column
> to be named `h3_index`. The top-level project README mentions an `h3_8` column
> in one example — that is illustrative; the linker default is `h3_index`. If your
> file uses a different name, set it via `ProcessingConfig(h3_column=...)`.

---

## 2.3 Input 2 — Inventar shapefiles

The "Inventar" is a directory of planned-infrastructure geometries, split by
geometry type. All three are loaded by Stage 1 from a single directory.

| File (default name) | Geometry | Typical content |
|---------------------|----------|-----------------|
| `geom_point.shp` | Point | Station locations, intersections, point assets |
| `geom_line.shp` | LineString | Road segments, transit alignments |
| `geom_multiline.shp` | MultiLineString | Complex / multi-part corridors |

**Required attribute:** every shapefile must contain a **`uid`** column — the
unique project identifier. This `uid` is the join key to the project data in
Stage 2.

**Coordinate Reference System (CRS):** intersection is done against H3 polygons,
which are in **WGS84 (EPSG:4326)**. The shapefiles must be in the same CRS for
intersections to be correct. If yours are in Israel TM Grid (EPSG:2039),
reproject first:

```python
import geopandas as gpd
gdf = gpd.read_file("geom_point.shp").to_crs("EPSG:4326")
gdf.to_file("geom_point.shp")
```

> A missing shapefile is tolerated: `ShapefileLoader.load()` logs a warning and
> returns an empty GeoDataFrame, so that geometry type simply contributes no
> intersections rather than crashing the run.

---

## 2.4 Input 3 — Project data CSV (`data.csv`)

The engineering attributes of every project, keyed by `uid`. Consumed by Stage 2
to attach status to each linked project.

**Required columns** (enforced by `ProjectDataJoiner.REQUIRED_PROJECT_COLS`):

| Column | Type | Description |
|--------|------|-------------|
| `uid` | str/int | Unique project identifier. **Primary key**; must match the `uid` values in the Inventar shapefiles. Cast to `str` before joining. |
| `proj_name` | str | Human-readable project name. |
| `main_type` | str | Project mode/type (e.g. Rail, LRT, BRT, Metro, Bus). |
| `Proj_status` | int/str | Status code of the project. **Join key to the status-weights table.** |
| `scn_year` | int | Scenario / planned year. Coerced to numeric for safety (`DataTypeHandler`). |

If a linked `uid` has no matching row here, the project's attributes come through
as `NaN` after the left join (and its status maps to weight 0 — see
[Chapter 4](04_model_methodology.md)).

---

## 2.5 Input 4 — Status weights CSV

The lookup table that converts an engineering status into a numeric completion
weight. This table **defines the model's notion of "progress"**, so getting it
right matters more than any other tuning.

**Required columns** (enforced by
`StatusProgressCalculator.REQUIRED_WEIGHT_COLS`):

| Column | Type | Description |
|--------|------|-------------|
| `Proj_status` | int/str | Status code — matches `Proj_status` in the project data. |
| `weight` | float | Normalized completion weight, typically `0.0`–`1.0`. |

Example weight schema (statuses ascending from planning to operational):

| `Proj_status` | Meaning | `weight` |
|---------------|---------|----------|
| 1 | Planning initiated | 0.10 |
| 2 | Preliminary design | 0.25 |
| 3 | Detailed design | 0.40 |
| 4 | Tender / procurement | 0.60 |
| 5 | Under construction | 0.75 |
| 6 | Testing / commissioning | 0.85 |
| 7 | Soft opening | 0.95 |
| 8 | Fully operational | 1.00 |

(Optionally add a `0` row for not-started/cancelled with weight `0.0`; see the
status-zero discussion in [Chapter 4](04_model_methodology.md#43-the-status-zero-model).)

> **Important — column name is `Proj_status`, not `Proj_status_id`.**
> The current code keys the weights table on a column literally named
> `Proj_status`. Some older guides in `docs/` show `Proj_status_id`; that name
> will fail validation with the code in `src/`. Use `Proj_status`.

### Modeling notes on the weights

- Weights should be **monotonic** in completion (later stages ≥ earlier stages)
  for the progress percentage to behave intuitively.
- The model normalizes by `max(weight)`, so the **scale** of the weights is
  irrelevant — only their *ratios* matter. `[0.1 … 1.0]` and `[10 … 100]` give the
  same progress percentages.
- Any status present in the project data but **absent** from this table is
  treated as weight `0` (with a warning), which both lowers progress and flags the
  project as status-zero.

---

## 2.6 Configuration knobs

Both stages expose configuration so you rarely need to touch input files:

- **Stage 1 — `ProcessingConfig`** (`inventar_hub_linker.py`):
  `hubs_csv_path`, `inventar_directory`, `output_csv_path`, `encoding`
  (default `windows-1255`), shapefile names, and column names
  (`uid_column='uid'`, `h3_column='h3_index'`, `group_column='group'`).
- **Stage 2 — pipeline arguments** (`hub_project_status_calculator.py`):
  `uid_columns` (which list columns to combine, default the three
  `intersecting_*`), `group_col` (default `group`), and `encoding`.

Continue to **[3. Process Workflow](03_process_workflow.md)** for the step-by-step
run.
</content>
