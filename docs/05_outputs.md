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

## 5.3 End-to-end workflow outputs

`run_end_to_end(input_dir, output_dir)` (or the notebooks) writes, into one folder:

| File | Content |
|------|---------|
| `hubs_with_inventar[_combined/_exploded].csv` | Stage 1 outputs (5.1) |
| `project_hub_links.csv` | **written right after Stage 1, before scoring.** One row per (project `uid`, hub `group`): `proj_name`, `main_type`, current `Proj_status`, `group`, `HubNameHE`, `intersecting_h3` (Python list of the hub's H3 cells the project touches, same notation as the hubs CSV's `h3_index`) and `n_intersecting_cells`. A project touching several hubs has several rows; projects touching no hub are absent |
| `status_overrides_template.csv` | **written with the file above.** One row per linked project: `uid`, `Proj_status` (current), `proj_name`, `main_type`, `n_hubs`, `hubs` (e.g. `12 Hub A; 15 Hub B`). Edit `Proj_status`, save as `status_overrides.csv` in the input folder and re-run; unchanged rows are no-ops and the extra columns are ignored |
| `hub_project_joined.csv` | one row per (hub, project) with final status; adds `Proj_status_original` and `status_overridden` |
| `hub_progress.csv` | per-hub progress (5.2.2) plus `x`, `y`, `HubNameHE` |
| `hub_status_breakdown.csv` | project counts per status (5.2.3) |
| `status_zero_projects.csv` | projects whose status has weight 0 (zero-project hubs excluded) |
| `status_weights_template.csv` | the statuses found in the data with suggested weights, ready to edit |
| `selected_hubs_report.xlsx` | only if a hub list is given (`hub_selection.csv` in the input folder). Sheet **Summary**: run date, urgency rule, hubs requested / in report / urgent / not urgent, hub ids not found, then one row per hub: `group`, `HubNameHE`, `total_projects`, `current_weighted_sum`, `max_possible_sum`, `unique_statuses`, `status_progress_pct`, `Urgency`. Sheet **Projects**: one row per (hub, project): `group`, `HubNameHE`, `project_uid`, `proj_name`, `main_type`, `Proj_status` (final), `Proj_status_original`, `status_overridden`, `status_progress_pct`, `Urgency`; a hub without projects has one row with the project columns empty |
| `hub_urgency_report.html` | self-contained report: key figures, warnings (unmapped statuses, unknown override UIDs, hubs without projects), status counts, overrides, progress histogram, top/bottom 15 hubs |
| `hub_urgency_map.html` | interactive Leaflet map: hub H3 cells coloured by progress (grey = no projects), project geometries coloured by status weight, tooltips with names and status mix |

The map is a normal HTML file: it loads Leaflet and the basemap from the internet,
so it needs a connection when opened (the hub and project data are embedded).
Pass `make_report=False` to skip the two HTML files.

**Report for selected hubs.** Put a CSV with a `group` column (hub ids; a single-column file with another header or none also works) in the input folder as `hub_selection.csv`, or pass `hub_selection_csv=`. `Urgency` is `דחוף` when `status_progress_pct >= urgent_threshold` (default 50), otherwise `לא דחוף`. Ids not found in the results are listed in the Summary and left out. To get the report for another list **without re-running** the pipeline:

```python
from huburgency import selected_hubs_report
selected_hubs_report('path/to/output', 'path/to/hub_list.csv')   # reads hub_progress.csv + hub_project_joined.csv
```

**Building the status overrides.** Run with `link_only=True` (the *Link only* checkbox in the
interactive notebook, `LINK_ONLY` in the other one): the run stops right after Stage 1 and
needs no weights file. Open `project_hub_links.csv` to see which hubs and H3 cells each project
touches, change `Proj_status` in `status_overrides_template.csv`, save it as
`status_overrides.csv` in the input folder and run again without `link_only`.

## 5.4 Quick analysis recipes

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
