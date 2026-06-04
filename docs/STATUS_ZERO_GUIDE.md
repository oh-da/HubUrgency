# Status = 0 Projects Analysis - Quick Reference

## Overview

The Status = 0 analysis identifies and reports on projects with status ID = 0, which typically indicates:
- **Not Started** - Projects in planning phase that haven't begun execution
- **Cancelled** - Projects that were cancelled or abandoned
- **On Hold** - Projects temporarily suspended

This analysis helps identify:
- Hubs with high numbers of stalled/cancelled projects
- Groups where project execution is problematic
- Areas requiring management attention or resource reallocation

## Output Report Structure

### What the pipeline writes: `hub_status_zero_report.csv`

`HubProjectStatusPipeline.get_status_zero_projects()` (and
`save_results(status_zero_path=...)`) writes the **project-level** rows whose
`status_weight == 0` — one row per status-zero hub–project pair, with the same
columns as the joined data (`group`, `h3_index`, `uid`, `proj_name`, `main_type`,
`Proj_status`, `scn_year`, `status_weight`).

### Derived per-hub summary

The SQL and Python examples below operate on a **per-hub summary** with the
columns shown here. Build it from the project-level report with one aggregation
(or read `num_proj_status_0` straight from `hub_status_breakdown.csv`):

```python
zero = pipeline.get_status_zero_projects()              # project-level rows
status_zero_df = (
    zero.groupby('group').size()
        .rename('status_zero_count').reset_index()
        .merge(progress_df[['group', 'total_projects']], on='group')
)
status_zero_df['status_zero_pct'] = (
    100 * status_zero_df['status_zero_count'] / status_zero_df['total_projects']
)
```

| Column | Description |
|--------|-------------|
| `group` | Hub group ID |
| `total_projects` | Total number of projects in the hub |
| `status_zero_count` | Number of projects with status = 0 |
| `status_zero_pct` | Percentage of status = 0 projects (%) |

**Note**: The derived summary naturally includes only groups with at least one
status = 0 project (those are the only groups present in the project-level
report).

## Interpretation Guide

### Status Zero Percentage Ranges

| Percentage | Interpretation | Action Required |
|------------|----------------|-----------------|
| 0% | No cancelled/stalled projects | ✓ Good |
| 1-25% | Low cancellation rate | Monitor |
| 26-50% | Moderate cancellation rate | ⚠️ Review and investigate |
| 51-75% | High cancellation rate | 🔴 Immediate attention needed |
| 76-100% | Very high cancellation rate | 🔴 Critical - full review required |

### Key Metrics

**Average Status = 0 per Group**: Indicates typical cancellation rate across affected hubs
- Low (<2): Generally healthy project portfolio
- Medium (2-5): Some execution challenges
- High (>5): Systemic issues requiring attention

**Groups with >50% Status = 0**: Critical indicator
- These groups have more cancelled/stalled projects than active ones
- Require immediate management review and corrective action

## Usage Examples

