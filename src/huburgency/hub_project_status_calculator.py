"""
Hub Project Status Progress Calculator - Fixed Version

Fixes TypeError: agg function failed [how->mean,dtype->object]
by ensuring scn_year is converted to numeric before aggregation.

Following SOLID principles from the Hub Prioritizing project.
"""

import pandas as pd
import numpy as np
from typing import Optional, Tuple, List, Union
from pathlib import Path
import ast


# =============================================================================
# DATA TYPE HANDLER (Single Responsibility)
# =============================================================================

class DataTypeHandler:
    """
    Single Responsibility: Handle data type conversions and validation.
    Ensures numeric columns are properly typed before aggregation.
    """
    
    @staticmethod
    def to_numeric_safe(series: pd.Series, column_name: str = '') -> pd.Series:
        """
        Convert a series to numeric, handling strings like '2030'.
        
        Args:
            series: Input pandas Series
            column_name: Name for logging purposes
            
        Returns:
            Numeric pandas Series with errors coerced to NaN
        """
        if series.dtype in ['int64', 'int32', 'float64', 'float32']:
            return series  # Already numeric
            
        converted = pd.to_numeric(series, errors='coerce')
        
        # Log conversion stats
        original_non_null = series.notna().sum()
        converted_non_null = converted.notna().sum()
        
        if original_non_null != converted_non_null:
            failed_count = original_non_null - converted_non_null
            print(f"  ⚠ Warning: {failed_count} values in '{column_name}' could not be converted to numeric")
        
        return converted
    
    @staticmethod
    def ensure_numeric_columns(df: pd.DataFrame, columns: List[str]) -> pd.DataFrame:
        """
        Ensure specified columns are numeric.
        
        Args:
            df: Input DataFrame
            columns: List of column names to convert
            
        Returns:
            DataFrame with converted columns
        """
        df = df.copy()
        for col in columns:
            if col in df.columns:
                df[col] = DataTypeHandler.to_numeric_safe(df[col], col)
        return df


# =============================================================================
# DATA LOADER (Single Responsibility)
# =============================================================================

class DataLoader:
    """
    Single Responsibility: Handle all data loading operations.
    """
    
    @staticmethod
    def load_csv(filepath: str, encoding: str = 'windows-1255') -> pd.DataFrame:
        """Load CSV file with specified encoding."""
        try:
            df = pd.read_csv(filepath, encoding=encoding)
            print(f"✓ Loaded {filepath}: {len(df):,} rows")
            return df
        except UnicodeDecodeError:
            df = pd.read_csv(filepath, encoding='utf-8-sig')
            print(f"✓ Loaded {filepath} with utf-8-sig: {len(df):,} rows")
            return df
    
    @staticmethod
    def validate_columns(df: pd.DataFrame, required_cols: list, name: str) -> None:
        """Validate that required columns exist in dataframe."""
        missing = set(required_cols) - set(df.columns)
        if missing:
            raise ValueError(f"{name} missing required columns: {missing}")
        print(f"✓ {name} has all required columns")


class ListColumnParser:
    """
    Single Responsibility: Parse string representations of lists into actual lists.
    Handles formats like: "['a', 'b']", "[a, b]", already-parsed lists
    """
    
    @staticmethod
    def parse_list_column(value) -> list:
        """Parse a single value that may be a string representation of a list."""
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return []
        
        if isinstance(value, list):
            return value
        
        if isinstance(value, str):
            value = value.strip()
            if value in ('[]', ''):
                return []
            
            # Try ast.literal_eval first
            try:
                parsed = ast.literal_eval(value)
                if isinstance(parsed, list):
                    return parsed
            except (ValueError, SyntaxError):
                pass
            
            # Fallback: manual parsing
            if value.startswith('[') and value.endswith(']'):
                inner = value[1:-1].strip()
                if not inner:
                    return []
                items = [item.strip().strip("'\"") for item in inner.split(',')]
                return [item for item in items if item]
        
        return [value] if value else []
    
    @staticmethod
    def parse_dataframe_column(df: pd.DataFrame, column: str) -> pd.DataFrame:
        """Parse a column in a DataFrame from string lists to actual lists."""
        df = df.copy()
        if column in df.columns:
            df[column] = df[column].apply(ListColumnParser.parse_list_column)
        return df


def load_hub_csv(filepath: str, list_columns: List[str] = None, encoding: str = 'windows-1255') -> pd.DataFrame:
    """
    Convenience function: Load hub CSV and automatically parse list columns.
    
    Args:
        filepath: Path to CSV file
        list_columns: Columns to parse as lists (default: intersection columns)
        encoding: File encoding
    
    Returns:
        DataFrame with parsed list columns
    """
    if list_columns is None:
        list_columns = ['intersecting_points', 'intersecting_lines', 'intersecting_multilines']
    
    df = DataLoader.load_csv(filepath, encoding)
    
    for col in list_columns:
        if col in df.columns:
            df = ListColumnParser.parse_dataframe_column(df, col)
            print(f"  ✓ Parsed list column: {col}")
    
    return df


