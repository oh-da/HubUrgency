# 5. Outputs

Every file the pipeline can produce, and the meaning of every column.

## 5.1 Stage 1 outputs (Inventar Hub Linker)

`process_and_save_all_formats()` writes three files derived from a single base
output. If the output path is `Hubs_with_Inventar.csv`, the files are:

| File | Grain | Built by |
|------|-------|----------|
| `Hubs_with_Inventar.csv` | one row per H3 hexagon | `process()` |
| `Hubs_with_Inventar_combined.csv` | one row per H3 hexagon | + `combine_project_uids()` |
| `Hubs_with_Inventar_exploded.csv` | one row per (hexagon, project) | + `explode_by_project()` |

### 5.1.1 Base output

| Column | Type | Description |
|--------|------|-------------|
| `group` | int | Hub group ID |
| `x`, `y` | float | Hub centroid coordinates (EPSG:2039, carried from input) |
| `HubNameHE` | str | Hebrew hub name |
| `h3_index` | str | A **single** H3 cell index (after explode) |
| `intersecting_points` | list | Project UIDs from `geom_point.shp` intersecting this cell |
| `intersecting_lines` | list | Project UIDs from `geom_line.shp` |
| `intersecting_multilines` | list | Project UIDs from `geom_multiline.shp` |

### 5.1.2 Combined output
Base **plus**:

| Column | Type | Description |
|--------|------|-------------|
| `all_project_uids` | list | De-duplicated union of the three `intersecting_*` lists, order preserved |

This is the recommended file to feed into Stage 2 (it still carries the three
`intersecting_*` columns the calculator combines).

### 5.1.3 Exploded output
One row per (hexagon, single project):

| Column | Type | Description |
|--------|------|-------------|
| `group` | int | Hub group ID |
| `h3_index` | str | Single H3 cell |
| `project_uid` | any | A single project UID (one per row) |
| … | … | Other hub columns carried along |

Hexagons with **no** intersecting projects are kept with `project_uid = NaN`, so
no hub silently disappears. Ideal for SQL-style joins to the project table.

---

## 5.2 Stage 2 outputs (Status Calculator)

`save_results()` writes up to four files.

### 5.2.1 Joined data — `hubs_with_project_data.csv`
One row per hub–project link, with project attributes and the mapped weight.

| Column | Type | Description |
|--------|------|-------------|
| `group` | int | Hub group ID |
| `h3_index` | str | Hub cell (carried from Stage 1) |
| `uid` | str | Linked project UID |
| `proj_name` | str | Project name (from project data) |
| `main_type` | str | Project type/mode |
| `Proj_status` | str | Project status code |
| `scn_year` | numeric | Scenario/planned year |
| `status_weight` | float | Weight looked up for `Proj_status` (0 if unmapped) |

(plus any other hub columns carried through the join, e.g. `all_project_uids`).

### 5.2.2 Progress summary — `hub_status_progress.csv`
**The headline output: one row per hub.**

| Column | Type | Description |
|--------|------|-------------|
| `group` | int | Hub group ID |
| `total_projects` | int | Number of (de-duplicated) projects linked to the hub |
| `current_weighted_sum` | float | Σ of project `status_weight` |
| `max_possible_sum` | float | `total_projects × max_weight` |
| `unique_statuses` | int | Distinct status codes present in the hub |
| `status_progress_pct` | float | **Weighted progress, 0–100%** (see [Chapter 4](04_model_methodology.md)) |

### 5.2.3 Status breakdown — `hub_status_breakdown.csv`
One row per hub; one column per observed status.

| Column | Type | Description |
|--------|------|-------------|
| `group` | int | Hub group ID |
| `num_proj_status_0`, `num_proj_status_1`, … | int | Count of projects in the hub at each status code |
| `total_projects` | int | Sum across the `num_proj_status_*` columns |

Use `num_proj_status_0` directly as the per-hub **status-zero count**.

### 5.2.4 Status-zero rows — `hub_status_zero_report.csv`
Written only if there are zero-weight projects. As produced by the current code,
this is the **project-level** set of hub–project rows where `status_weight == 0`
(same columns as the joined data). To get a per-hub stalled-rate table:

```python
zero = pipeline.get_status_zero_projects()
per_hub = (
    zero.groupby("group").size().rename("status_zero_count").reset_index()
    .merge(progress_df[["group", "total_projects"]], on="group")
)
per_hub["status_zero_pct"] = 100 * per_hub["status_zero_count"] / per_hub["total_projects"]
```

---

## 5.3 Quick analysis recipes

**Top hubs needing attention** (low progress, many projects):
```python
critical = progress_df[
    (progress_df["status_progress_pct"] < 40) &
    (progress_df["total_projects"] >= 5)
].sort_values("total_projects", ascending=False)
```

**Most-advanced hubs:**
```python
progress_df.nlargest(20, "status_progress_pct")
```

**Hubs with the most stalled projects:**
```python
breakdown_df.nlargest(10, "num_proj_status_0")[["group", "num_proj_status_0", "total_projects"]]
```

See **[Appendix A](appendix_a_code_reference.md)** for the code reference and
**[Appendix B](appendix_b_glossary.md)** for terms and troubleshooting.
</content>