> In the examples below, `hub_status_zero_report` / `status_zero_df` refers to the
> **per-hub summary** (`group`, `total_projects`, `status_zero_count`,
> `status_zero_pct`) derived from the project-level report as shown under
> [Derived per-hub summary](#derived-per-hub-summary). If you query the raw
> project-level file directly, aggregate by `group` first.

### SQL Analysis

```sql
-- Groups with highest cancellation rates
SELECT 
    group,
    total_projects,
    status_zero_count,
    status_zero_pct
FROM hub_status_zero_report
WHERE status_zero_pct > 50
ORDER BY status_zero_count DESC;

-- Average cancellation rate by region (join with hub data)
SELECT 
    h.region,
    AVG(s.status_zero_pct) as avg_cancellation_rate,
    SUM(s.status_zero_count) as total_cancelled
FROM hub_status_zero_report s
JOIN hubs h ON s.group = h.group
GROUP BY h.region
ORDER BY avg_cancellation_rate DESC;

-- Correlation between hub size and cancellation rate
SELECT 
    CASE 
        WHEN total_projects <= 5 THEN 'Small (1-5)'
        WHEN total_projects <= 10 THEN 'Medium (6-10)'
        ELSE 'Large (11+)'
    END as hub_size,
    AVG(status_zero_pct) as avg_cancellation_rate,
    COUNT(*) as hub_count
FROM hub_status_zero_report
GROUP BY 1
ORDER BY avg_cancellation_rate;
```

### Python Analysis

```python
import pandas as pd

# Load the project-level report and roll it up to the per-hub summary
# (status_zero_df) that the examples below expect.
progress_df = pd.read_csv('hub_status_progress.csv', encoding='windows-1255')
zero_rows = pd.read_csv('hub_status_zero_report.csv', encoding='windows-1255')
status_zero_df = (
    zero_rows.groupby('group').size()
        .rename('status_zero_count').reset_index()
        .merge(progress_df[['group', 'total_projects']], on='group')
)
status_zero_df['status_zero_pct'] = (
    100 * status_zero_df['status_zero_count'] / status_zero_df['total_projects']
)

# Identify critical hubs (>50% cancellation)
critical_hubs = status_zero_df[status_zero_df['status_zero_pct'] > 50]
print(f"Critical hubs requiring immediate attention: {len(critical_hubs)}")

# Calculate overall statistics
total_cancelled = status_zero_df['status_zero_count'].sum()
total_projects = status_zero_df['total_projects'].sum()
overall_rate = 100 * total_cancelled / total_projects
print(f"Overall cancellation rate: {overall_rate:.1f}%")

# Find hubs with most cancelled projects
top_cancelled = status_zero_df.nlargest(10, 'status_zero_count')
print("\nTop 10 hubs by number of cancelled projects:")
print(top_cancelled[['group', 'status_zero_count', 'total_projects']])
```

## Integration with Main Analysis

### Combining Status Zero with Progress Analysis

```python
# Load both reports
# (status_zero_df is the per-hub summary derived as shown in "Python Analysis" above)
progress_df = pd.read_csv('hub_status_progress.csv', encoding='windows-1255')
zero_rows = pd.read_csv('hub_status_zero_report.csv', encoding='windows-1255')
status_zero_df = (
    zero_rows.groupby('group').size()
        .rename('status_zero_count').reset_index()
        .merge(progress_df[['group', 'total_projects']], on='group')
)
status_zero_df['status_zero_pct'] = (
    100 * status_zero_df['status_zero_count'] / status_zero_df['total_projects']
)

# Merge
combined = progress_df.merge(
    status_zero_df[['group', 'status_zero_count', 'status_zero_pct']],
    on='group',
    how='left'
)

# Fill NaN (groups with no status=0) with 0
combined['status_zero_count'] = combined['status_zero_count'].fillna(0)
combined['status_zero_pct'] = combined['status_zero_pct'].fillna(0)

# Calculate adjusted priority score
# Lower progress + higher cancellation = higher priority for intervention
combined['intervention_priority'] = (
    (100 - combined['status_progress_pct']) * 0.6 +  # Progress gap
    combined['status_zero_pct'] * 0.4                # Cancellation rate
)

# Identify hubs needing urgent intervention
urgent_intervention = combined[
    (combined['status_progress_pct'] < 40) & 
    (combined['status_zero_pct'] > 25)
].sort_values('intervention_priority', ascending=False)

print("Hubs requiring urgent intervention:")
print(urgent_intervention[['group', 'total_projects', 'status_progress_pct', 
                          'status_zero_pct', 'intervention_priority']])
```

## Reporting Template

### Executive Summary Format

```
STATUS = 0 PROJECTS ANALYSIS SUMMARY
Generated: [Date]

OVERVIEW:
- Total Groups Analyzed: XXX
- Groups with Status=0 Projects: XXX (XX%)
- Total Status=0 Projects: XXX
- Overall Cancellation Rate: XX%

CRITICAL FINDINGS:
- Groups with >50% cancellation rate: XXX
- Average cancellation rate (affected groups): XX%
- Hub with most cancellations: Group XXX (X projects)

TOP 5 GROUPS REQUIRING ATTENTION:
1. Group XXX: X/XX projects cancelled (XX%)
2. Group XXX: X/XX projects cancelled (XX%)
3. Group XXX: X/XX projects cancelled (XX%)
4. Group XXX: X/XX projects cancelled (XX%)
5. Group XXX: X/XX projects cancelled (XX%)

RECOMMENDATIONS:
□ Immediate review of groups with >50% cancellation rate
□ Root cause analysis for groups with >5 cancelled projects
□ Resource reallocation from stalled to active projects
□ Process improvement to reduce future cancellations
```

## Common Issues & Solutions

### Issue: High Overall Cancellation Rate
**Symptom**: Status_zero_pct averaging >30% across all groups
**Possible Causes**:
- Overambitious initial project scoping
- Insufficient feasibility studies
- Budget/resource constraints
- Political/stakeholder issues

**Actions**:
1. Review project approval and scoping processes
2. Implement stronger feasibility requirements
3. Improve stakeholder engagement early in planning
4. Establish clearer go/no-go criteria

### Issue: Concentration in Specific Hubs
**Symptom**: A few hubs have very high cancellation rates while others have none
**Possible Causes**:
- Geographic/regional challenges
- Local political issues
- Hub-specific constraints (land availability, regulatory)

**Actions**:
1. Conduct site-specific assessments
2. Engage with local stakeholders
3. Consider alternative hub locations
4. Adjust investment strategy by region

### Issue: Specific Project Types Cancelled
**Symptom**: One project type (e.g., Metro) has higher cancellation rate
**Possible Causes**:
- Technology-specific challenges
- Cost overruns for that project type
- Regulatory hurdles

**Actions**:
1. Review project type-specific approval criteria
2. Improve cost estimation for that type
3. Consider alternative modes/technologies
4. Strengthen technical feasibility reviews

## Automation & Monitoring

### Scheduled Reports

```python
# Script for automated monthly status zero report
import pandas as pd
from datetime import datetime

def generate_monthly_status_zero_report():
    # Load latest data and roll the project-level report up to the per-hub summary
    progress_df = pd.read_csv('hub_status_progress.csv', encoding='windows-1255')
    zero_rows = pd.read_csv('hub_status_zero_report.csv', encoding='windows-1255')
    status_zero_df = (
        zero_rows.groupby('group').size()
            .rename('status_zero_count').reset_index()
            .merge(progress_df[['group', 'total_projects']], on='group')
    )
    status_zero_df['status_zero_pct'] = (
        100 * status_zero_df['status_zero_count'] / status_zero_df['total_projects']
    )

    # Generate summary statistics
    summary = {
        'report_date': datetime.now().strftime('%Y-%m-%d'),
        'total_groups': len(status_zero_df),
        'avg_cancellation_rate': status_zero_df['status_zero_pct'].mean(),
        'critical_groups': len(status_zero_df[status_zero_df['status_zero_pct'] > 50]),
        'total_cancelled': status_zero_df['status_zero_count'].sum()
    }
    
    # Save summary
    summary_df = pd.DataFrame([summary])
    summary_df.to_csv(f'status_zero_summary_{summary["report_date"]}.csv', index=False)
    
    return summary

# Run monthly
summary = generate_monthly_status_zero_report()
print(f"Monthly report generated: {summary}")
```

## Contact & Support

For questions about status = 0 analysis:
- Check if your status_weights.csv includes an entry for status_id = 0
- Verify that status = 0 truly represents cancelled/stalled projects in your data
- Review the main USAGE_GUIDE.md for general pipeline support
