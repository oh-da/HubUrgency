# Appendix A — Code Documentation

A reference for every module, class, and public function in the `huburgency`
package. This appendix documents the code **as written**; for the conceptual
"why", see [Chapter 4](04_model_methodology.md).

```
src/huburgency/
├── __init__.py                         # package exports (version 1.0.0)
├── inventar_hub_linker.py              # Stage 1 — spatial linking
└── hub_project_status_calculator.py    # Stage 2 — weighted progress
```

The package re-exports the main classes, so both
`from huburgency.inventar_hub_linker import InventarHubLinker` and
`from huburgency import InventarHubLinker` work.

---

## A.1 `inventar_hub_linker.py` — Stage 1

Links infrastructure projects to hubs via H3 spatial intersection. Designed around
SOLID principles: each class has one responsibility, geometry loaders are
interchangeable behind a `Protocol`, and the orchestrator depends on abstractions.

### A.1.1 `ProcessingConfig` (dataclass)
Holds all paths and settings for a Stage-1 run.

| Field | Default | Purpose |
|-------|---------|---------|
| `hubs_csv_path` | — | Path to the hubs CSV (coerced to `Path`). |
| `inventar_directory` | — | Directory containing the three shapefiles. |
| `output_csv_path` | — | Output path; suffixes added for combined/exploded. |
| `encoding` | `'windows-1255'` | File encoding for read/write. |
| `point_shapefile` / `line_shapefile` / `multiline_shapefile` | `geom_point.shp` / `geom_line.shp` / `geom_multiline.shp` | Shapefile names. |
| `uid_column` | `'uid'` | UID column in shapefiles. |
| `h3_column` | `'h3_index'` | H3-list column in hubs CSV. |
| `group_column` | `'group'` | Hub group ID column. |

- `__post_init__()` — converts string paths to `Path`.
- `validate()` — raises `FileNotFoundError` if the hubs CSV or Inventar directory
  is missing.

### A.1.2 `H3ListParser`
`parse(value) -> List[str]` *(static)* — parses a string like
`"['8a..', '8a..']"` into a list of H3 index strings; strips brackets, quotes, and
whitespace; returns `[]` for `NaN`/non-strings.

### A.1.3 `HubDataLoader`
Constructed with a `ProcessingConfig`.
- `load() -> DataFrame` — reads the hubs CSV, parses the H3 column with
  `H3ListParser`, keeps the relevant columns that exist, and `explode()`s the H3
  list so there is **one row per H3 cell**.

### A.1.4 `GeometryLoader` (Protocol)
The interface every loader satisfies: a `load() -> GeoDataFrame` method and a
`name` property. Enables Open/Closed extensibility — add new geometry sources
without touching the orchestrator.

### A.1.5 `ShapefileLoader`
`ShapefileLoader(filepath, geometry_name)` implements `GeometryLoader`.
`load()` reads the shapefile into a GeoDataFrame; if the file is missing it logs a
warning and returns an **empty** GeoDataFrame (run continues).

### A.1.6 `InventarLoaderFactory`
`create_all_loaders() -> Dict[str, GeometryLoader]` — builds the three
`ShapefileLoader`s keyed `'points'`, `'lines'`, `'multilines'`.

### A.1.7 `H3PolygonConverter`
- `convert(h3_index) -> Optional[Polygon]` *(static)* — converts an H3 index to a
  Shapely `Polygon` in WGS84, swapping H3's `(lat, lon)` to Shapely's `(lon, lat)`.
  Returns `None` on failure.
- `convert_series(series) -> Series` *(class method)* — applies `convert` to a
  Series.

### A.1.8 `SpatialIntersector`
`SpatialIntersector(target_gdf, uid_column='uid')` wraps the geometries to test
against.
- `find_intersecting_uids(query_polygon) -> List` — two-stage intersection:
  R-tree bounding-box pre-filter (`gdf.sindex.intersection(bounds)`) then precise
  `intersects()`; returns the `uid`s of matches. Empty input / `None` polygon →
  `[]`.

### A.1.9 `IntersectionResult` (dataclass)
A typed container (`h3_index`, `group`, and the three intersecting lists). Present
for structured results; the main flow uses DataFrame columns directly.

