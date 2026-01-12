# -*- coding: utf-8 -*-
"""
Inventar Projects to Hubs Linker
================================

Links infrastructure inventory projects to transit hubs via H3 hexagonal spatial intersection.

This module is part of the Hub Prioritization pipeline. It takes the output from the 
Hub Processing Pipeline (with H3 indices and group assignments) and enriches it by 
identifying which planned infrastructure projects (points, lines, multilines) 
intersect with each hub's H3 hexagonal cells.

Input:
    - Hub results CSV from the Transit Hub Processing Pipeline
      (columns: group, x, y, HubNameHE, h3_index)
    - Inventar shapefiles: geom_point.shp, geom_line.shp, geom_multiline.shp

Output:
    - Enriched hub DataFrame with intersecting project UIDs per geometry type

Architecture follows SOLID principles:
    - Single Responsibility: Each class has one job
    - Open/Closed: Extensible via new geometry loaders without modifying core logic
    - Liskov Substitution: All geometry loaders implement common interface
    - Interface Segregation: Minimal interfaces for each component
    - Dependency Inversion: Core logic depends on abstractions, not concrete implementations

Author: Transport Modeling Team
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Dict, Any, Protocol
import logging

import pandas as pd
import geopandas as gpd
import numpy as np
from shapely.geometry import Polygon
import h3

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

@dataclass
class ProcessingConfig:
    """Configuration for the Inventar-to-Hubs linking process."""
    
    # Input paths
    hubs_csv_path: Path
    inventar_directory: Path
    
    # Output path
    output_csv_path: Path
    
    # File encoding
    encoding: str = 'windows-1255'
    
    # Geometry shapefile names
    point_shapefile: str = 'geom_point.shp'
    line_shapefile: str = 'geom_line.shp'
    multiline_shapefile: str = 'geom_multiline.shp'
    
    # Column names
    uid_column: str = 'uid'
    h3_column: str = 'h3_index'
    group_column: str = 'group'
    
    def __post_init__(self):
        """Convert string paths to Path objects."""
        self.hubs_csv_path = Path(self.hubs_csv_path)
        self.inventar_directory = Path(self.inventar_directory)
        self.output_csv_path = Path(self.output_csv_path)
    
    def validate(self) -> None:
        """Validate configuration paths exist."""
        if not self.hubs_csv_path.exists():
            raise FileNotFoundError(f"Hubs CSV not found: {self.hubs_csv_path}")
        if not self.inventar_directory.exists():
            raise FileNotFoundError(f"Inventar directory not found: {self.inventar_directory}")


# =============================================================================
# Data Loading (Single Responsibility)
# =============================================================================

class H3ListParser:
    """Parses H3 index lists stored as strings in CSV files."""
    
    @staticmethod
    def parse(value: str) -> List[str]:
        """
        Parse a string representation of H3 index list.
        
        Handles formats like: "['8a3e0a1234', '8a3e0a1235']" or "[8a3e0a1234, 8a3e0a1235]"
        
        Args:
            value: String containing list of H3 indices
            
        Returns:
            List of H3 index strings
        """
        if pd.isna(value) or not isinstance(value, str):
            return []
        
        # Remove brackets and split by comma
        cleaned = value.replace('[', '').replace(']', '')
        items = cleaned.split(',')
        
        # Strip whitespace and quotes from each item
        return [item.strip().strip("'\"") for item in items if item.strip()]


class HubDataLoader:
    """Loads and prepares hub data from the Transit Hub Processing Pipeline output."""
    
    def __init__(self, config: ProcessingConfig):
        self.config = config
        self._parser = H3ListParser()
    
    def load(self) -> pd.DataFrame:
        """
        Load hub data from CSV and prepare for spatial processing.
        
        Returns:
            DataFrame with one row per H3 cell (exploded from hub groups)
        """
        logger.info(f"Loading hub data from {self.config.hubs_csv_path}")
        
        # Load raw data
        df = pd.read_csv(self.config.hubs_csv_path, encoding=self.config.encoding)
        logger.info(f"Loaded {len(df)} hub groups")
        
        # Parse H3 index lists
        df[self.config.h3_column] = df[self.config.h3_column].apply(self._parser.parse)
        
        # Select relevant columns
        columns_to_keep = [
            self.config.group_column, 'x', 'y', 'HubNameHE', self.config.h3_column
        ]
        available_columns = [c for c in columns_to_keep if c in df.columns]
        df = df[available_columns]
        
        # Explode H3 indices (one row per cell)
        df = df.explode(self.config.h3_column).reset_index(drop=True)
        logger.info(f"Exploded to {len(df)} H3 cells")
        
        return df


class GeometryLoader(Protocol):
    """Protocol for geometry data loaders (Interface Segregation)."""
    
    def load(self) -> gpd.GeoDataFrame:
        """Load geometry data and return GeoDataFrame."""
        ...
    
    @property
    def name(self) -> str:
        """Human-readable name for this geometry type."""
        ...


class ShapefileLoader:
    """Loads shapefile geometries from the Inventar directory."""
    
    def __init__(self, filepath: Path, geometry_name: str):
        self._filepath = filepath
        self._name = geometry_name
    
    @property
    def name(self) -> str:
        return self._name
    
    def load(self) -> gpd.GeoDataFrame:
        """Load shapefile into GeoDataFrame."""
        logger.info(f"Loading {self._name} from {self._filepath}")
        
        if not self._filepath.exists():
            logger.warning(f"Shapefile not found: {self._filepath}")
            return gpd.GeoDataFrame()
        
        gdf = gpd.read_file(self._filepath)
        logger.info(f"Loaded {len(gdf)} {self._name} features")
        return gdf


class InventarLoaderFactory:
    """Factory for creating geometry loaders (Open/Closed - add new types without modification)."""
    
    def __init__(self, config: ProcessingConfig):
        self.config = config
    
    def create_all_loaders(self) -> Dict[str, GeometryLoader]:
        """Create loaders for all geometry types."""
        return {
            'points': ShapefileLoader(
                self.config.inventar_directory / self.config.point_shapefile,
                'points'
            ),
            'lines': ShapefileLoader(
                self.config.inventar_directory / self.config.line_shapefile,
                'lines'
            ),
            'multilines': ShapefileLoader(
                self.config.inventar_directory / self.config.multiline_shapefile,
                'multilines'
            )
        }


# =============================================================================
# H3 to Polygon Conversion (Single Responsibility)
# =============================================================================

class H3PolygonConverter:
    """Converts H3 hexagonal indices to Shapely Polygons."""
    
    @staticmethod
    def convert(h3_index: str) -> Optional[Polygon]:
        """
        Convert H3 index string to Shapely Polygon.
        
        Note: H3 cell_to_boundary returns (lat, lon) tuples.
              Shapely expects (lon, lat) - i.e., (x, y) coordinates.
        
        Args:
            h3_index: Valid H3 index string
            
        Returns:
            Shapely Polygon in WGS84 (EPSG:4326), or None if conversion fails
        """
        if not isinstance(h3_index, str) or not h3_index:
            return None
        
        try:
            # h3.cell_to_boundary returns list of (lat, lon) tuples
            geo_boundary = h3.cell_to_boundary(h3_index)
            
            # Convert to (lon, lat) for Shapely
            lon_lat_coords = [(lon, lat) for lat, lon in geo_boundary]
            return Polygon(lon_lat_coords)
        
        except Exception as e:
            logger.debug(f"Failed to convert H3 index '{h3_index}': {e}")
            return None
    
    @classmethod
    def convert_series(cls, h3_series: pd.Series) -> pd.Series:
        """Convert a Series of H3 indices to Polygons."""
        return h3_series.apply(cls.convert)


# =============================================================================
# Spatial Intersection Engine (Single Responsibility)
# =============================================================================

class SpatialIntersector:
    """Performs efficient spatial intersection using spatial indexing."""
    
    def __init__(self, target_gdf: gpd.GeoDataFrame, uid_column: str = 'uid'):
        """
        Initialize with target geometries to intersect against.
        
        Args:
            target_gdf: GeoDataFrame with geometries to find intersections with
            uid_column: Column name containing unique identifiers
        """
        self._gdf = target_gdf
        self._uid_column = uid_column
        self._has_data = len(target_gdf) > 0
    
    def find_intersecting_uids(self, query_polygon: Optional[Polygon]) -> List[Any]:
        """
        Find UIDs of all geometries intersecting with query polygon.
        
        Uses R-tree spatial index for efficient bounding box filtering,
        then precise intersection check.
        
        Args:
            query_polygon: Shapely Polygon to test intersection against
            
        Returns:
            List of UIDs from intersecting geometries
        """
        if query_polygon is None or not self._has_data:
            return []
        
        # Stage 1: Bounding box filter using spatial index
        candidate_indices = list(self._gdf.sindex.intersection(query_polygon.bounds))
        
        if not candidate_indices:
            return []
        
        # Stage 2: Precise intersection test
        candidates = self._gdf.iloc[candidate_indices]
        intersecting = candidates[candidates.intersects(query_polygon)]
        
        return intersecting[self._uid_column].tolist()


# =============================================================================
# Main Processor (Dependency Inversion - depends on abstractions)
# =============================================================================

@dataclass
class IntersectionResult:
    """Result container for intersection analysis."""
    
    h3_index: str
    group: int
    intersecting_points: List[Any] = field(default_factory=list)
    intersecting_lines: List[Any] = field(default_factory=list)
    intersecting_multilines: List[Any] = field(default_factory=list)


# =============================================================================
# Post-Processing Utilities
# =============================================================================

class ResultTransformer:
    """Transforms intersection results into different output formats."""
    
    @staticmethod
    def combine_project_uids(df: pd.DataFrame) -> pd.DataFrame:
        """
        Combine all intersecting UIDs into a single column.
        
        Creates 'all_project_uids' column containing unique UIDs from
        points, lines, and multilines combined.
        
        Args:
            df: DataFrame with intersecting_points, intersecting_lines, 
                intersecting_multilines columns
                
        Returns:
            DataFrame with new 'all_project_uids' column
        """
        df = df.copy()
        
        def _combine_uids(row) -> List[Any]:
            """Combine UIDs from all geometry types, preserving uniqueness."""
            all_uids = []
            
            for col in ['intersecting_points', 'intersecting_lines', 'intersecting_multilines']:
                if col in row and isinstance(row[col], list):
                    all_uids.extend(row[col])
            
            # Return unique UIDs while preserving order
            seen = set()
            unique_uids = []
            for uid in all_uids:
                if uid not in seen:
                    seen.add(uid)
                    unique_uids.append(uid)
            
            return unique_uids
        
        df['all_project_uids'] = df.apply(_combine_uids, axis=1)
        logger.info(f"Combined project UIDs into 'all_project_uids' column")
        
        return df
    
    @staticmethod
    def explode_by_project(df: pd.DataFrame, uid_column: str = 'all_project_uids') -> pd.DataFrame:
        """
        Explode DataFrame so each row contains a single project UID.
        
        Args:
            df: DataFrame with list column to explode
            uid_column: Name of column containing UID lists
            
        Returns:
            Exploded DataFrame with one row per project UID
        """
        if uid_column not in df.columns:
            raise ValueError(f"Column '{uid_column}' not found. Run combine_project_uids() first.")
        
        # Only explode rows that have UIDs
        has_uids = df[uid_column].apply(lambda x: len(x) > 0 if isinstance(x, list) else False)
        
        df_with_uids = df[has_uids].copy()
        df_without_uids = df[~has_uids].copy()
        
        if len(df_with_uids) == 0:
            logger.warning("No rows have project UIDs to explode")
            df['project_uid'] = None
            return df
        
        # Explode the UID column
        df_exploded = df_with_uids.explode(uid_column).reset_index(drop=True)
        df_exploded = df_exploded.rename(columns={uid_column: 'project_uid'})
        
        logger.info(f"Exploded {len(df_with_uids)} rows to {len(df_exploded)} rows (one per project UID)")
        
        return df_exploded
    
    @classmethod
    def create_hub_project_mapping(cls, df: pd.DataFrame) -> pd.DataFrame:
        """
        Create a hub-to-project mapping table.
        
        Combines UIDs and explodes in one step, creating a clean
        mapping of H3 cells to individual project UIDs.
        
        Args:
            df: DataFrame from InventarHubLinker.process()
            
        Returns:
            DataFrame with columns: group, h3_index, project_uid, [other hub columns]
        """
        # Step 1: Combine all UIDs
        df_combined = cls.combine_project_uids(df)
        
        # Step 2: Explode to one row per project
        df_exploded = cls.explode_by_project(df_combined)
        
        return df_exploded


class InventarHubLinker:
    """
    Main processor that links infrastructure projects to transit hubs.
    
    This is the orchestrator class that coordinates data loading,
    H3 conversion, and spatial intersection.
    """
    
    def __init__(self, config: ProcessingConfig):
        """
        Initialize the linker with configuration.
        
        Args:
            config: ProcessingConfig with all paths and settings
        """
        self.config = config
        self._hub_loader = HubDataLoader(config)
        self._loader_factory = InventarLoaderFactory(config)
        self._converter = H3PolygonConverter()
    
    def process(self) -> pd.DataFrame:
        """
        Execute the full linking pipeline.
        
        Returns:
            DataFrame with hubs enriched with intersecting project UIDs
        """
        # Validate configuration
        self.config.validate()
        
        # Load hub data
        hub_df = self._hub_loader.load()
        
        # Load all geometry layers
        geometry_gdfs = self._load_all_geometries()
        
        # Convert H3 indices to polygons
        logger.info("Converting H3 indices to polygons...")
        hub_df['h3_polygon'] = self._converter.convert_series(hub_df[self.config.h3_column])
        
        # Perform spatial intersections
        hub_df = self._compute_all_intersections(hub_df, geometry_gdfs)
        
        # Clean up intermediate columns
        hub_df = hub_df.drop(columns=['h3_polygon'])
        
        logger.info(f"Processing complete. Result has {len(hub_df)} rows")
        return hub_df
    
    def _load_all_geometries(self) -> Dict[str, gpd.GeoDataFrame]:
        """Load all geometry layers."""
        loaders = self._loader_factory.create_all_loaders()
        return {name: loader.load() for name, loader in loaders.items()}
    
    def _compute_all_intersections(
        self, 
        hub_df: pd.DataFrame, 
        geometry_gdfs: Dict[str, gpd.GeoDataFrame]
    ) -> pd.DataFrame:
        """Compute intersections for all geometry types."""
        
        # Create intersectors for each geometry type
        intersectors = {
            name: SpatialIntersector(gdf, self.config.uid_column)
            for name, gdf in geometry_gdfs.items()
        }
        
        logger.info("Computing spatial intersections...")
        
        # Compute intersections for all rows
        results = {
            f'intersecting_{name}': [] 
            for name in intersectors.keys()
        }
        
        total_rows = len(hub_df)
        for idx, (_, row) in enumerate(hub_df.iterrows()):
            if idx % 1000 == 0 and idx > 0:
                logger.info(f"Processed {idx}/{total_rows} rows")
            
            polygon = row['h3_polygon']
            
            for name, intersector in intersectors.items():
                uids = intersector.find_intersecting_uids(polygon)
                results[f'intersecting_{name}'].append(uids)
        
        # Assign results to DataFrame
        for col_name, values in results.items():
            hub_df[col_name] = values
        
        # Log summary statistics
        self._log_intersection_summary(hub_df, results.keys())
        
        return hub_df
    
    def _log_intersection_summary(self, df: pd.DataFrame, columns: List[str]) -> None:
        """Log summary of intersection results."""
        for col in columns:
            non_empty = df[col].apply(lambda x: len(x) > 0).sum()
            logger.info(f"{col}: {non_empty} H3 cells have intersections")
    
    def save(self, df: pd.DataFrame, suffix: str = '') -> Path:
        """
        Save results to CSV.
        
        Args:
            df: DataFrame to save
            suffix: Optional suffix to add before file extension
            
        Returns:
            Path to saved file
        """
        if suffix:
            # Insert suffix before extension
            output_path = self.config.output_csv_path.with_stem(
                f"{self.config.output_csv_path.stem}_{suffix}"
            )
        else:
            output_path = self.config.output_csv_path
        
        logger.info(f"Saving results to {output_path}")
        
        # Ensure output directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        df.to_csv(output_path, encoding=self.config.encoding, index=False)
        logger.info(f"Saved {len(df)} rows to {output_path}")
        
        return output_path
    
    def process_and_save_all_formats(self) -> Dict[str, pd.DataFrame]:
        """
        Process and save results in multiple formats.
        
        Creates three output files:
        1. Base output: One row per H3 cell with intersection lists
        2. Combined output: Same as base, plus 'all_project_uids' column
        3. Exploded output: One row per (H3 cell, project UID) pair
        
        Returns:
            Dict with keys 'base', 'combined', 'exploded' containing DataFrames
        """
        # Process base data
        base_df = self.process()
        self.save(base_df)
        
        # Create combined version
        combined_df = ResultTransformer.combine_project_uids(base_df)
        self.save(combined_df, suffix='combined')
        
        # Create exploded version
        exploded_df = ResultTransformer.explode_by_project(combined_df)
        self.save(exploded_df, suffix='exploded')
        
        # Log summary
        logger.info("=" * 50)
        logger.info("Processing Summary:")
        logger.info(f"  Base output: {len(base_df)} H3 cells")
        logger.info(f"  Combined output: {len(combined_df)} H3 cells with all_project_uids")
        logger.info(f"  Exploded output: {len(exploded_df)} (H3 cell, project) pairs")
        logger.info("=" * 50)
        
        return {
            'base': base_df,
            'combined': combined_df,
            'exploded': exploded_df
        }


# =============================================================================
# Convenience Functions
# =============================================================================

def link_inventar_to_hubs(
    hubs_csv: str,
    inventar_dir: str,
    output_csv: str,
    encoding: str = 'windows-1255',
    create_all_formats: bool = True
) -> Dict[str, pd.DataFrame]:
    """
    Convenience function to run the full pipeline.
    
    Args:
        hubs_csv: Path to hub results CSV from Transit Hub Pipeline
        inventar_dir: Path to directory containing Inventar shapefiles
        output_csv: Path for output CSV
        encoding: File encoding (default: windows-1255 for Hebrew)
        create_all_formats: If True, creates three output files:
            - {output_csv}: Base output with intersection lists
            - {output_csv}_combined: With all_project_uids column
            - {output_csv}_exploded: One row per project UID
        
    Returns:
        Dict with 'base', 'combined', 'exploded' DataFrames
        
    Example:
        >>> results = link_inventar_to_hubs(
        ...     hubs_csv='/data/Results_29-12-2025.csv',
        ...     inventar_dir='/data/Inventar',
        ...     output_csv='/data/Hubs_with_Inventar.csv'
        ... )
        >>> exploded_df = results['exploded']
        >>> print(f"Total hub-project pairs: {len(exploded_df)}")
    """
    config = ProcessingConfig(
        hubs_csv_path=hubs_csv,
        inventar_directory=inventar_dir,
        output_csv_path=output_csv,
        encoding=encoding
    )
    
    linker = InventarHubLinker(config)
    
    if create_all_formats:
        return linker.process_and_save_all_formats()
    else:
        result = linker.process()
        linker.save(result)
        return {'base': result}


def combine_and_explode_projects(df: pd.DataFrame) -> pd.DataFrame:
    """
    Combine all project UIDs and explode to one row per project.
    
    Convenience function for post-processing an existing DataFrame.
    
    Args:
        df: DataFrame with intersecting_points, intersecting_lines, 
            intersecting_multilines columns
            
    Returns:
        Exploded DataFrame with 'project_uid' column
        
    Example:
        >>> base_df = pd.read_csv('hubs_with_inventar.csv')
        >>> exploded = combine_and_explode_projects(base_df)
    """
    return ResultTransformer.create_hub_project_mapping(df)


def get_hubs_with_projects(df: pd.DataFrame) -> pd.DataFrame:
    """
    Filter to only hubs that have at least one intersecting project.
    
    Args:
        df: DataFrame from link_inventar_to_hubs()
        
    Returns:
        Filtered DataFrame
    """
    mask = (
        df['intersecting_points'].apply(len) > 0 |
        df['intersecting_lines'].apply(len) > 0 |
        df['intersecting_multilines'].apply(len) > 0
    )
    return df[mask]


# =============================================================================
# CLI Entry Point
# =============================================================================

def main():
    """Command-line entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='Link infrastructure inventory projects to transit hubs'
    )
    parser.add_argument(
        '--hubs', '-H',
        required=True,
        help='Path to hubs CSV from Transit Hub Pipeline'
    )
    parser.add_argument(
        '--inventar', '-I',
        required=True,
        help='Path to Inventar directory with shapefiles'
    )
    parser.add_argument(
        '--output', '-o',
        required=True,
        help='Path for output CSV'
    )
    parser.add_argument(
        '--encoding', '-e',
        default='windows-1255',
        help='File encoding (default: windows-1255)'
    )
    
    args = parser.parse_args()
    
    link_inventar_to_hubs(
        hubs_csv=args.hubs,
        inventar_dir=args.inventar,
        output_csv=args.output,
        encoding=args.encoding
    )


if __name__ == '__main__':
    main()
