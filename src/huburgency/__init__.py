"""
HubUrgency - Transit Hub Project Status Analysis System

A spatial analysis system for calculating weighted project status progress
for transit hubs using H3 hexagonal grid spatial intersection.

Modules:
    inventar_hub_linker: Links infrastructure projects to transit hubs using spatial intersection
    hub_project_status_calculator: Calculates weighted project status progress for hubs
"""

__version__ = "1.0.0"
__author__ = "Ohad Dahan"
__email__ = "ohad@ayalonhw.co.il"

from .inventar_hub_linker import (
    InventarHubLinker,
    ProcessingConfig,
    H3ListParser,
    HubDataLoader,
    InventarLoaderFactory,
    H3PolygonConverter,
    SpatialIntersector,
    link_inventar_to_hubs,
    combine_and_explode_projects,
    get_hubs_with_projects,
)

from .hub_project_status_calculator import (
    HubProjectStatusPipeline,
    DataLoader,
    ListColumnParser,
    ProjectDataJoiner,
    StatusProgressCalculator,
    StatusOverrideHandler,
    PreExplodedDataHandler,
    load_hub_csv,
    fix_scn_year_dtype,
)

__all__ = [
    # Spatial Linker
    "InventarHubLinker",
    "ProcessingConfig",
    "H3ListParser",
    "HubDataLoader",
    "InventarLoaderFactory",
    "H3PolygonConverter",
    "SpatialIntersector",
    "link_inventar_to_hubs",
    "combine_and_explode_projects",
    "get_hubs_with_projects",
    # Status Calculator
    "HubProjectStatusPipeline",
    "DataLoader",
    "ListColumnParser",
    "ProjectDataJoiner",
    "StatusProgressCalculator",
    "StatusOverrideHandler",
    "PreExplodedDataHandler",
    "load_hub_csv",
    "fix_scn_year_dtype",
]
