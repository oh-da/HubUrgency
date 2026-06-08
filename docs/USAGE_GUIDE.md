# Hub Project Status Calculator - Usage Guide

## Overview
This module calculates weighted project status progress for transit hubs based on the SOLID principles outlined in your Hubs Prioritizing project.

## SOLID Principles Applied

### Single Responsibility Principle (SRP)
- **DataLoader**: Only handles file loading and validation
- **ProjectDataJoiner**: Only handles joining project data to hubs
- **StatusProgressCalculator**: Only calculates status progress metrics
- **HubProjectStatusPipeline**: Only orchestrates the workflow

### Open/Closed Principle (OCP)
- Easy to extend with new calculation methods by inheriting from `StatusProgressCalculator`
- Can add new data sources without modifying existing classes

### Liskov Substitution Principle (LSP)
- All classes can be replaced with enhanced versions without breaking the pipeline

### Interface Segregation Principle (ISP)
- Each class has focused, minimal interfaces
- No class is forced to depend on methods it doesn't use

### Dependency Inversion Principle (DIP)
- `HubProjectStatusPipeline` depends on injected components, not concrete implementations
- Easy to swap implementations for testing or different data sources

## File Format Requirements

### 1. Hub Data (Input)
**Example**: `Hubs_w_InventarProjects_uid.csv`

Required columns:
```
group,x,y,HubNameHE,h3_index,intersecting_points,intersecting_lines,intersecting_multilines
692,34.8123,32.0456,"תל אביב מרכז","[8a2a1072b59ffff]","['uid_001','uid_002']","['uid_100']","[]"
```

- `group`: Hub group ID (integer)
- `intersecting_points/lines/multilines`: Lists of UIDs (can be empty lists `[]`)

### 2. Project Data (Input)
**File**: `data.csv`

Required columns:
```
uid,proj_name,main_type,Proj_status,scn_year
uid_001,Light Rail Extension,LRT,3,2028
uid_002,Bus Terminal Upgrade,BRT,5,2026
uid_100,Metro Line 1,Metro,2,2030
```

- `uid`: Unique project identifier (primary key) - must match UIDs in hub data
- `proj_name`: Project name
- `main_type`: Main project type (Rail, LRT, BRT, Metro, Bus)
- `Proj_status`: Status ID (integer, maps to weights file)
- `scn_year`: Scenario/planned year

### 3. Status Weights (Input)
**File**: `status_weights.csv`

Required columns:
```
Proj_status,weight
1,0.10
2,0.25
3,0.40
4,0.60
5,0.75
6,0.85
7,0.95
8,1.00
```

- `Proj_status`: Status identifier (must match the `Proj_status` column in the project data). **Note:** the column must be named `Proj_status` — the calculator validates `REQUIRED_WEIGHT_COLS = ['Proj_status', 'weight']` and will reject a `Proj_status_id` column.
- `weight`: Normalized weight (0.0 to 1.0)

**Status Types Example**:
1. Planning initiated (10%)
2. Preliminary design (25%)
3. Detailed design (40%)
4. Tender/procurement (60%)
5. Under construction (75%)
6. Testing/commissioning (85%)
7. Soft opening (95%)
8. Fully operational (100%)

## Output Files

### 1. Joined Data
**File**: `hubs_with_project_data.csv`

All hub columns + project columns for each hub-project pair:
```
group,h3_index,all_project_uids,uid,proj_name,main_type,Proj_status,scn_year,status_weight
692,8a2a1072b59ffff,uid_001,uid_001,Light Rail Extension,LRT,3,2028,0.40
692,8a2a1072b59ffff,uid_002,uid_002,Bus Terminal Upgrade,BRT,5,2026,0.75
```

### 2. Progress Summary
**File**: `hub_status_progress.csv`

Hub-level aggregated metrics:
```
group,total_projects,current_weighted_sum,max_possible_sum,unique_statuses,status_progress_pct
692,15,8.50,15.00,5,56.67
450,8,6.20,8.00,4,77.50
```

