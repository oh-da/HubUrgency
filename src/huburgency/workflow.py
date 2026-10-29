"""
End-to-End Workflow
===================

One call that runs the whole HubUrgency pipeline from an input folder to an
output folder:

    Stage 1  link inventar projects to hubs (H3 spatial intersection)
    Stage 2  join project status, apply manual overrides, score each hub

Expected contents of the input folder (file names are the defaults; every one
can be overridden):

    <hubs>.csv              hubs from the Transit Hub pipeline (auto-detected:
                            the CSV with ``group`` and ``h3_index`` columns)
    *.geojson               inventar as one GeoJSON file, OR
    geom_*.shp              inventar as shapefiles (also found in a sub-folder)
    status_weights.csv      Proj_status -> weight (required)
    status_overrides.csv    optional: uid, Proj_status - manual status fixes
    data.csv                optional: project attributes; when absent they are
                            read from the inventar (GeoJSON properties)

Usage::

    from huburgency.workflow import run_end_to_end
    result = run_end_to_end('/path/to/input', '/path/to/output')
    result.progress_df
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Union
import logging

import pandas as pd

from .inventar_hub_linker import (
    GEOJSON_SUFFIXES,
    InventarHubLinker,
    ProcessingConfig,
    load_inventar_attributes,
)
from .hub_project_status_calculator import (
    HubProjectStatusPipeline,
    ProjectDataJoiner,
    StatusOverrideHandler,
)

logger = logging.getLogger(__name__)

PathLike = Union[str, Path]

# File names written to the output folder.
OUT_LINKER = 'hubs_with_inventar.csv'          # + _combined / _exploded
OUT_JOINED = 'hub_project_joined.csv'
OUT_PROGRESS = 'hub_progress.csv'
OUT_BREAKDOWN = 'hub_status_breakdown.csv'
OUT_STATUS_ZERO = 'status_zero_projects.csv'
OUT_WEIGHTS_TEMPLATE = 'status_weights_template.csv'
OUT_MAP = 'hub_urgency_map.html'
OUT_REPORT = 'hub_urgency_report.html'

# Starting-point weights proposed in the generated template. These are a
# suggestion for the Hebrew planning stages seen in the Inventar, not a
# definition: review them before use.
SUGGESTED_STATUS_WEIGHTS = {
    '?': 0.0,
    'תכנון אסטרטגי': 0.10,
    'תכנון מוקדם': 0.20,
    'תכנון מוקדם סטטוטורי': 0.30,
    'תכנון ראשוני': 0.40,
    'תכנון מפורט': 0.60,
    'ביצוע': 0.85,
}

_HUB_INFO_COLS = ['x', 'y', 'HubNameHE']


# =============================================================================
# Input discovery
# =============================================================================

@dataclass
class WorkflowInputs:
    """Resolved input locations; optional inputs are None when absent."""

    hubs_csv: Path
    inventar: Path
    status_weights_csv: Path
    status_overrides_csv: Optional[Path] = None
    project_data_csv: Optional[Path] = None


def read_csv_auto(path: PathLike) -> pd.DataFrame:
    """Read a CSV that may be UTF-8 (with/without BOM) or windows-1255."""
    last_error: Optional[Exception] = None
    for encoding in ('utf-8-sig', 'windows-1255'):
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    raise last_error  # type: ignore[misc]


def _read_csv_header(path: Path) -> List[str]:
    for encoding in ('utf-8-sig', 'windows-1255'):
        try:
            return list(pd.read_csv(path, encoding=encoding, nrows=0).columns)
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError('csv', b'', 0, 1, f'cannot decode header of {path}')


def _find_hubs_csv(input_dir: Path) -> Path:
    """The one CSV in ``input_dir`` that has both ``group`` and ``h3_index`` columns."""
    matches = []
    for csv in sorted(input_dir.glob('*.csv')):
        try:
            cols = set(_read_csv_header(csv))
        except Exception:  # unreadable CSV: not our hubs file
            continue
        if {'group', 'h3_index'} <= cols:
            matches.append(csv)
    if not matches:
        raise FileNotFoundError(
            f"No hubs CSV (with 'group' and 'h3_index' columns) found in {input_dir}"
        )
    if len(matches) > 1:
        raise ValueError(
            f"Several hubs CSV candidates in {input_dir}: {[m.name for m in matches]}. "
            "Pass hubs_csv explicitly."
        )
    return matches[0]


def _has_inventar(directory: Path) -> bool:
    cfg = ProcessingConfig(hubs_csv_path='_', inventar_directory=directory, output_csv_path='_')
    if any(
        (directory / n).exists()
        for n in (cfg.point_shapefile, cfg.line_shapefile, cfg.multiline_shapefile)
    ):
        return True
    return any(f.suffix.lower() in GEOJSON_SUFFIXES for f in directory.iterdir() if f.is_file())


def _find_inventar(input_dir: Path) -> Path:
    """``input_dir`` itself, or the first sub-folder, holding shapefiles / a GeoJSON."""
    for candidate in [input_dir] + sorted(p for p in input_dir.iterdir() if p.is_dir()):
        if _has_inventar(candidate):
            return candidate
    raise FileNotFoundError(
        f"No inventar found in {input_dir}: expected a .geojson file or geom_*.shp files "
        "(directly in the folder or in a sub-folder)."
    )


def discover_inputs(
    input_dir: PathLike,
    hubs_csv: Optional[str] = None,
    inventar: Optional[str] = None,
    status_weights_csv: str = 'status_weights.csv',
    status_overrides_csv: str = 'status_overrides.csv',
    project_data_csv: str = 'data.csv',
) -> WorkflowInputs:
    """
    Locate every input inside ``input_dir``.

    File names are relative to ``input_dir`` (absolute paths also work).
    ``hubs_csv`` and ``inventar`` are auto-detected when None. The overrides
    and project-data files are optional: when missing, they are skipped.
    The status-weights path is returned even if the file does not exist; the
    run reports that with a template (see ``run_end_to_end``).
    """
    input_dir = Path(input_dir)
    if not input_dir.is_dir():
        raise FileNotFoundError(f"Input folder not found: {input_dir}")

    def _resolve(name: str) -> Path:
        return input_dir / name  # absolute names win via pathlib semantics

    def _optional(name: str) -> Optional[Path]:
        path = _resolve(name)
        return path if path.exists() else None

    hubs = _resolve(hubs_csv) if hubs_csv else _find_hubs_csv(input_dir)
    if not hubs.exists():
        raise FileNotFoundError(f"Hubs CSV not found: {hubs}")
    inventar_path = _resolve(inventar) if inventar else _find_inventar(input_dir)
    if not inventar_path.exists():
        raise FileNotFoundError(f"Inventar not found: {inventar_path}")

    return WorkflowInputs(
        hubs_csv=hubs,
        inventar=inventar_path,
        status_weights_csv=_resolve(status_weights_csv),
        status_overrides_csv=_optional(status_overrides_csv),
        project_data_csv=_optional(project_data_csv),
    )


# =============================================================================
# Status handling
# =============================================================================

def clean_status(value):
    """Normalise a status label: strip whitespace, turn 2.0 into '2'; NaN stays NaN."""
    if pd.isna(value):
        return value
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def clean_status_series(series: pd.Series) -> pd.Series:
    return series.map(clean_status)


def build_weights_template(statuses: pd.Series) -> pd.DataFrame:
    """
    Ready-to-edit ``status_weights`` table for the statuses present in the data.

    Weights come from ``SUGGESTED_STATUS_WEIGHTS`` where the label is known;
    others get 0 and a note asking for a manual value.
    """
    counts = clean_status_series(statuses).dropna().value_counts()
    rows = []
    for label, n in counts.items():
        known = label in SUGGESTED_STATUS_WEIGHTS
        rows.append({
            'Proj_status': label,
            'weight': SUGGESTED_STATUS_WEIGHTS.get(label, 0.0),
            'n_projects': int(n),
            'note': 'suggested - review' if known else 'no suggestion - set manually',
        })
    return pd.DataFrame(rows, columns=['Proj_status', 'weight', 'n_projects', 'note'])


def load_status_weights(path: PathLike) -> pd.DataFrame:
    df = read_csv_auto(path)
    missing = {'Proj_status', 'weight'} - set(df.columns)
    if missing:
        raise ValueError(f"{Path(path).name} is missing required columns: {sorted(missing)}")
    df = df.copy()
    df['Proj_status'] = clean_status_series(df['Proj_status'])
    df['weight'] = pd.to_numeric(df['weight'], errors='raise')
    dupes = df['Proj_status'][df['Proj_status'].duplicated()].unique()
    if len(dupes):
        raise ValueError(f"Duplicate Proj_status in {Path(path).name}: {list(dupes)}")
    return df


def normalise_overrides(override_df: pd.DataFrame) -> pd.DataFrame:
    """Validated ``uid`` (int) / ``Proj_status`` (clean str) table, last row per UID wins."""
    missing = {'uid', 'Proj_status'} - set(override_df.columns)
    if missing:
        raise ValueError(f"Status overrides file is missing required columns: {sorted(missing)}")
    overrides = override_df[['uid', 'Proj_status']].copy()
    overrides['Proj_status'] = clean_status_series(overrides['Proj_status'])
    overrides = overrides.dropna()
    overrides['uid'] = pd.to_numeric(overrides['uid'], errors='coerce')
    overrides = overrides.dropna(subset=['uid'])
    overrides['uid'] = overrides['uid'].astype('int64')
    return overrides.drop_duplicates(subset='uid', keep='last')


def find_unknown_override_uids(project_df: pd.DataFrame, overrides: pd.DataFrame) -> List[int]:
    """Override UIDs that match no project (they are ignored)."""
    return sorted(int(u) for u in set(overrides['uid']) - set(project_df['uid'].astype('int64')))


def apply_status_overrides(
    project_df: pd.DataFrame, override_df: Optional[pd.DataFrame]
) -> pd.DataFrame:
    """
    Replace ``Proj_status`` for the UIDs listed in ``override_df``.

    Adds ``Proj_status_original`` and ``status_overridden`` so the change stays
    visible downstream. With no overrides the original statuses are kept.
    """
    result = project_df.copy()
    result['Proj_status_original'] = result['Proj_status']
    if override_df is None:
        result['status_overridden'] = False
        return result

    overrides = normalise_overrides(override_df)
    unknown = find_unknown_override_uids(project_df, overrides)
    if unknown:
        logger.warning(f"Override UIDs not found in the project data (ignored): {unknown}")

    result = StatusOverrideHandler(overrides).apply_overrides(
        result, uid_col='uid', status_col='Proj_status'
    )
    result['status_overridden'] = (
        result['Proj_status'].astype(str) != result['Proj_status_original'].astype(str)
    )
    return result


# =============================================================================
# Orchestration
# =============================================================================

@dataclass
class WorkflowResult:
    """Everything produced by ``run_end_to_end``."""

    inputs: WorkflowInputs
    output_dir: Path
    project_df: pd.DataFrame
    weights_df: pd.DataFrame
    linker_outputs: Dict[str, pd.DataFrame]
    joined_df: pd.DataFrame
    progress_df: pd.DataFrame
    status_breakdown_df: pd.DataFrame
    status_zero_df: Optional[pd.DataFrame]
    config: Optional[ProcessingConfig] = None
    group_col: str = 'group'
    unmapped_statuses: List[str] = field(default_factory=list)
    unknown_override_uids: List[int] = field(default_factory=list)
    n_overridden: int = 0
    outputs: Dict[str, Path] = field(default_factory=dict)


def _save_csv(df: pd.DataFrame, path: Path, encoding: str) -> Path:
    """Save a CSV, falling back to UTF-8 if a character does not fit ``encoding``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        df.to_csv(path, index=False, encoding=encoding)
    except UnicodeEncodeError:
        logger.warning(f"{path.name}: characters not representable in {encoding}; saved as utf-8-sig")
        df.to_csv(path, index=False, encoding='utf-8-sig')
    return path