# =============================================================================
# PROJECT DATA JOINER (Single Responsibility)
# =============================================================================

class ProjectDataJoiner:
    """
    Single Responsibility: Handle joining of project data to hub dataframe.
    """
    
    REQUIRED_PROJECT_COLS = ['uid', 'proj_name', 'main_type', 'Proj_status', 'scn_year']
    
    def __init__(self, hub_df: pd.DataFrame, project_df: pd.DataFrame):
        """Initialize joiner with hub and project dataframes."""
        self.hub_df = hub_df.copy()
        self.project_df = project_df.copy()
        DataLoader.validate_columns(project_df, self.REQUIRED_PROJECT_COLS, "Project data")
    
    def _combine_uids(self, uid_columns: list) -> pd.DataFrame:
        """Combine multiple UID columns into a single list per row."""
        print(f"\nCombining UIDs from: {uid_columns}")
        
        df = self.hub_df.copy()
        
        # Combine all UIDs, removing duplicates per group
        def merge_uid_lists(row):
            all_uids = []
            for col in uid_columns:
                if col in row and row[col]:
                    uids = row[col] if isinstance(row[col], list) else [row[col]]
                    all_uids.extend([uid for uid in uids if uid and uid not in all_uids])
            return all_uids
        
        df['combined_uids'] = df.apply(merge_uid_lists, axis=1)
        
        total_uids = sum(len(uids) for uids in df['combined_uids'])
        print(f"  Combined {total_uids:,} total UIDs (duplicates removed per group)")
        
        return df
    
    def _explode_uids(self, df: pd.DataFrame) -> pd.DataFrame:
        """Explode combined_uids to create one row per hub-project relationship."""
        print(f"\nExploding UIDs...")
        
        exploded = df.explode('combined_uids')
        exploded = exploded.rename(columns={'combined_uids': 'uid'})
        
        # Remove rows with empty/null UIDs
        before_count = len(exploded)
        exploded = exploded.dropna(subset=['uid'])
        exploded = exploded[exploded['uid'] != '']
        after_count = len(exploded)
        
        print(f"✓ Exploded to {after_count:,} hub-project pairs")
        print(f"  (Removed {before_count - after_count:,} empty/null rows)")
        
        return exploded
    
    def join_to_hubs(self, uid_columns: list = None) -> pd.DataFrame:
        """
        Join project data to hub dataframe based on UIDs.
        
        Args:
            uid_columns: List of columns containing UIDs to combine
            
        Returns:
            DataFrame with hub-project relationships and project details
        """
        if uid_columns is None:
            uid_columns = ['intersecting_points', 'intersecting_lines', 'intersecting_multilines']
        
        # Combine and explode UIDs
        df = self._combine_uids(uid_columns)
        df = self._explode_uids(df)
        
        # Ensure uid columns are same type for join
        df['uid'] = df['uid'].astype(str)
        project_df = self.project_df.copy()
        project_df['uid'] = project_df['uid'].astype(str)
        
        # Join project data
        print(f"\nJoining project data...")
        result = df.merge(
            project_df[self.REQUIRED_PROJECT_COLS],
            on='uid',
            how='left'
        )
        
        matched = result['proj_name'].notna().sum()
        total = len(result)
        print(f"✓ Joined {matched:,}/{total:,} records matched to projects ({100*matched/total:.1f}%)")
        
        return result


# =============================================================================
# STATUS PROGRESS CALCULATOR (Single Responsibility) - FIXED
# =============================================================================

