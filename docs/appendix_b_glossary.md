# Appendix B — Glossary & FAQ

## B.1 Glossary

| Term | Meaning |
|------|---------|
| **Hub** | A transit hub, identified by a `group` ID. Represented spatially as a set of H3 hexagons, not a single point. |
| **Group** | The integer hub identifier; the key everything is aggregated by. |
| **H3** | Uber's hierarchical hexagonal geospatial index. Each `h3_index` string (e.g. `8a2a1072b59ffff`) names one hexagon. |
| **Inventar** | The collection of planned infrastructure project geometries, stored as three shapefiles (points, lines, multilines). |
| **UID (`uid`)** | Unique project identifier; the join key between the Inventar geometries and the project attribute data. |
| **Project status** | An engineering lifecycle stage (e.g. detailed design, under construction). Stored as `Proj_status`. |
| **Weight** | A `0.0–1.0` value mapping a status to a fraction of lifecycle completion. |
| **Progress (`status_progress_pct`)** | Per-hub weighted completion percentage — the headline metric. |
| **Status-zero project** | A project whose `status_weight` is 0 (not started / cancelled / on hold / unmapped). |
| **Intersection** | The geometric test that links a project to a hub: any overlap between a project geometry and a hub hexagon. |
| **R-tree / spatial index** | The bounding-box index (`GeoDataFrame.sindex`) used to make intersection fast. |
| **CRS** | Coordinate Reference System. H3 polygons are WGS84 (EPSG:4326); inputs may be Israel TM Grid (EPSG:2039). |

## B.2 Encodings and Hebrew text

- The default file encoding is **`windows-1255`** so Hebrew hub names
  (`HubNameHE`) round-trip correctly.
- `DataLoader.load_csv()` falls back to **`utf-8-sig`** on a decode error.
- If Hebrew shows as gibberish, the file is probably UTF-8; pass
  `encoding='utf-8-sig'`.

## B.3 CRS — the most common source of empty results

H3 polygons are built in **WGS84 (EPSG:4326)**. If your shapefiles are in
**EPSG:2039** (Israel TM Grid), every intersection test fails silently (the
geometries are in different coordinate spaces). Reproject first:

```python
import geopandas as gpd
gdf = gpd.read_file("geom_point.shp").to_crs("EPSG:4326")
gdf.to_file("geom_point.shp")
```

## B.4 FAQ / Troubleshooting

**Q: All `intersecting_*` columns are empty.**
CRS mismatch (see B.3), invalid H3 indices, or genuinely no spatial overlap.
Verify a single conversion with `h3.cell_to_boundary(index)` and check
`gdf.crs`.

**Q: Stage 2 produces empty or tiny results.**
Usually a UID type mismatch or unparsed list columns. Load the hub file with
`load_hub_csv()` (parses lists), and ensure both sides cast `uid` to `str`
(`join_to_hubs` does this). Confirm the list columns really are lists:
`type(hub_df['intersecting_points'].iloc[0])` should be `list`.

**Q: `TypeError: agg function failed [how->mean,dtype->object]`.**
Already handled by `DataTypeHandler`, which coerces numeric columns before
aggregation. If you hit it on a custom DataFrame, call
`fix_scn_year_dtype(df)` or `DataTypeHandler.to_numeric_safe(...)`.

**Q: Warning about unmapped status values.**
A `Proj_status` in the project data has no row in the weights table. It is treated
as weight 0 (lowering progress and counting as status-zero). Add the missing
status to the weights CSV.

**Q: Progress is always 0% or 100%.**
Weights are probably binary (0/1) instead of graded. Use decimal weights across
`0.0–1.0`.

**Q: The weights file column is `Proj_status_id` — it fails.**
The current code requires the column to be named **`Proj_status`**. Rename it.

**Q: A project appears under more than one hub.**
Expected — a line crossing several hubs links to each. Within a hub it is counted
once (per-group dedup).

## B.5 Performance notes

| Operation | Size | Approx time | Approx memory |
|-----------|------|-------------|---------------|
| Spatial intersection | 1,000 cells | ~30 s | ~200 MB |
| Spatial intersection | 10,000 cells | ~3 min | ~500 MB |
| Spatial intersection | 50,000 cells | ~15 min | ~1 GB |
| Status calculation | 1,000 hubs / 10k projects | ~30–60 s | ~500 MB |

Tips: process hexagons in chunks for very large hub sets; pre-filter projects by
`scn_year` before joining; use `category` dtype for repeated strings like
`HubNameHE`.

## B.6 Dependencies

From `requirements.txt`:

| Package | Min version | Role |
|---------|-------------|------|
| pandas | 2.0.0 | Tabular data, joins, aggregation |
| numpy | 1.24.0 | Numerics |
| geopandas | 0.14.0 | Shapefile I/O, spatial ops |
| shapely | 2.0.0 | Geometry / intersection |
| h3 | 4.0.0 | Hexagonal indexing, cell→polygon |
| jupyter | 1.0.0 | Notebooks |
| matplotlib | 3.7.0 | Visualization |
| pytest | 7.4.0 | Testing (dev) |

> The code calls `h3.cell_to_boundary(...)` returning `(lat, lon)` tuples; ensure
> your installed H3 version's API matches (H3 v4 naming).

## B.7 Notebooks

Two notebooks under `notebooks/` mirror the two stages interactively:
- `inventar_hub_linker_notebook.ipynb` — Stage 1 exploration.
- `Hub_Project_Status_Analysis.ipynb` — Stage 2 analysis and charts.
</content>