Columns:
- `total_projects`: Number of projects in hub
- `current_weighted_sum`: Sum of actual project weights
- `max_possible_sum`: Maximum possible sum (all projects at weight=1.0)
- `unique_statuses`: Number of different status types in hub
- `status_progress_pct`: Progress percentage (0-100%)

## Usage Examples

### Basic Usage
```python
from huburgency import (
    DataLoader, 
    HubProjectStatusPipeline
)

# Load data
loader = DataLoader()
hub_df = loader.load_csv('Hubs_w_InventarProjects_uid.csv')
project_df = loader.load_csv('data.csv')
weights_df = loader.load_csv('status_weights.csv')

# Run pipeline
pipeline = HubProjectStatusPipeline(hub_df, project_df, weights_df)
joined_df, progress_df, status_breakdown_df = pipeline.run()

# Save results
pipeline.save_results(
    'hubs_with_project_data.csv',
    'hub_status_progress.csv'
)
```

### Custom UID Columns
```python
# If your hub data has different column names for UIDs
joined_df, progress_df, status_breakdown_df = pipeline.run(
    uid_columns=['points_uid', 'lines_uid', 'stations_uid']
)
```

### Advanced: Custom Calculation
```python
from huburgency import StatusProgressCalculator

class WeightedByYearCalculator(StatusProgressCalculator):
    """Custom calculator that weights by scenario year proximity."""
    
    def calculate_hub_progress(self, hub_projects_df, group_col='group'):
        # Add year-based weighting
        current_year = 2026
        hub_projects_df['year_weight'] = 1 / (
            1 + abs(hub_projects_df['scn_year'] - current_year)
        )
        
        # Call parent method
        result = super().calculate_hub_progress(hub_projects_df, group_col)
        
        # Add year-weighted metrics
        year_stats = hub_projects_df.groupby(group_col).agg(
            avg_year=('scn_year', 'mean'),
            year_weighted_sum=('year_weight', 'sum')
        )
        
        return result.merge(year_stats, on=group_col)

# Use custom calculator
pipeline = HubProjectStatusPipeline(hub_df, project_df, weights_df)
pipeline.calculator = WeightedByYearCalculator(weights_df)
joined_df, progress_df, status_breakdown_df = pipeline.run()
```

## Advanced Features

The pipeline supports three optional capabilities, each available in either input mode.

### Pre-exploded Input Mode

If your data is already exploded to one row per `(group, project_uid)` with a
`Proj_status` column, skip the internal join entirely:

```python
from huburgency import HubProjectStatusPipeline, DataLoader

loader = DataLoader()
hub_project_df = loader.load_csv('Hubs_w_InventarProjects_filtered.csv')
weights_df = loader.load_csv('status_weights.csv')

pipeline = HubProjectStatusPipeline(
    status_weights_df=weights_df,
    hub_project_df=hub_project_df,
    use_pre_exploded=True,
)
joined_df, progress_df, status_breakdown_df = pipeline.run()
```

Rows with a missing `project_uid` are preserved — they represent hub groups with
zero intersecting projects and surface in the output at 0% progress.

### Status Overrides

Supply a table with columns `uid` and `Proj_status` to replace the status of
selected projects before scoring (useful for manual corrections without editing
the source data):

```python
override_df = loader.load_csv_if_exists('status_override.csv')  # None if absent

pipeline = HubProjectStatusPipeline(
    status_weights_df=weights_df,
    hub_project_df=hub_project_df,
    status_override_df=override_df,   # ignored if None / empty
    use_pre_exploded=True,
)
```

### Guaranteeing Every Hub Appears (All-Hubs Backfill)

Pass the full hub table as `all_hubs_df`; every group in it is guaranteed to
appear in `progress_df`, with hubs that have no projects backfilled at 0%:

```python
all_hubs_df = loader.load_csv('Hubs_w_InventarProjects_combined.csv')

pipeline = HubProjectStatusPipeline(
    hub_df=hub_df,
    project_df=project_df,
    status_weights_df=weights_df,
    all_hubs_df=all_hubs_df,
)
```

