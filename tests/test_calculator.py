"""
Unit tests for the Hub Project Status Calculator.

These tests are fully self-contained: all hub, project and status-weight data
is built in-memory, so no external CSV fixtures are required. Run with:

    pytest tests/
"""

import pandas as pd
import pytest

from huburgency import (
    HubProjectStatusPipeline,
    ProjectDataJoiner,
    StatusProgressCalculator,
    StatusOverrideHandler,
    PreExplodedDataHandler,
    ListColumnParser,
    get_hubs_with_projects,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def hub_df():
    """Hub hexagons with actual list columns (as produced by the linker)."""
    return pd.DataFrame({
        'group': [100, 100, 100, 200, 200, 300],
        'x': [34.81, 34.81, 34.81, 32.07, 32.07, 35.20],
        'y': [32.04, 32.04, 32.04, 34.77, 34.77, 31.26],
        'HubNameHE': ['תל אביב מרכז'] * 3 + ['חיפה'] * 2 + ['באר שבע'],
        'h3_index': [
            '8a2a1072b59ffff', '8a2a1072b5affff', '8a2a1072b5bffff',
            '8a3969a34d9ffff', '8a3969a34daffff', '8a2b0a434c1ffff',
        ],
        'intersecting_points': [
            ['proj_001', 'proj_002'], ['proj_003'], [],
            ['proj_004', 'proj_005'], ['proj_006'], ['proj_007', 'proj_008'],
        ],
        'intersecting_lines': [
            ['proj_009'], [], ['proj_010'], [], ['proj_011'], [],
        ],
        'intersecting_multilines': [
            [], ['proj_012'], [], ['proj_013'], [], ['proj_014', 'proj_015'],
        ],
    })


@pytest.fixture
def hub_df_with_duplicates():
    """Group 100 references proj_001/proj_002 multiple times across columns."""
    return pd.DataFrame({
        'group': [100, 100, 200],
        'x': [34.81, 34.81, 32.07],
        'y': [32.04, 32.04, 34.77],
        'HubNameHE': ['תל אביב מרכז', 'תל אביב מרכז', 'חיפה'],
        'h3_index': ['8a2a1072b59ffff', '8a2a1072b5affff', '8a3969a34d9ffff'],
        'intersecting_points': [
            ['proj_001', 'proj_002'], ['proj_001', 'proj_003'], ['proj_004'],
        ],
        'intersecting_lines': [['proj_002'], [], []],
        'intersecting_multilines': [[], ['proj_002'], []],
    })


@pytest.fixture
def project_df():
    """Project attribute table covering proj_001..proj_015."""
    uids = [f'proj_{i:03d}' for i in range(1, 16)]
    statuses = [0, 1, 2, 3, 4, 0, 1, 2, 3, 4, 0, 1, 2, 3, 4]
    return pd.DataFrame({
        'uid': uids,
        'proj_name': [f'Project {i}' for i in range(1, 16)],
        'main_type': ['road'] * 15,
        'Proj_status': statuses,
        'scn_year': ['2030'] * 15,  # intentionally string to exercise numeric coercion
    })


@pytest.fixture
def weights_df():
    """Status -> weight mapping (max weight = 4)."""
    return pd.DataFrame({
        'Proj_status': [0, 1, 2, 3, 4],
        'weight': [0, 1, 2, 3, 4],
    })


# =============================================================================
# ListColumnParser
# =============================================================================

@pytest.mark.parametrize("value,expected", [
    ("['a', 'b']", ['a', 'b']),
    ("[a, b]", ['a', 'b']),
    ("[]", []),
    ("", []),
    (None, []),
    (['x', 'y'], ['x', 'y']),
])
def test_list_column_parser(value, expected):
    assert ListColumnParser.parse_list_column(value) == expected


# =============================================================================
# Pipeline
# =============================================================================

def test_pipeline_runs_and_returns_three_frames(hub_df, project_df, weights_df):
    pipeline = HubProjectStatusPipeline(hub_df, project_df, weights_df)
    result = pipeline.run()

    assert len(result) == 3
    joined_df, progress_df, status_breakdown_df = result
    assert len(joined_df) > 0
    assert len(progress_df) > 0
    assert len(status_breakdown_df) > 0


def test_progress_columns_present(hub_df, project_df, weights_df):
    pipeline = HubProjectStatusPipeline(hub_df, project_df, weights_df)
    _, progress_df, _ = pipeline.run()

    for col in ('group', 'total_projects', 'current_weighted_sum',
                'max_possible_sum', 'status_progress_pct'):
        assert col in progress_df.columns

    # Progress is a percentage bounded to [0, 100]
    assert progress_df['status_progress_pct'].between(0, 100).all()


def test_progress_value_is_correct(project_df, weights_df):
    """Group 100 = proj_001(w0), proj_002(w1), proj_003(w2) -> 3/(3*4) = 25%."""
    hub_df = pd.DataFrame({
        'group': [100],
        'intersecting_points': [['proj_001', 'proj_002', 'proj_003']],
        'intersecting_lines': [[]],
        'intersecting_multilines': [[]],
    })
    pipeline = HubProjectStatusPipeline(hub_df, project_df, weights_df)
    _, progress_df, _ = pipeline.run()

    row = progress_df[progress_df['group'] == 100].iloc[0]
    assert row['total_projects'] == 3
    assert row['current_weighted_sum'] == 3      # 0 + 1 + 2
    assert row['max_possible_sum'] == 12         # 3 * 4
    assert row['status_progress_pct'] == pytest.approx(25.0)


# =============================================================================
# Deduplication
# =============================================================================

def test_deduplication_within_group(hub_df_with_duplicates, project_df):
    joiner = ProjectDataJoiner(hub_df_with_duplicates, project_df)
    joined_df = joiner.join_to_hubs()

    group_100 = set(joined_df[joined_df['group'] == 100]['uid'].unique())
    assert group_100 == {'proj_001', 'proj_002', 'proj_003'}


# =============================================================================
# Validation
# =============================================================================

def test_missing_required_project_columns_raises(hub_df):
    bad_project_df = pd.DataFrame({'uid': ['proj_001']})  # missing the rest
    with pytest.raises(ValueError):
        ProjectDataJoiner(hub_df, bad_project_df)


def test_unmapped_status_defaults_to_zero_weight(weights_df):
    df = pd.DataFrame({'group': [1], 'uid': ['x'], 'Proj_status': [99]})
    calc = StatusProgressCalculator(weights_df)
    mapped = calc._map_status_to_weight(df)
    assert mapped['status_weight'].iloc[0] == 0


# =============================================================================
# Linker helper (regression test for operator-precedence fix)
# =============================================================================

def test_get_hubs_with_projects_filters_empty_rows():
    df = pd.DataFrame({
        'intersecting_points': [['a'], [], []],
        'intersecting_lines': [[], ['b'], []],
        'intersecting_multilines': [[], [], []],
    })
    filtered = get_hubs_with_projects(df)
    # Only the first two rows have at least one intersecting project.
    assert len(filtered) == 2
    assert list(filtered.index) == [0, 1]


# =============================================================================
# Status overrides
# =============================================================================

def test_status_override_handler_applies_overrides():
    handler = StatusOverrideHandler(pd.DataFrame({
        'uid': [1, 2],
        'Proj_status': [4, 0],
    }))
    df = pd.DataFrame({
        'project_uid': [1, 2, 3],
        'Proj_status': [0, 0, 2],
    })
    result = handler.apply_overrides(df, uid_col='project_uid')
    assert result['Proj_status'].tolist() == [4, 0, 2]  # uid 3 unchanged


def test_status_override_missing_column_raises():
    with pytest.raises(ValueError):
        StatusOverrideHandler(pd.DataFrame({'uid': [1]}))  # no Proj_status


def test_pipeline_applies_status_override(weights_df):
    # Single project at status 0 (weight 0) -> overridden to status 4 (weight 4) -> 100%.
    hub_project_df = pd.DataFrame({
        'group': [100],
        'project_uid': [1],
        'Proj_status': [0],
    })
    override_df = pd.DataFrame({'uid': [1], 'Proj_status': [4]})
    pipeline = HubProjectStatusPipeline(
        status_weights_df=weights_df,
        hub_project_df=hub_project_df,
        status_override_df=override_df,
        use_pre_exploded=True,
    )
    _, progress_df, _ = pipeline.run()
    assert progress_df.loc[progress_df['group'] == 100, 'status_progress_pct'].iloc[0] == pytest.approx(100.0)


# =============================================================================
# Pre-exploded input mode
# =============================================================================

def test_pre_exploded_handler_preserves_zero_project_hubs():
    df = pd.DataFrame({
        'group': [100, 100, 200],
        'project_uid': [1, 2, None],   # group 200 has no projects
        'Proj_status': [1, 2, None],
    })
    prepared = PreExplodedDataHandler(df).get_data()
    assert set(prepared['group']) == {100, 200}
    assert prepared['project_uid'].isna().sum() == 1


def test_pre_exploded_pipeline_runs(weights_df):
    hub_project_df = pd.DataFrame({
        'group': [100, 100, 200],
        'project_uid': [1, 2, 3],
        'Proj_status': [1, 2, 3],
    })
    pipeline = HubProjectStatusPipeline(
        status_weights_df=weights_df,
        hub_project_df=hub_project_df,
        use_pre_exploded=True,
    )
    joined_df, progress_df, _ = pipeline.run()
    assert len(progress_df) == 2
    # group 100: weights 1+2 = 3 over 2*4 = 8 -> 37.5%
    assert progress_df.loc[progress_df['group'] == 100, 'status_progress_pct'].iloc[0] == pytest.approx(37.5)


def test_pre_exploded_requires_hub_project_df(weights_df):
    with pytest.raises(ValueError):
        HubProjectStatusPipeline(status_weights_df=weights_df, use_pre_exploded=True)


# =============================================================================
# All-hubs backfill (zero-project hubs)
# =============================================================================

def test_all_hubs_backfill_includes_zero_project_hubs(weights_df):
    hub_project_df = pd.DataFrame({
        'group': [100],
        'project_uid': [1],
        'Proj_status': [2],
    })
    all_hubs_df = pd.DataFrame({'group': [100, 200, 300]})
    pipeline = HubProjectStatusPipeline(
        status_weights_df=weights_df,
        hub_project_df=hub_project_df,
        all_hubs_df=all_hubs_df,
        use_pre_exploded=True,
    )
    _, progress_df, _ = pipeline.run()

    assert set(progress_df['group']) == {100, 200, 300}
    # Backfilled hubs report 0 projects and 0% progress.
    for g in (200, 300):
        row = progress_df[progress_df['group'] == g].iloc[0]
        assert row['total_projects'] == 0
        assert row['status_progress_pct'] == 0


def test_raw_mode_still_returns_three_frames(hub_df, project_df, weights_df):
    """Backward-compat: positional raw-mode construction is unchanged."""
    pipeline = HubProjectStatusPipeline(hub_df, project_df, weights_df)
    result = pipeline.run()
    assert len(result) == 3