### A.1.10 `ResultTransformer`
Stateless transforms between output shapes.
- `combine_project_uids(df) -> DataFrame` *(static)* — adds `all_project_uids`,
  the order-preserving de-duplicated union of the three `intersecting_*` lists.
- `explode_by_project(df, uid_column='all_project_uids') -> DataFrame` *(static)* —
  explodes to one row per UID, renames to `project_uid`; **keeps** zero-project
  rows as `NaN`. Raises `ValueError` if the column is missing.
- `create_hub_project_mapping(df) -> DataFrame` *(class method)* — convenience:
  combine then explode in one call.

### A.1.11 `InventarHubLinker` (orchestrator)
`InventarHubLinker(config)` wires together the loaders, factory, and converter.
- `process() -> DataFrame` — the full Stage-1 pipeline: validate → load hubs →
  load geometries → H3→polygon → intersect all types → drop the temp polygon
  column. Returns the **base** DataFrame.
- `_load_all_geometries()`, `_compute_all_intersections()`,
  `_log_intersection_summary()` — internal helpers (load layers; loop hexagons ×
  geometry types logging every 1,000 rows; log per-type hit counts).
- `save(df, suffix='') -> Path` — writes a DataFrame, inserting `suffix` before
  the extension; creates the output directory if needed.
- `process_and_save_all_formats() -> Dict[str, DataFrame]` — runs `process()` and
  saves **base**, **combined**, and **exploded**; returns all three keyed
  `'base'`, `'combined'`, `'exploded'`.

### A.1.12 Module-level functions
- `link_inventar_to_hubs(hubs_csv, inventar_dir, output_csv, encoding='windows-1255', create_all_formats=True) -> Dict` —
  one-call convenience wrapper around config + linker.
- `combine_and_explode_projects(df) -> DataFrame` — post-process an existing base
  DataFrame into the exploded mapping.
- `get_hubs_with_projects(df) -> DataFrame` — filter to hubs with at least one
  intersecting project.
- `main()` — argparse CLI (`--hubs/-H`, `--inventar/-I`, `--output/-o`,
  `--encoding/-e`).

---

## A.2 `hub_project_status_calculator.py` — Stage 2

Joins project status onto linked hubs and computes weighted progress. Also
SOLID-structured: single-responsibility classes behind a pipeline facade.

### A.2.1 `DataTypeHandler`
Guards aggregation against `object`-dtype columns (the historical
`TypeError: agg function failed` fix).
- `to_numeric_safe(series, column_name='') -> Series` *(static)* — returns numeric
  as-is, otherwise `pd.to_numeric(errors='coerce')`, warning on coercion losses.
- `ensure_numeric_columns(df, columns) -> DataFrame` *(static)* — applies the
  above to a list of columns.

### A.2.2 `DataLoader`
- `load_csv(filepath, encoding='windows-1255') -> DataFrame` *(static)* — loads a
  CSV; falls back to `utf-8-sig` on `UnicodeDecodeError`.
- `validate_columns(df, required_cols, name)` *(static)* — raises `ValueError`
  listing any missing required columns.

### A.2.3 `ListColumnParser`
Turns string-encoded lists back into real lists.
- `parse_list_column(value) -> list` *(static)* — handles real lists, `NaN`/`None`,
  `"[]"`, and string lists via `ast.literal_eval` with a manual-split fallback.
- `parse_dataframe_column(df, column) -> DataFrame` *(static)* — applies it to a
  column.

### A.2.4 `load_hub_csv(filepath, list_columns=None, encoding='windows-1255')`
Module-level convenience: loads a hub CSV and auto-parses the list columns
(default the three `intersecting_*`). **Use this** when reading Stage-1 output so
the calculator sees lists, not strings.

### A.2.5 `ProjectDataJoiner`
`ProjectDataJoiner(hub_df, project_df)` — validates the project columns
(`REQUIRED_PROJECT_COLS = ['uid','proj_name','main_type','Proj_status','scn_year']`)
on construction.
- `join_to_hubs(uid_columns=None) -> DataFrame` — combine UID columns → explode to
  one row per (hub, uid) → cast `uid` to `str` → left-merge project attributes;
  logs the match rate. `uid_columns` defaults to the three `intersecting_*`.
- `_combine_uids(uid_columns)` / `_explode_uids(df)` — internal steps (per-row
  de-dup; explode + drop empty/null UIDs).

