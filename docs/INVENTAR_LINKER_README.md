# Inventar Projects to Hubs Linker

Links infrastructure inventory projects to transit hubs via H3 hexagonal spatial intersection.

## Overview

This module is **Part 4** of the Hub Prioritization Pipeline. It enriches the hub dataset by identifying which planned infrastructure projects (from the "Inventar") spatially intersect with each hub's H3 hexagonal cells.

```
Hub Processing Pipeline Output    →    Inventar Linker    →    Hubs with Project UIDs
(h3_index, group, x, y, ...)          (spatial join)           (+ intersecting_points,
                                                                  intersecting_lines,
                                                                  intersecting_multilines)
```

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         INVENTAR HUB LINKER                                 │
│                                                                             │
│  ┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐    │
│  │  HubDataLoader   │     │ InventarFactory  │     │ H3PolygonConvert │    │
│  │  ──────────────  │     │  ─────────────   │     │  ──────────────  │    │
│  │  • Load CSV      │     │  • Points loader │     │  • H3 → Polygon  │    │
│  │  • Parse H3 list │     │  • Lines loader  │     │  • WGS84 coords  │    │
│  │  • Explode rows  │     │  • Multilines    │     │                  │    │
│  └────────┬─────────┘     └────────┬─────────┘     └────────┬─────────┘    │
│           │                        │                        │              │
│           └────────────────────────┼────────────────────────┘              │
│                                    │                                        │
│                       ┌────────────▼────────────┐                          │
│                       │   SpatialIntersector    │                          │
│                       │   ─────────────────     │                          │
│                       │   • R-tree spatial idx  │                          │
│                       │   • Bbox pre-filter     │                          │
│                       │   • Precise intersect   │                          │
│                       └────────────┬────────────┘                          │
│                                    │                                        │
│                       ┌────────────▼────────────┐                          │
│                       │    InventarHubLinker    │                          │
│                       │    ─────────────────    │                          │
│                       │    • Orchestration      │                          │
│                       │    • Result aggregation │                          │
│                       │    • Output generation  │                          │
│                       └─────────────────────────┘                          │
└─────────────────────────────────────────────────────────────────────────────┘
```

## SOLID Principles Applied

| Principle | Implementation |
|-----------|----------------|
| **S**ingle Responsibility | Each class does one thing: `HubDataLoader` loads, `H3PolygonConverter` converts, `SpatialIntersector` intersects |
| **O**pen/Closed | New geometry types can be added via `InventarLoaderFactory` without modifying core logic |
| **L**iskov Substitution | All loaders implement `GeometryLoader` protocol and are interchangeable |
| **I**nterface Segregation | `GeometryLoader` protocol has minimal required methods |
| **D**ependency Inversion | `InventarHubLinker` depends on abstractions, not concrete implementations |

## Installation

```bash
# From the repository root
pip install -e .
```

Installs `geopandas`, `pandas`, `numpy`, `shapely`, and `h3>=4.0.0`.

## Usage

### Python API

```python
from huburgency import link_inventar_to_hubs, combine_and_explode_projects

# Run full pipeline (creates 3 output files automatically)
results = link_inventar_to_hubs(
    hubs_csv='/path/to/Results_29-12-2025.csv',
    inventar_dir='/path/to/Inventar',
    output_csv='/path/to/Hubs_with_Inventar.csv'
)

# Access different output formats
base_df = results['base']          # One row per H3 cell
combined_df = results['combined']  # Same + all_project_uids column
exploded_df = results['exploded']  # One row per (H3 cell, project) pair

print(f"H3 cells: {len(base_df)}")
print(f"Hub-project pairs: {len(exploded_df)}")
```

### Command Line

```bash
python inventar_hub_linker.py \
    --hubs /data/Results_29-12-2025.csv \
    --inventar /data/Inventar \
    --output /data/Hubs_with_Inventar.csv
```

This creates three files:
- `Hubs_with_Inventar.csv` - Base output
- `Hubs_with_Inventar_combined.csv` - With `all_project_uids` column
- `Hubs_with_Inventar_exploded.csv` - One row per project UID

### Advanced Usage

```python
from huburgency import ProcessingConfig, InventarHubLinker
from huburgency.inventar_hub_linker import ResultTransformer

# Custom configuration
config = ProcessingConfig(
    hubs_csv_path='/data/Results.csv',
    inventar_directory='/data/Inventar',
    output_csv_path='/data/Output.csv',
    encoding='utf-8',  # Override default encoding
    uid_column='project_id'  # Use different UID column
)

# Process
linker = InventarHubLinker(config)
base_df = linker.process()

# Transform to different formats
combined_df = ResultTransformer.combine_project_uids(base_df)
exploded_df = ResultTransformer.explode_by_project(combined_df)

# Or use the convenience method for all formats
results = linker.process_and_save_all_formats()
```

### Post-processing Existing Data

```python
from huburgency import combine_and_explode_projects
import pandas as pd

