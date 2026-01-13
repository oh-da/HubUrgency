# HubUrgency

A spatial analysis system for calculating weighted project status progress for transit hubs in Israel.

## Overview

HubUrgency is a two-part pipeline that:
1. **Spatial Linking**: Links infrastructure projects to transit hubs using H3 hexagonal grid spatial intersection
2. **Status Calculation**: Calculates weighted project status progress for each hub based on project completion

## Features

- **H3 Hexagonal Grid Integration**: Uses Uber's H3 spatial indexing system for efficient geographic operations
- **Multi-Geometry Support**: Handles point, line, and multiline infrastructure projects
- **SOLID Architecture**: Clean, maintainable code following SOLID principles
- **Hebrew Text Support**: Proper handling of Hebrew text with windows-1255 encoding
- **Weighted Progress Metrics**: Customizable status weights for accurate progress tracking
- **Multiple Output Formats**: CSV outputs with various aggregation levels

## Quick Start

### Installation

```bash
# Clone the repository
git clone <repository-url>
cd HubUrgency

# Install dependencies
pip install -r requirements.txt
```

### Basic Usage

**Part 1: Link Projects to Hubs**
```python
from src.inventar_hub_linker import InventarHubLinker, ProcessingConfig

config = ProcessingConfig(
    hub_csv_path='path/to/hubs.csv',
    hub_h3_column='h3_8',
    inventar_point_path='path/to/points.shp',
    inventar_line_path='path/to/lines.shp',
    inventar_multiline_path='path/to/multilines.shp'
)

linker = InventarHubLinker(config)
result_df = linker.run()
```

**Part 2: Calculate Hub Status**
```python
from src.hub_project_status_calculator import HubProjectStatusPipeline

pipeline = HubProjectStatusPipeline(
    hub_csv_path='path/to/hubs_with_uids.csv',
    project_csv_path='path/to/projects.csv',
    status_weights_path='path/to/status_weights.csv'
)

results = pipeline.run()
```

## Project Structure

```
HubUrgency/
├── src/                              # Source code
│   ├── hub_project_status_calculator.py
│   ├── inventar_hub_linker.py
│   └── __init__.py
├── tests/                            # Unit tests
│   └── test_calculator.py
├── notebooks/                        # Jupyter notebooks
│   ├── Hub_Project_Status_Analysis.ipynb
│   └── inventar_hub_linker_notebook.ipynb
├── docs/                             # Documentation
│   ├── documentation.md              # Complete technical documentation
│   ├── USAGE_GUIDE.md               # Usage guide for status calculator
│   ├── INVENTAR_LINKER_README.md    # Spatial linker documentation
│   ├── STATUS_ZERO_GUIDE.md         # Analysis guide for cancelled projects
│   ├── FIX_DOCUMENTATION.md         # Bug fixes and migration guide
│   └── claude_md_Hubs_Urgency.md    # Technical reference
├── requirements.txt                  # Python dependencies
├── .gitignore                        # Git ignore rules
└── README.md                         # This file
```

## Documentation

- **[Complete Documentation](docs/documentation.md)**: Comprehensive guide covering architecture, installation, usage, and troubleshooting
- **[Usage Guide](docs/USAGE_GUIDE.md)**: Detailed usage instructions for the status calculator
- **[Spatial Linker Guide](docs/INVENTAR_LINKER_README.md)**: Documentation for the spatial linking module
- **[Status Zero Analysis](docs/STATUS_ZERO_GUIDE.md)**: Guide for analyzing cancelled/stalled projects
- **[Bug Fixes](docs/FIX_DOCUMENTATION.md)**: Documentation of bug fixes and migrations

## Dependencies

- **pandas** (>=2.0.0): Data manipulation and analysis
- **numpy** (>=1.24.0): Numerical computing
- **geopandas** (>=0.14.0): Geographic data operations
- **shapely** (>=2.0.0): Geometric operations
- **h3** (>=3.7.0): Hexagonal hierarchical spatial indexing
- **jupyter** (>=1.0.0): Interactive notebooks
- **matplotlib** (>=3.7.0): Data visualization

## Architecture

The system follows a **two-stage pipeline architecture**:

### Stage 1: Spatial Linking (inventar_hub_linker.py)
- Loads hub data with H3 hexagonal indices
- Loads infrastructure projects from shapefiles (points, lines, multilines)
- Performs spatial intersection using R-tree indexing
- Outputs hub-to-project UID mappings

### Stage 2: Status Calculation (hub_project_status_calculator.py)
- Loads hub-project mappings and project status data
- Joins project information to hubs
- Calculates weighted progress based on customizable status weights
- Generates multiple output formats

Both modules follow **SOLID principles** for maintainability and extensibility.

## Testing

```bash
# Run unit tests
pytest tests/

# Run specific test file
pytest tests/test_calculator.py
```

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## Data Requirements

### Input Files
- **Hub CSV**: Must contain H3 hexagonal indices and hub identifiers
- **Project Shapefiles**: Point, line, and multiline geometries with UID fields
- **Status Weights CSV**: Mapping of status codes to weight values

### Output Files
- **Hub-Project Mapping**: CSV with hub IDs and associated project UIDs
- **Status Progress**: CSV with calculated weighted progress per hub
- **Detailed Results**: Multiple aggregation levels for analysis

## Performance

- Handles large datasets efficiently using R-tree spatial indexing
- Average processing time: ~2-5 minutes for typical datasets
- Memory efficient with streaming operations where possible

## License

[Add license information]

## Contact

[Add contact information]

## Acknowledgments

- Uses Uber's H3 hexagonal hierarchical spatial indexing system
- Built with GeoPandas for efficient geographic operations