### A.2.6 `StatusProgressCalculator`
`StatusProgressCalculator(status_weights_df)` — validates
`REQUIRED_WEIGHT_COLS = ['Proj_status','weight']`, builds the
`Proj_status(str) → weight` lookup, and records `max(weight)`.
- `calculate_hub_progress(hub_projects_df, group_col='group') -> DataFrame` —
  maps status→weight, ensures numeric types, groups by hub and computes
  `total_projects`, `current_weighted_sum`, `max_possible_sum`,
  `unique_statuses`, and `status_progress_pct`.
- `calculate_status_breakdown(hub_projects_df, group_col='group') -> DataFrame` —
  pivots `group × Proj_status` into `num_proj_status_X` columns plus
  `total_projects`.
- `_map_status_to_weight(df)` — adds `status_weight`; unmapped → 0 with a warning.
- `_prepare_for_aggregation(df)` — coerces `status_weight` numeric and
  `Proj_status` string.

### A.2.7 `HubProjectStatusPipeline` (facade)
`HubProjectStatusPipeline(hub_df, project_df, status_weights_df)` — injects a
`ProjectDataJoiner` and a `StatusProgressCalculator` (Dependency Inversion).
- `run(uid_columns=None, group_col='group') -> (joined_df, progress_df, status_breakdown_df)` —
  executes join → progress → breakdown; stores each on the instance.
- `get_status_zero_projects() -> Optional[DataFrame]` — rows with
  `status_weight == 0`; maps weights first if needed; `None` before `run()`.
- `save_results(joined_path, progress_path, status_breakdown_path=None, status_zero_path=None, encoding='windows-1255')` —
  writes the outputs; creates parent dirs; raises if `run()` hasn't executed.

### A.2.8 `fix_scn_year_dtype(df) -> DataFrame`
Module-level quick fix: coerces `scn_year` to numeric on an existing DataFrame.
Superseded by `DataTypeHandler` inside the pipeline; kept for ad-hoc use.

---

## A.3 Tests — `tests/test_calculator.py`

Self-contained `pytest` tests for the calculator and linker helpers. All hub,
project, and status-weight data is built in-memory via fixtures, so no external
CSV files are required. Run with `pytest tests/` (or just `pytest`) from the
repository root. Coverage includes:
- `ListColumnParser` parsing of string/list/empty/None inputs.
- Pipeline execution returning `(joined_df, progress_df, status_breakdown_df)`.
- A numeric correctness check of `status_progress_pct`.
- Per-group UID deduplication.
- Validation errors for missing project columns and unmapped statuses.
- `get_hubs_with_projects` filtering (regression test for the operator-precedence fix).

---

## A.4 SOLID design summary

| Principle | Where it shows up |
|-----------|-------------------|
| **Single Responsibility** | `HubDataLoader` loads, `H3PolygonConverter` converts, `SpatialIntersector` intersects, `StatusProgressCalculator` scores. |
| **Open/Closed** | New geometry sources via `GeometryLoader`/`InventarLoaderFactory`; new scoring via subclassing `StatusProgressCalculator`. |
| **Liskov Substitution** | Any `GeometryLoader` implementation is interchangeable in the factory. |
| **Interface Segregation** | The `GeometryLoader` protocol declares only `load()` and `name`. |
| **Dependency Inversion** | `InventarHubLinker` and `HubProjectStatusPipeline` depend on injected abstractions, not concrete classes. |

### Extending the progress model
```python
from huburgency import StatusProgressCalculator

class CostWeightedCalculator(StatusProgressCalculator):
    """Weight each project's contribution by its cost."""
    def calculate_hub_progress(self, df, group_col="group"):
        result = super().calculate_hub_progress(df, group_col)
        # ... fold in cost-weighted metrics and merge onto result ...
        return result

pipeline = HubProjectStatusPipeline(hub_df, project_df, weights_df)
pipeline.calculator = CostWeightedCalculator(weights_df)   # swap in
```

### Adding a geometry type
```python
from huburgency.inventar_hub_linker import ShapefileLoader

class PolygonLoader(ShapefileLoader):
    def __init__(self, filepath):
        super().__init__(filepath, "polygons")
```
Register it in a `InventarLoaderFactory` subclass and the orchestrator picks it up
unchanged.
</content>
