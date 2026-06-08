# Hubs Urgency - Project Documentation

**Hub Project Status Analysis & Infrastructure Linking System**

A comprehensive pipeline for analyzing transit hub priority based on infrastructure project status and spatial intersection with planned developments.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Installation](#installation)
4. [Quick Start](#quick-start)
5. [Modules](#modules)
6. [Data Pipeline](#data-pipeline)
7. [Output Files](#output-files)
8. [Usage Guides](#usage-guides)
9. [Troubleshooting](#troubleshooting)
10. [Development](#development)

---

## Overview

### What This System Does

The Hubs Urgency system provides two integrated capabilities:

1. **Infrastructure Project Linking** (`inventar_hub_linker.py`)
   - Links planned infrastructure projects to transit hubs using H3 hexagonal spatial intersection
   - Identifies which projects (points, lines, multilines) intersect with each hub's area
   - Outputs hub-to-project mappings for further analysis

2. **Project Status Analysis** (`hub_project_status_calculator.py`)
   - Calculates weighted progress metrics for each hub based on project statuses
   - Identifies hubs with stalled/cancelled projects (status = 0)
   - Provides hub prioritization data based on project execution progress

### Key Features

- ✅ **SOLID Architecture**: Clean, maintainable, extensible code following SOLID principles
- ✅ **Spatial Analysis**: H3 hexagonal grid-based spatial intersection
- ✅ **Weighted Progress**: Configurable status weights for nuanced progress tracking
- ✅ **Hebrew Support**: Full support for Hebrew text (windows-1255 encoding)
- ✅ **Multiple Output Formats**: Base, combined, and exploded views
- ✅ **Production Ready**: Comprehensive error handling and validation

### Use Cases

- **Hub Prioritization**: Identify which hubs need urgent attention based on project progress
- **Investment Planning**: Analyze infrastructure investment distribution across hubs
- **Risk Assessment**: Find hubs with high cancellation rates (status = 0)
- **Resource Allocation**: Prioritize resources to hubs with stalled projects
- **Progress Monitoring**: Track project execution across the transit network

---

## Architecture

### System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        HUBS URGENCY SYSTEM                          │
│                                                                     │
│  ┌──────────────────────┐         ┌──────────────────────┐        │
│  │  INVENTAR HUB LINKER │         │ STATUS CALCULATOR    │        │
│  │  (Part 1)            │  ──────>│ (Part 2)             │        │
│  │                      │         │                      │        │
│  │  • H3 Spatial Join   │         │  • Weighted Progress │        │
│  │  • Project Mapping   │         │  • Status Analysis   │        │
│  │  • UID Extraction    │         │  • Priority Scoring  │        │
│  └──────────────────────┘         └──────────────────────┘        │
│           │                                 │                       │
│           v                                 v                       │
│  Hub-Project Mappings            Hub Progress Metrics              │
└─────────────────────────────────────────────────────────────────────┘
```

### SOLID Principles Implementation

| Principle | Implementation |
|-----------|----------------|
| **Single Responsibility** | Each class has one job: `DataLoader` loads, `H3PolygonConverter` converts, `SpatialIntersector` intersects, `StatusProgressCalculator` calculates |
| **Open/Closed** | New geometry types via `InventarLoaderFactory`, new calculation methods via inheritance |
| **Liskov Substitution** | All loaders implement `GeometryLoader` protocol and are interchangeable |
| **Interface Segregation** | Minimal interfaces - each protocol only defines what's needed |
| **Dependency Inversion** | Pipeline classes depend on abstractions, not concrete implementations |

---

## Installation

### Requirements

```bash
# Install the package and its core dependencies (from the repo root)
pip install -e .

# Include notebook extras (jupyter, matplotlib)
pip install -e ".[notebooks]"
```

Core dependencies (installed automatically): `pandas`, `numpy`, `geopandas`,
`shapely`, `h3>=4.0.0`.

### System Requirements

- Python 3.10+
- 4GB RAM minimum (8GB recommended for large datasets)
- Storage: ~500MB per 10,000 hubs

---

## Quick Start

### 1. Link Infrastructure Projects to Hubs

```python
from huburgency import link_inventar_to_hubs

# Run spatial linking
results = link_inventar_to_hubs(
    hubs_csv='data/Results_29-12-2025.csv',
    inventar_dir='data/Inventar',
    output_csv='output/Hubs_with_Inventar.csv'
)

# Access different formats
base_df = results['base']          # One row per H3 cell
combined_df = results['combined']  # With all_project_uids column
exploded_df = results['exploded']  # One row per (hub, project) pair

print(f"Linked {len(exploded_df)} hub-project pairs")
```

### 2. Calculate Hub Status Progress

```python
from huburgency import (
    DataLoader,
    HubProjectStatusPipeline
)

# Load data
loader = DataLoader()
hub_df = loader.load_csv('output/Hubs_with_Inventar_combined.csv')
project_df = loader.load_csv('data/data.csv')
weights_df = loader.load_csv('data/status_weights.csv')

# Run analysis
pipeline = HubProjectStatusPipeline(hub_df, project_df, weights_df)
joined_df, progress_df, status_breakdown_df = pipeline.run()

# Save results
pipeline.save_results(
    joined_path='output/hubs_with_project_data.csv',
    progress_path='output/hub_status_progress.csv',
    status_breakdown_path='output/hub_status_breakdown.csv',
    status_zero_path='output/hub_status_zero_report.csv'
)

print(f"Analyzed {len(progress_df)} hubs")
```

> **Optional inputs.** `HubProjectStatusPipeline` also accepts
> `status_override_df` (replace `Proj_status` for selected UIDs before scoring),
> `all_hubs_df` (guarantee every hub group appears, backfilling hubs with no
> projects at 0%), and a pre-exploded input via `hub_project_df` +
> `use_pre_exploded=True`. See the
> [Usage Guide → Advanced Features](USAGE_GUIDE.md#advanced-features).

### 3. Analyze Results

```python
# Find critical hubs (low progress, high cancellation)
critical = progress_df[
    (progress_df['status_progress_pct'] < 40)
].sort_values('total_projects', ascending=False)

print("Top 10 hubs needing attention:")
print(critical.head(10)[['group', 'total_projects', 'status_progress_pct']])
```

---

## Modules

### 1. Inventar Hub Linker (`inventar_hub_linker.py`)

**Purpose**: Links infrastructure inventory projects to transit hubs via H3 spatial intersection.

**Key Classes**:
- `HubDataLoader`: Loads hub CSV and parses H3 indices
- `InventarLoaderFactory`: Creates geometry loaders for points/lines/multilines
- `H3PolygonConverter`: Converts H3 hexagons to Shapely polygons
- `SpatialIntersector`: Performs R-tree indexed spatial intersection
- `InventarHubLinker`: Main orchestrator
- `ResultTransformer`: Transforms results into different formats

**See**: [INVENTAR_LINKER_README.md](INVENTAR_LINKER_README.md) for detailed documentation.

### 2. Hub Project Status Calculator (`hub_project_status_calculator.py`)

**Purpose**: Calculates weighted project status progress for transit hubs.

**Key Classes**:
- `DataTypeHandler`: Ensures numeric columns are properly typed
- `DataLoader`: Loads and validates CSV files
- `ListColumnParser`: Parses string representations of lists
- `ProjectDataJoiner`: Joins project data to hubs based on UIDs
- `StatusProgressCalculator`: Calculates weighted progress metrics
- `HubProjectStatusPipeline`: Orchestrates the complete workflow

**See**: [USAGE_GUIDE.md](USAGE_GUIDE.md) for detailed documentation.

---

## Data Pipeline

### Complete End-to-End Pipeline

```
Step 1: H3 Processing (Existing Pipeline)
   ↓ (Hubs with H3 indices, group assignments)

Step 2: Inventar Linking (inventar_hub_linker.py)
   Input:  Hubs CSV + Inventar Shapefiles
   Output: Hubs with intersecting project UIDs
   ↓

Step 3: Status Calculation (hub_project_status_calculator.py)
   Input:  Hubs + Project Data + Status Weights
   Output: Hub progress metrics, status breakdown
   ↓

Step 4: Analysis & Prioritization
   Input:  All outputs
   Output: Priority rankings, intervention recommendations
```

### Data Flow Diagram

```
┌──────────────┐
│ Hub Results  │ (from Transit Hub Processing)
│ CSV          │
└──────┬───────┘
       │
       v
┌──────────────────────┐      ┌──────────────┐
│ Inventar Shapefiles  │──────>│  Spatial     │
│ • geom_point.shp     │       │  Intersection│
│ • geom_line.shp      │       │              │
│ • geom_multiline.shp │       └──────┬───────┘
└──────────────────────┘              │
                                      v
                           ┌──────────────────┐
                           │ Hubs with        │
                           │ Project UIDs     │
                           └─────────┬────────┘
                                     │
                        ┌────────────┴────────────┐
                        │                         │
                        v                         v
              ┌─────────────────┐      ┌─────────────────┐
              │ Project Data    │      │ Status Weights  │
              │ (data.csv)      │      │ (status_weights │
              │                 │      │  .csv)          │
              └────────┬────────┘      └────────┬────────┘
                       │                        │
                       └────────┬───────────────┘
                                v
                    ┌──────────────────────┐
                    │ Status Calculator    │
                    │                      │
                    └──────────┬───────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
              v                v                v
    ┌─────────────┐  ┌──────────────┐  ┌──────────────┐
    │ Joined Data │  │ Progress     │  │ Status       │
    │             │  │ Summary      │  │ Breakdown    │
    └─────────────┘  └──────────────┘  └──────────────┘
```

---

## Output Files

### From Inventar Hub Linker

| File | Format | Description |
|------|--------|-------------|
| `Hubs_with_Inventar.csv` | One row per H3 cell | Base output with intersection lists per geometry type |
| `Hubs_with_Inventar_combined.csv` | One row per H3 cell | Base + `all_project_uids` column with all UIDs combined |
| `Hubs_with_Inventar_exploded.csv` | One row per (H3, project) pair | Normalized format for SQL joins |

### From Status Calculator

| File | Format | Description |
|------|--------|-------------|
| `hubs_with_project_data.csv` | One row per (hub, project) pair | All hub columns + project details + status weights |
| `hub_status_progress.csv` | One row per hub | Aggregated progress metrics: total projects, weighted sum, progress % |
| `hub_status_breakdown.csv` | One row per hub | Columns: `num_proj_status_0`, `num_proj_status_1`, etc. |
| `hub_status_zero_report.csv` | One row per (hub, project) with weight=0 | Project-level rows for every status-zero (not-started/cancelled/unmapped) project, as written by `get_status_zero_projects()` |

### Key Columns Reference

#### Hub Status Progress (`hub_status_progress.csv`)

| Column | Type | Description |
|--------|------|-------------|
| `group` | int | Hub group ID |
| `total_projects` | int | Number of projects in hub |
| `current_weighted_sum` | float | Sum of actual project weights |
| `max_possible_sum` | float | Maximum possible sum (all at weight=1.0) |
| `unique_statuses` | int | Number of different status types |
| `status_progress_pct` | float | Progress percentage (0-100%) |

#### Status Zero Report (`hub_status_zero_report.csv`)

As written by the pipeline (`get_status_zero_projects()` →
`save_results(status_zero_path=...)`), this file contains the **project-level**
rows whose `status_weight == 0` — i.e. the same columns as the joined data
(`group`, `h3_index`, `uid`, `proj_name`, `main_type`, `Proj_status`, `scn_year`,
`status_weight`), filtered to weight-zero projects.

The per-hub `status_zero_count` / `status_zero_pct` table used by the analysis
examples in [STATUS_ZERO_GUIDE.md](STATUS_ZERO_GUIDE.md) is **derived** from these
rows with a short aggregation:

```python
zero = pipeline.get_status_zero_projects()              # project-level rows
per_hub = (
    zero.groupby('group').size()
        .rename('status_zero_count').reset_index()
        .merge(progress_df[['group', 'total_projects']], on='group')
)
per_hub['status_zero_pct'] = 100 * per_hub['status_zero_count'] / per_hub['total_projects']
```

| Derived column | Type | Description |
|----------------|------|-------------|
| `group` | int | Hub group ID |
| `total_projects` | int | Total number of projects in hub |
| `status_zero_count` | int | Number of status=0 projects |
| `status_zero_pct` | float | Percentage of status=0 projects |

> Equivalently, `num_proj_status_0` in `hub_status_breakdown.csv` already gives the
> per-hub status-zero count directly.

---

## Usage Guides

### Detailed Documentation by Topic

- **[USAGE_GUIDE.md](USAGE_GUIDE.md)** - Complete usage guide for Hub Project Status Calculator
  - File format requirements
  - Basic and advanced usage examples
  - Integration with existing pipeline
  - SQL analysis examples
  - Troubleshooting

- **[INVENTAR_LINKER_README.md](INVENTAR_LINKER_README.md)** - Inventar Hub Linker documentation
  - Architecture and design patterns
  - Input/output schemas
  - Technical details (H3 conversion, spatial indexing, CRS)
  - Performance benchmarks
  - Integration guide

- **[STATUS_ZERO_GUIDE.md](STATUS_ZERO_GUIDE.md)** - Status = 0 projects analysis guide
  - Interpretation of cancellation rates
  - SQL queries for analysis
  - Python analysis examples
  - Integration with progress analysis
  - Executive reporting templates

- **[FIX_DOCUMENTATION.md](FIX_DOCUMENTATION.md)** - Bug fixes and migration guide
  - Fixed: Empty DataFrames issue (list parsing)
  - Fixed: Duplicate UIDs within groups
  - Test results
  - Migration guide (100% backward compatible)

---

## Troubleshooting

### Common Issues

#### 1. Empty Results from Status Calculator

**Symptom**: `joined_df` is empty or has very few rows

**Causes & Solutions**:
```python
# Check 1: UID format mismatch
project_df['uid'] = project_df['uid'].astype(str).str.strip()

# Check 2: List columns are actually lists (not strings)
print(type(hub_df['intersecting_points'].iloc[0]))  # Should be <class 'list'>

# If strings, parse them:
from huburgency import load_hub_csv
hub_df = load_hub_csv('hubs.csv')  # Automatically parses lists
```

#### 2. Empty Spatial Intersections

**Symptom**: All `intersecting_*` columns are empty lists

**Causes**:
- CRS mismatch between H3 polygons (WGS84) and shapefiles
- Invalid H3 indices
- No actual spatial overlap

**Solutions**:
```python
# Check CRS of shapefiles
import geopandas as gpd
gdf = gpd.read_file('geom_point.shp')
print(gdf.crs)  # Should be EPSG:4326 (WGS84)

# If not, transform:
gdf = gdf.to_crs('EPSG:4326')
gdf.to_file('geom_point_wgs84.shp')
```

#### 3. TypeError: agg function failed

**Symptom**: `TypeError: agg function failed [how->mean,dtype->object]`

**Solution**: Already fixed in current version. The `DataTypeHandler` class ensures numeric columns are properly typed before aggregation.

#### 4. Hebrew Encoding Issues

**Symptom**: Hebrew text appears as gibberish

**Solutions**:
```python
# Try different encodings
hub_df = pd.read_csv('hubs.csv', encoding='windows-1255')  # Default
# OR
hub_df = pd.read_csv('hubs.csv', encoding='utf-8-sig')     # Alternative
```

---

## Development

### Running Tests

```bash
# Run test suite
python test_calculator.py

# Expected output:
# Test 1 (Basic Functionality): ✓ PASS
# Test 2 (Deduplication): ✓ PASS
# 🎉 ALL TESTS PASSED! 🎉
```

### Project Structure

```
HubUrgency/
├── documentation.md                      # This file - main documentation
├── claude_md_Hubs_Urgency.md            # Technical reference
├── USAGE_GUIDE.md                       # Status calculator usage
├── INVENTAR_LINKER_README.md            # Spatial linker usage
├── STATUS_ZERO_GUIDE.md                 # Status=0 analysis guide
├── FIX_DOCUMENTATION.md                 # Bug fix documentation
├── hub_project_status_calculator.py     # Main calculator module
├── inventar_hub_linker.py               # Spatial linking module
├── test_calculator.py                   # Test suite
├── Hub_Project_Status_Analysis.ipynb    # Interactive notebook
└── inventar_hub_linker_notebook.ipynb   # Spatial analysis notebook
```

### Extending the System

#### Adding New Status Weight Calculations

```python
from huburgency import StatusProgressCalculator

class TimeWeightedCalculator(StatusProgressCalculator):
    """Custom calculator with time-based weighting."""

    def calculate_hub_progress(self, hub_projects_df, group_col='group'):
        # Add custom logic
        hub_projects_df['time_weight'] = self._calculate_time_weight(
            hub_projects_df['scn_year']
        )

        # Call parent implementation
        result = super().calculate_hub_progress(hub_projects_df, group_col)

        # Add custom metrics
        return self._add_custom_metrics(result, hub_projects_df)
```

#### Adding New Geometry Types

```python
from huburgency.inventar_hub_linker import ShapefileLoader

class CustomGeometryLoader(ShapefileLoader):
    """Loader for custom geometry type."""

    def __init__(self, filepath: Path):
        super().__init__(filepath, 'custom_geometry')

    def load(self) -> gpd.GeoDataFrame:
        gdf = super().load()
        # Add custom processing
        return self._process_custom_geometry(gdf)
```

---

## Performance

### Benchmarks

| Operation | Dataset Size | Time | Memory |
|-----------|-------------|------|--------|
| Spatial Intersection | 1,000 H3 cells | ~30 sec | ~200 MB |
| Spatial Intersection | 10,000 H3 cells | ~3 min | ~500 MB |
| Spatial Intersection | 50,000 H3 cells | ~15 min | ~1 GB |
| Status Calculation | 1,000 hubs, 10K projects | ~30-60 sec | ~500 MB |

### Optimization Tips

1. **For Large Spatial Datasets**: Process in chunks
   ```python
   for i in range(0, len(hub_df), 10000):
       chunk = hub_df.iloc[i:i+10000]
       # Process chunk...
   ```

2. **For Many Projects**: Filter by relevance before joining
   ```python
   # Only include projects in relevant years
   project_df = project_df[project_df['scn_year'].between(2025, 2035)]
   ```

3. **Memory Usage**: Use categorical types for repeated strings
   ```python
   hub_df['HubNameHE'] = hub_df['HubNameHE'].astype('category')
   ```

---

## Contact & Support

- **Issues**: Report bugs or request features via project issue tracker
- **Questions**: Check troubleshooting section first, then relevant detailed guides
- **Contributions**: Follow SOLID principles, add tests, update documentation

---

## Version History

- **v1.0** (Current) - Initial release with spatial linking and status calculation
  - Fixed: Empty DataFrames issue (list parsing)
  - Fixed: Duplicate UIDs within groups
  - Added: Status zero analysis
  - Added: Multiple output formats

---

## License

Part of the Hub Prioritization project.