# Load existing output
df = pd.read_csv('hubs_with_inventar.csv')

# Create exploded view
exploded = combine_and_explode_projects(df)
```

## Input/Output Schema

### Input: Hub Results CSV

From Transit Hub Processing Pipeline (Part 1-3):

| Column | Type | Description |
|--------|------|-------------|
| group | int | Proximity group ID |
| x | float | Centroid X (EPSG:2039) |
| y | float | Centroid Y (EPSG:2039) |
| HubNameHE | str | Hebrew hub name |
| h3_index | str | List of H3 indices as string |

### Input: Inventar Shapefiles

| File | Geometry | Example Content |
|------|----------|-----------------|
| geom_point.shp | Point | Station locations, intersections |
| geom_line.shp | LineString | Road segments, transit alignments |
| geom_multiline.shp | MultiLineString | Complex corridors |

All shapefiles must have a `uid` column.

### Output Files

The pipeline generates **three output files**:

#### 1. Base Output (`{name}.csv`)
One row per H3 cell with intersection lists.

| Column | Type | Description |
|--------|------|-------------|
| group | int | Proximity group ID |
| x | float | Centroid X |
| y | float | Centroid Y |
| HubNameHE | str | Hebrew hub name |
| h3_index | str | Single H3 index (exploded) |
| intersecting_points | list | UIDs from geom_point.shp |
| intersecting_lines | list | UIDs from geom_line.shp |
| intersecting_multilines | list | UIDs from geom_multiline.shp |

#### 2. Combined Output (`{name}_combined.csv`)
Same as base, plus combined UID column.

| Additional Column | Type | Description |
|-------------------|------|-------------|
| all_project_uids | list | Unique UIDs from all geometry types combined |

#### 3. Exploded Output (`{name}_exploded.csv`)
One row per (H3 cell, project UID) pair - ideal for SQL-style joins.

| Column | Type | Description |
|--------|------|-------------|
| group | int | Proximity group ID |
| h3_index | str | Single H3 index |
| project_uid | any | Single project UID (one per row) |
| ... | ... | Other hub columns |

**Note:** The exploded output preserves hub cells with **no** intersecting projects as rows with `project_uid = NaN` (so no hub silently disappears). `ResultTransformer.explode_by_project()` explodes empty lists into NaN rows and logs both the with-project and zero-project counts. To keep only rows that have a project, filter afterwards: `exploded_df = exploded_df[exploded_df['project_uid'].notna()]`.

## Technical Details

### H3 to Polygon Conversion

H3 indices are in WGS84 (EPSG:4326). The conversion:

```python
# H3 returns (lat, lon) - geographic coordinates
geo_boundary = h3.cell_to_boundary(h3_index)

# Shapely expects (lon, lat) = (x, y)
polygon = Polygon([(lon, lat) for lat, lon in geo_boundary])
```

### Spatial Indexing Strategy

Two-stage filtering for performance:

1. **Bounding box filter** via R-tree spatial index (fast)
2. **Precise intersection** only on candidates (accurate)

```python
# Stage 1: O(log n) bbox query
candidates = gdf.sindex.intersection(polygon.bounds)

# Stage 2: Precise check on small subset
intersecting = candidates[candidates.intersects(polygon)]
```

### CRS Considerations

The Inventar shapefiles should be in the same CRS as the H3 polygons (WGS84/EPSG:4326) for intersection to work correctly. If they're in Israel TM Grid (EPSG:2039), you'll need to transform:

```python
gdf = gdf.to_crs('EPSG:4326')
```

## Performance

| Dataset Size | Processing Time | Memory |
|--------------|-----------------|--------|
| 1,000 H3 cells | ~30 sec | ~200 MB |
| 10,000 H3 cells | ~3 min | ~500 MB |
| 50,000 H3 cells | ~15 min | ~1 GB |

## Troubleshooting

### Empty intersection results

1. **CRS mismatch**: Ensure shapefiles and H3 polygons are in same CRS
2. **Invalid H3 indices**: Check H3 parsing with `h3.cell_to_boundary(index)`
3. **No spatial overlap**: Visualize both datasets on a map

### Memory issues

For very large datasets, process in chunks:

```python
chunk_size = 10000
for i in range(0, len(hub_df), chunk_size):
    chunk = hub_df.iloc[i:i+chunk_size]
    # Process chunk...
```

### Hebrew encoding issues

Default is `windows-1255`. For UTF-8 files:

```python
config = ProcessingConfig(..., encoding='utf-8-sig')
```

## Integration with Hub Prioritization Pipeline

This module fits after Part 3 (Influence Area Processing):

```
Part 1: H3 Processing → Part 2: Demand → Part 3: Influence → Part 4: Inventar Linking
```

The output can be used to:
- Identify hubs affected by planned infrastructure
- Prioritize hubs based on project proximity
- Analyze infrastructure investment coverage