def prepare_project_table(
    inputs: WorkflowInputs, config: ProcessingConfig
) -> pd.DataFrame:
    """Project attributes from ``data.csv`` if supplied, else from the inventar itself."""
    if inputs.project_data_csv is not None:
        logger.info(f"Project attributes: {inputs.project_data_csv.name}")
        df = read_csv_auto(inputs.project_data_csv)
    else:
        df = load_inventar_attributes(config)
        if df is None:
            raise ValueError("The inventar contains no features, and no data.csv was supplied.")
        logger.info("Project attributes: read from the inventar")

    missing = [c for c in ProjectDataJoiner.REQUIRED_PROJECT_COLS if c not in df.columns]
    if missing:
        raise ValueError(
            f"Project data is missing columns {missing}. Provide a data.csv with "
            f"{ProjectDataJoiner.REQUIRED_PROJECT_COLS} next to the inventar."
        )
    df = df.copy()
    df['uid'] = pd.to_numeric(df['uid'], errors='coerce')
    df = df.dropna(subset=['uid'])
    df['uid'] = df['uid'].astype('int64')
    if df['uid'].duplicated().any():
        logger.warning("Duplicate project UIDs in the project data; keeping the first of each")
        df = df.drop_duplicates(subset='uid')
    df['Proj_status'] = clean_status_series(df['Proj_status'])
    return df.reset_index(drop=True)