These options compose freely and also work in raw mode
(`hub_df` + `project_df`).

## Integration with Existing Pipeline

This module integrates with your existing Hub Prioritizing pipeline:

```
Part 1: H3 Processing (process_transit_nodes_to_h3.py)
    ↓
Part 2: Demand Processing (hub_demand_processor.py)
    ↓
Part 3: Influence Area (influence_area_processor.py)
    ↓
NEW: Project Status (hub_project_status_calculator.py) ← You are here
    ↓
Final Hub Prioritization Analysis
```

### Combined Pipeline Example
```python
# After running Parts 1-3 of your existing pipeline
from hub_demand_processor import DemandDataProcessor
from influence_area_processor import InfluenceAreaProcessor
from huburgency import HubProjectStatusPipeline, DataLoader

# Complete Part 3
influence_processor = InfluenceAreaProcessor()
hubs_with_influence = influence_processor.process_full_pipeline(
    hubs_csv='...',
    taz_shp='...'
)

# Add project status (NEW)
loader = DataLoader()
project_df = loader.load_csv('data.csv')
weights_df = loader.load_csv('status_weights.csv')

status_pipeline = HubProjectStatusPipeline(
    hub_df=hubs_with_influence,
    project_df=project_df,
    status_weights_df=weights_df
)

joined_df, progress_df, status_breakdown_df = status_pipeline.run()

# Merge progress back to main hub dataset
final_hubs = hubs_with_influence.merge(
    progress_df[['group', 'status_progress_pct', 'total_projects']],
    on='group',
    how='left'
)

# Now you have complete hub dataset with:
# - H3 spatial grouping
# - Demand data
# - Influence area demographics
# - Project status progress
```

## SQL Analysis Examples

Once you have the output files, you can analyze them in SQL:

```sql
-- Top 20 hubs by status progress
SELECT 
    group,
    total_projects,
    status_progress_pct,
    unique_statuses
FROM hub_status_progress
ORDER BY status_progress_pct DESC
LIMIT 20;

-- Hubs with low progress but high project count (potential bottlenecks)
SELECT 
    group,
    total_projects,
    status_progress_pct
FROM hub_status_progress
WHERE total_projects >= 5
    AND status_progress_pct < 40
ORDER BY total_projects DESC;

-- Project distribution by status across hubs
SELECT 
    Proj_status,
    COUNT(DISTINCT group) as hub_count,
    COUNT(*) as project_count,
    AVG(status_weight) as avg_weight
FROM hubs_with_project_data
GROUP BY Proj_status
ORDER BY Proj_status;

-- Hubs by main project type
SELECT 
    h.group,
    p.main_type,
    COUNT(*) as type_count,
    AVG(p.status_weight) as avg_status_weight
FROM hubs_with_project_data h
JOIN (SELECT DISTINCT uid, main_type FROM hubs_with_project_data) p
    ON h.uid = p.uid
GROUP BY h.group, p.main_type
ORDER BY h.group, type_count DESC;
```

## Troubleshooting

### Issue: No projects matched
**Cause**: UID format mismatch between hub data and project data

**Fix**: Ensure UIDs are consistent strings:
```python
# Clean UIDs in project data
project_df['uid'] = project_df['uid'].astype(str).str.strip()
```

### Issue: Missing status weights
**Symptom**: Warning about unmapped statuses

**Fix**: Add missing status IDs to `status_weights.csv` or update project data to use valid status IDs

### Issue: All progress values are 0% or 100%
**Cause**: Weight values might be binary (0 or 1) instead of normalized

**Fix**: Ensure weights are decimal values between 0.0 and 1.0

## Performance Notes

- Typical runtime: 30-60 seconds for 1,000 hubs with 10,000 projects
- Memory usage: ~500MB for large datasets
- For very large datasets (>100k projects), consider processing in batches by group