class StatusProgressCalculator:
    """
    Single Responsibility: Calculate weighted status progress for hubs.
    
    Uses Proj_status (not Proj_status_id) for aggregation.
    """
    
    REQUIRED_WEIGHT_COLS = ['Proj_status', 'weight']
    
    def __init__(self, status_weights_df: pd.DataFrame):
        """Initialize calculator with status weights reference."""
        DataLoader.validate_columns(status_weights_df, self.REQUIRED_WEIGHT_COLS, "Status weights")
        
        # Build lookup dictionary: Proj_status -> weight
        self.weight_lookup = dict(zip(
            status_weights_df['Proj_status'].astype(str),
            status_weights_df['weight']
        ))
        
        # Store all known statuses for pivot table
        self.all_statuses = sorted(status_weights_df['Proj_status'].unique())
        
        print(f"✓ Loaded {len(self.weight_lookup)} status weight mappings")
    
    def _map_status_to_weight(self, df: pd.DataFrame) -> pd.DataFrame:
        """Map Proj_status to numeric weight."""
        df = df.copy()
        df['status_weight'] = df['Proj_status'].astype(str).map(self.weight_lookup)
        
        unmapped = df['status_weight'].isna().sum()
        if unmapped > 0:
            print(f"  ⚠ Warning: {unmapped} records have unmapped status values")
            df['status_weight'] = df['status_weight'].fillna(0)
        
        return df
    
    def _prepare_for_aggregation(self, df: pd.DataFrame) -> pd.DataFrame:
        """Ensure all columns that will be aggregated are properly typed."""
        df = df.copy()
        
        # Ensure status_weight is numeric
        if 'status_weight' in df.columns:
            df['status_weight'] = DataTypeHandler.to_numeric_safe(df['status_weight'], 'status_weight')
        
        # Ensure Proj_status is string for consistent grouping
        if 'Proj_status' in df.columns:
            df['Proj_status'] = df['Proj_status'].astype(str)
        
        return df
    
    def calculate_hub_progress(
        self,
        hub_projects_df: pd.DataFrame,
        group_col: str = 'group'
    ) -> pd.DataFrame:
        """
        Calculate weighted status progress for each hub.
        
        Args:
            hub_projects_df: DataFrame with hub-project relationships
            group_col: Column name for hub grouping
            
        Returns:
            DataFrame with hub-level progress metrics
        """
        print(f"\nCalculating status progress by group...")
        
        # Map status to weights
        df = self._map_status_to_weight(hub_projects_df)
        
        # Prepare columns for aggregation
        df = self._prepare_for_aggregation(df)
        
        # Calculate max possible weight
        max_weight = max(self.weight_lookup.values())
        
        # Aggregate by hub
        hub_stats = df.groupby(group_col).agg(
            total_projects=('uid', 'count'),
            current_weighted_sum=('status_weight', 'sum'),
            max_possible_sum=('uid', lambda x: len(x) * max_weight),
            unique_statuses=('Proj_status', 'nunique')
        ).reset_index()
        
        # Calculate progress percentage
        hub_stats['status_progress_pct'] = (
            100 * hub_stats['current_weighted_sum'] / 
            hub_stats['max_possible_sum']
        ).round(2)
        
        print(f"✓ Calculated progress for {len(hub_stats):,} hubs")
        print(f"  Progress range: {hub_stats['status_progress_pct'].min():.1f}% - "
              f"{hub_stats['status_progress_pct'].max():.1f}%")
        
        return hub_stats
    
    def calculate_status_breakdown(
        self,
        hub_projects_df: pd.DataFrame,
        group_col: str = 'group'
    ) -> pd.DataFrame:
        """
        Calculate number of projects per status for each hub.
        
        Creates columns like: num_proj_status_0, num_proj_status_1, etc.
        
        Args:
            hub_projects_df: DataFrame with hub-project relationships
            group_col: Column name for hub grouping
            
        Returns:
            DataFrame with one column per status containing project counts
        """
        print(f"\nCalculating status breakdown by group...")
        
        df = hub_projects_df.copy()
        df['Proj_status'] = df['Proj_status'].astype(str)
        
        # Create pivot table: groups x statuses
        pivot = df.groupby([group_col, 'Proj_status']).size().unstack(fill_value=0)
        
        # Rename columns to num_proj_status_X format
        pivot.columns = [f'num_proj_status_{col}' for col in pivot.columns]
        
        # Reset index to make group a column
        pivot = pivot.reset_index()
        
        # Add total column
        status_cols = [col for col in pivot.columns if col.startswith('num_proj_status_')]
        pivot['total_projects'] = pivot[status_cols].sum(axis=1)
        
        print(f"✓ Created status breakdown for {len(pivot):,} hubs")
        print(f"  Status columns: {len(status_cols)}")
        
        return pivot


# =============================================================================
# PIPELINE FACADE (Dependency Inversion)
# =============================================================================