def run_end_to_end(
    input_dir: PathLike,
    output_dir: PathLike,
    hubs_csv: Optional[str] = None,
    inventar: Optional[str] = None,
    status_weights_csv: str = 'status_weights.csv',
    status_overrides_csv: str = 'status_overrides.csv',
    project_data_csv: str = 'data.csv',
    encoding: str = 'windows-1255',
    group_col: str = 'group',
    make_report: bool = True,
) -> WorkflowResult:
    """
    Run Stage 1 and Stage 2 for the files in ``input_dir``; write CSVs to ``output_dir``.

    Args:
        input_dir: folder holding the inputs (see the module docstring).
        output_dir: folder for all outputs (created if needed).
        hubs_csv / inventar: file names inside ``input_dir``; auto-detected when None.
        status_weights_csv: required Proj_status -> weight table.
        status_overrides_csv: optional ``uid, Proj_status`` file. If it does not
            exist the statuses from the inventar / data.csv are used unchanged.
        project_data_csv: optional project attribute table.
        encoding: encoding of the hubs CSV and of the CSVs written.
        group_col: hub id column.
        make_report: also write ``hub_urgency_map.html`` and ``hub_urgency_report.html``
            (the map is skipped with a warning if ``folium`` is not installed).

    Raises:
        FileNotFoundError: when ``status_weights.csv`` is missing. A pre-filled
            ``status_weights_template.csv`` is written to ``output_dir`` first.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    inputs = discover_inputs(
        input_dir, hubs_csv, inventar, status_weights_csv, status_overrides_csv, project_data_csv
    )
    logger.info(f"Hubs: {inputs.hubs_csv.name} | Inventar: {inputs.inventar} | "
                f"Overrides: {inputs.status_overrides_csv.name if inputs.status_overrides_csv else 'none'}")

    config = ProcessingConfig(
        hubs_csv_path=inputs.hubs_csv,
        inventar_directory=inputs.inventar,
        output_csv_path=output_dir / OUT_LINKER,
        encoding=encoding,
    )
    config.validate()

    # --- Project statuses, overrides and weights: cheap checks before the slow linking ---
    project_df = prepare_project_table(inputs, config)
    override_df = None
    unknown_override_uids: List[int] = []
    if inputs.status_overrides_csv is not None:
        override_df = read_csv_auto(inputs.status_overrides_csv)
        logger.info(f"Status overrides: {len(override_df)} rows from {inputs.status_overrides_csv.name}")
        unknown_override_uids = find_unknown_override_uids(project_df, normalise_overrides(override_df))
    else:
        logger.info("No status overrides file found - using statuses as they are in the data")
    project_df = apply_status_overrides(project_df, override_df)
    n_overridden = int(project_df['status_overridden'].sum())

    outputs: Dict[str, Path] = {}
    template = build_weights_template(project_df['Proj_status'])
    outputs['weights_template'] = _save_csv(template, output_dir / OUT_WEIGHTS_TEMPLATE, 'utf-8-sig')

    if not inputs.status_weights_csv.exists():
        raise FileNotFoundError(
            f"Status weights file not found: {inputs.status_weights_csv}\n"
            f"A template with the {len(template)} statuses in your data was written to "
            f"{outputs['weights_template']}. Review the weights, save it as "
            f"'{inputs.status_weights_csv.name}' in the input folder and run again."
        )
    weights_df = load_status_weights(inputs.status_weights_csv)
    unmapped = sorted(set(project_df['Proj_status'].dropna()) - set(weights_df['Proj_status']))
    if unmapped:
        logger.warning(
            f"Statuses with no weight (counted as 0): {unmapped}. "
            f"Add them to {inputs.status_weights_csv.name}."
        )

    # --- Stage 1 ---
    linker_outputs = InventarHubLinker(config).process_and_save_all_formats()
    for key, suffix in (('base', ''), ('combined', '_combined'), ('exploded', '_exploded')):
        outputs[f'linker_{key}'] = config.output_csv_path.with_stem(
            f"{config.output_csv_path.stem}{suffix}"
        )

    # --- Stage 2 (pre-exploded mode: one row per hub x project, deduplicated) ---
    base_df = linker_outputs['base']
    exploded = linker_outputs['exploded'].copy()
    drop_cols = [c for c in exploded.columns
                 if c == 'h3_index' or c == 'all_project_uids' or c.startswith('intersecting_')]
    exploded = exploded.drop(columns=drop_cols)
    exploded['project_uid'] = pd.to_numeric(exploded['project_uid'], errors='coerce')

    attr_cols = ['uid'] + [c for c in ProjectDataJoiner.REQUIRED_PROJECT_COLS if c != 'uid']
    attr_cols += ['Proj_status_original', 'status_overridden']
    hub_project_df = exploded.merge(
        project_df[attr_cols], left_on='project_uid', right_on='uid', how='left'
    ).drop(columns='uid')

    pipeline = HubProjectStatusPipeline(
        status_weights_df=weights_df,
        hub_project_df=hub_project_df,
        use_pre_exploded=True,
        all_hubs_df=base_df,
    )
    joined_df, progress_df, breakdown_df = pipeline.run(group_col=group_col)

    hub_info = (base_df[[group_col] + [c for c in _HUB_INFO_COLS if c in base_df.columns]]
                .drop_duplicates(subset=group_col))
    progress_df = progress_df.merge(hub_info, on=group_col, how='left')
    pipeline.progress_df = progress_df
    status_zero_df = pipeline.get_status_zero_projects()
    if status_zero_df is not None:
        # Rows without a project_uid are zero-project hub placeholders, not projects.
        status_zero_df = status_zero_df[status_zero_df['project_uid'].notna()]
        if status_zero_df.empty:
            status_zero_df = None

    outputs['joined'] = _save_csv(joined_df, output_dir / OUT_JOINED, encoding)
    outputs['progress'] = _save_csv(progress_df, output_dir / OUT_PROGRESS, encoding)
    outputs['breakdown'] = _save_csv(breakdown_df, output_dir / OUT_BREAKDOWN, encoding)
    if status_zero_df is not None:
        outputs['status_zero'] = _save_csv(status_zero_df, output_dir / OUT_STATUS_ZERO, encoding)

    result = WorkflowResult(
        inputs=inputs,
        output_dir=output_dir,
        project_df=project_df,
        weights_df=weights_df,
        linker_outputs=linker_outputs,
        joined_df=joined_df,
        progress_df=progress_df,
        status_breakdown_df=breakdown_df,
        status_zero_df=status_zero_df,
        config=config,
        group_col=group_col,
        unmapped_statuses=unmapped,
        unknown_override_uids=unknown_override_uids,
        n_overridden=n_overridden,
        outputs=outputs,
    )

    if make_report:
        from .report import export_report
        outputs.update(export_report(result, output_dir / OUT_MAP, output_dir / OUT_REPORT))
    return result