class HubProjectStatusPipeline:
    """
    Facade: Provides simple interface to entire workflow.
    Dependency Inversion: Depends on abstractions (injected components).
    """
    
    def __init__(
        self,
        hub_df: pd.DataFrame,
        project_df: pd.DataFrame,
        status_weights_df: pd.DataFrame
    ):
        self.joiner = ProjectDataJoiner(hub_df, project_df)
        self.calculator = StatusProgressCalculator(status_weights_df)
        self.joined_df: Optional[pd.DataFrame] = None
        self.progress_df: Optional[pd.DataFrame] = None
        self.status_breakdown_df: Optional[pd.DataFrame] = None
    
    def run(
        self, 
        uid_columns: list = None,
        group_col: str = 'group'
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """
        Execute complete pipeline.
        
        Returns:
            Tuple of (joined_df, progress_df, status_breakdown_df)
        """
        print("=" * 70)
        print("STARTING HUB PROJECT STATUS ANALYSIS PIPELINE")
        print("=" * 70)
        
        # Step 1: Join project data
        self.joined_df = self.joiner.join_to_hubs(uid_columns)
        
        # Step 2: Calculate progress
        self.progress_df = self.calculator.calculate_hub_progress(
            self.joined_df,
            group_col
        )
        
        # Step 3: Calculate status breakdown (num_proj_status_X columns)
        self.status_breakdown_df = self.calculator.calculate_status_breakdown(
            self.joined_df,
            group_col
        )
        
        print("\n" + "=" * 70)
        print("PIPELINE COMPLETED SUCCESSFULLY")
        print("=" * 70)
        
        return self.joined_df, self.progress_df, self.status_breakdown_df
    
    def get_status_zero_projects(self) -> Optional[pd.DataFrame]:
        """
        Get projects with status weight = 0 (not started or unknown status).
        
        Returns:
            DataFrame with status-zero projects, or None if pipeline hasn't run
        """
        if self.joined_df is None:
            return None
        
        # Ensure status_weight column exists
        if 'status_weight' not in self.joined_df.columns:
            print("  ⚠ status_weight column not found - mapping status first...")
            df = self.calculator._map_status_to_weight(self.joined_df)
        else:
            df = self.joined_df
        
        status_zero = df[df['status_weight'] == 0].copy()
        
        if len(status_zero) > 0:
            print(f"✓ Found {len(status_zero):,} projects with status weight = 0")
        else:
            print("  No projects with status weight = 0 found")
        
        return status_zero
    
    def save_results(
        self, 
        joined_path: str,
        progress_path: str,
        status_breakdown_path: str = None,
        status_zero_path: str = None,
        encoding: str = 'windows-1255'
    ) -> None:
        """
        Save output dataframes to CSV.
        
        Args:
            joined_path: Path for joined hub-project data
            progress_path: Path for hub progress statistics
            status_breakdown_path: Path for status breakdown (num_proj_status_X columns)
            status_zero_path: Optional path for status-zero projects analysis
            encoding: File encoding (default: windows-1255 for Hebrew)
        """
        if self.joined_df is None or self.progress_df is None:
            raise RuntimeError("Pipeline must be run before saving results")
        
        Path(joined_path).parent.mkdir(parents=True, exist_ok=True)
        
        self.joined_df.to_csv(joined_path, index=False, encoding=encoding)
        print(f"✓ Saved joined data: {joined_path}")
        
        self.progress_df.to_csv(progress_path, index=False, encoding=encoding)
        print(f"✓ Saved progress data: {progress_path}")
        
        # Save status breakdown if path provided
        if status_breakdown_path and self.status_breakdown_df is not None:
            self.status_breakdown_df.to_csv(status_breakdown_path, index=False, encoding=encoding)
            print(f"✓ Saved status breakdown: {status_breakdown_path}")
        
        # Save status-zero analysis if path provided
        if status_zero_path:
            status_zero_df = self.get_status_zero_projects()
            if status_zero_df is not None and len(status_zero_df) > 0:
                status_zero_df.to_csv(status_zero_path, index=False, encoding=encoding)
                print(f"✓ Saved status-zero projects: {status_zero_path}")
            else:
                print(f"  Skipped status-zero file (no records)")


# =============================================================================
# CONVENIENCE FUNCTION FOR QUICK FIX
# =============================================================================

def fix_scn_year_dtype(df: pd.DataFrame) -> pd.DataFrame:
    """
    Quick fix: Convert scn_year column to numeric.
    
    Use this on your existing joined DataFrame if you don't want to 
    replace the entire module.
    
    Usage:
        joined_df = fix_scn_year_dtype(joined_df)
        # Now aggregation will work
    """
    if 'scn_year' in df.columns:
        df = df.copy()
        df['scn_year'] = pd.to_numeric(df['scn_year'], errors='coerce')
        print(f"✓ Converted 'scn_year' to numeric dtype")
    return df


# =============================================================================
# USAGE EXAMPLE
# =============================================================================

if __name__ == "__main__":
    print("Hub Project Status Calculator")
    print("=" * 50)
    print("\nUsage:")
    print("  from huburgency import HubProjectStatusPipeline, load_hub_csv")
    print("  ")
    print("  # Load data with automatic list parsing")
    print("  hub_df = load_hub_csv('hubs_with_uids.csv')")
    print("  project_df = pd.read_csv('data.csv')")
    print("  weights_df = pd.read_csv('status_weights.csv')")
    print("  ")
    print("  # Run pipeline")
    print("  pipeline = HubProjectStatusPipeline(hub_df, project_df, weights_df)")
    print("  joined_df, progress_df, status_breakdown_df = pipeline.run()")
    print()
    print("Or use the quick fix on existing data:")
    print("  from huburgency import fix_scn_year_dtype")
    print("  joined_df = fix_scn_year_dtype(joined_df)")
