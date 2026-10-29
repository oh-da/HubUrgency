"""
Tests for GeoJSON / shapefile inventar loading and the end-to-end workflow.

All data is built in a temp folder: two hub groups sitting on two projects, plus
a hub far away from everything.
"""

import json
from pathlib import Path

import geopandas as gpd
import h3
import pandas as pd
import pytest
from shapely.geometry import LineString, MultiLineString, Point, Polygon

from huburgency import (
    GeoJSONSource,
    InventarHubLinker,
    InventarLoaderFactory,
    ProcessingConfig,
    discover_inputs,
    load_inventar_attributes,
    run_end_to_end,
)
from huburgency.inventar_hub_linker import GeoJSONLoader, ShapefileLoader

# Lon/lat anchors, each far from the others.
PT = (34.78, 32.07)        # uid 1  Point        'ביצוע'
ML = (35.20, 31.78)        # uid 2  MultiLine    'תכנון מפורט'
LN = (34.99, 32.80)        # uid 3  LineString   '?'
FAR = (34.90, 29.55)       # hub with nothing nearby


def _cell(lonlat):
    return h3.latlng_to_cell(lonlat[1], lonlat[0], 9)


def _features():
    attrs = lambda uid, name, status: {
        'uid': uid, 'proj_name': name, 'main_type': 'רכבת',
        'Proj_status': status, 'scn_year': '2040',
    }
    return gpd.GeoDataFrame(
        [
            attrs(1, 'נקודה', 'ביצוע'),
            attrs(2, 'קו מרובה', 'תכנון מפורט'),
            attrs(3, 'קו', '?'),
            attrs(4, 'פוליגון', 'ביצוע'),
        ],
        geometry=[
            Point(*PT),
            MultiLineString([[(ML[0], ML[1]), (ML[0] + .001, ML[1])],
                             [(ML[0], ML[1] + .001), (ML[0] + .001, ML[1] + .001)]]),
            LineString([(LN[0], LN[1]), (LN[0] + .001, LN[1])]),
            Polygon([(35.5, 32.0), (35.6, 32.0), (35.6, 32.1)]),
        ],
        crs='EPSG:4326',
    )


def _write_hubs(folder: Path):
    rows = [
        {'group': 1, 'x': 0, 'y': 0, 'HubNameHE': 'מרכז', 'h3_index': str([_cell(PT), _cell(ML)])},
        {'group': 2, 'x': 0, 'y': 0, 'HubNameHE': 'צפון', 'h3_index': str([_cell(LN)])},
        {'group': 3, 'x': 0, 'y': 0, 'HubNameHE': 'ריק', 'h3_index': str([_cell(FAR)])},
    ]
    pd.DataFrame(rows).to_csv(folder / 'hubs.csv', index=False, encoding='windows-1255')


def _write_weights(folder: Path, labels=('?', 'תכנון מפורט', 'ביצוע'), weights=(0, .5, 1.0)):
    pd.DataFrame({'Proj_status': labels, 'weight': weights}).to_csv(
        folder / 'status_weights.csv', index=False, encoding='utf-8-sig')


@pytest.fixture
def geojson_folder(tmp_path):
    folder = tmp_path / 'in'
    folder.mkdir()
    _features().to_file(folder / 'layer.geojson', driver='GeoJSON')
    _write_hubs(folder)
    _write_weights(folder)
    return folder


@pytest.fixture
def shapefile_folder(tmp_path):
    folder = tmp_path / 'in_shp'
    (folder / 'Inventar').mkdir(parents=True)
    gdf = _features()
    cols = ['uid']
    gdf[gdf.geom_type == 'Point'][cols + ['geometry']].to_file(folder / 'Inventar' / 'geom_point.shp')
    gdf[gdf.geom_type == 'LineString'][cols + ['geometry']].to_file(folder / 'Inventar' / 'geom_line.shp')
    gdf[gdf.geom_type == 'MultiLineString'][cols + ['geometry']].to_file(folder / 'Inventar' / 'geom_multiline.shp')
    gdf.drop(columns='geometry').to_csv(folder / 'data.csv', index=False, encoding='utf-8-sig')
    _write_hubs(folder)
    _write_weights(folder)
    return folder


def _config(inventar, tmp_path, **kw):
    inventar = Path(inventar)
    hubs_folder = inventar.parent if inventar.name == 'Inventar' else (
        inventar if inventar.is_dir() else inventar.parent)
    return ProcessingConfig(
        hubs_csv_path=hubs_folder / 'hubs.csv', inventar_directory=inventar,
        output_csv_path=tmp_path / 'out.csv', **kw)


# =============================================================================
# GeoJSON loading
# =============================================================================

def test_geojson_splits_layers_and_drops_polygons(geojson_folder):
    source = GeoJSONSource(geojson_folder / 'layer.geojson')
    assert source.layer('points')['uid'].tolist() == [1]
    assert source.layer('lines')['uid'].tolist() == [3]
    assert source.layer('multilines')['uid'].tolist() == [2]
    assert 4 not in source.attributes()['uid'].tolist()


def test_geojson_reprojects_to_wgs84(tmp_path):
    projected = _features().iloc[[0]].to_crs('EPSG:2039')
    path = tmp_path / 'itm.geojson'
    projected.to_file(path, driver='GeoJSON')
    pt = GeoJSONSource(path).layer('points').geometry.iloc[0]
    assert (pt.x, pt.y) == pytest.approx(PT, abs=1e-5)


def test_geojson_without_uid_raises(tmp_path):
    path = tmp_path / 'nouid.geojson'
    _features().drop(columns='uid').to_file(path, driver='GeoJSON')
    with pytest.raises(ValueError, match="uid"):
        GeoJSONSource(path).read()


def test_factory_picks_geojson_in_folder(geojson_folder, tmp_path):
    loaders = InventarLoaderFactory(_config(geojson_folder, tmp_path)).create_all_loaders()
    assert all(isinstance(l, GeoJSONLoader) for l in loaders.values())


def test_factory_accepts_file_path_as_inventar_directory(geojson_folder, tmp_path):
    config = _config(geojson_folder / 'layer.geojson', tmp_path)
    assert config.inventar_file == geojson_folder / 'layer.geojson'
    loaders = InventarLoaderFactory(config).create_all_loaders()
    assert loaders['points'].load()['uid'].tolist() == [1]


def test_factory_prefers_shapefiles_when_present(shapefile_folder, tmp_path):
    # A GeoJSON next to the shapefiles must not hijack a shapefile run.
    _features().to_file(shapefile_folder / 'Inventar' / 'extra.geojson', driver='GeoJSON')
    loaders = InventarLoaderFactory(_config(shapefile_folder / 'Inventar', tmp_path)).create_all_loaders()
    assert all(isinstance(l, ShapefileLoader) for l in loaders.values())


def test_factory_rejects_ambiguous_geojson(geojson_folder, tmp_path):
    _features().to_file(geojson_folder / 'second.geojson', driver='GeoJSON')
    with pytest.raises(ValueError, match="Multiple GeoJSON"):
        InventarLoaderFactory(_config(geojson_folder, tmp_path)).create_all_loaders()


def test_empty_folder_keeps_old_behaviour(tmp_path):
    empty = tmp_path / 'empty'
    empty.mkdir()
    loaders = InventarLoaderFactory(_config(empty, tmp_path)).create_all_loaders()
    assert all(len(l.load()) == 0 for l in loaders.values())


def test_linker_links_geojson_features(geojson_folder, tmp_path):
    df = InventarHubLinker(_config(geojson_folder, tmp_path, encoding='windows-1255')).process()
    by_group = {g: d for g, d in df.groupby('group')}
    assert by_group[1]['intersecting_points'].explode().dropna().tolist() == [1]
    assert by_group[1]['intersecting_multilines'].explode().dropna().tolist() == [2]
    assert by_group[2]['intersecting_lines'].explode().dropna().tolist() == [3]
    assert by_group[3][['intersecting_points', 'intersecting_lines', 'intersecting_multilines']] \
        .map(len).sum().sum() == 0


def test_shapefile_and_geojson_give_identical_links(geojson_folder, shapefile_folder, tmp_path):
    cols = ['group', 'intersecting_points', 'intersecting_lines', 'intersecting_multilines']
    from_geojson = InventarHubLinker(_config(geojson_folder, tmp_path)).process()[cols]
    from_shp = InventarHubLinker(_config(shapefile_folder / 'Inventar', tmp_path)).process()[cols]
    pd.testing.assert_frame_equal(from_geojson, from_shp)


def test_attributes_from_geojson(geojson_folder, tmp_path):
    attrs = load_inventar_attributes(_config(geojson_folder, tmp_path))
    assert {'uid', 'proj_name', 'Proj_status', 'scn_year'} <= set(attrs.columns)
    assert 'geometry' not in attrs.columns


# =============================================================================
# End-to-end workflow
# =============================================================================

def _progress(result):
    return result.progress_df.set_index('group')['status_progress_pct'].to_dict()


def test_discover_inputs_finds_files(geojson_folder):
    inputs = discover_inputs(geojson_folder)
    assert inputs.hubs_csv.name == 'hubs.csv'
    assert inputs.inventar == geojson_folder
    assert inputs.status_overrides_csv is None and inputs.project_data_csv is None


def test_discover_inputs_finds_shapefile_subfolder(shapefile_folder):
    inputs = discover_inputs(shapefile_folder)
    assert inputs.inventar == shapefile_folder / 'Inventar'
    assert inputs.project_data_csv == shapefile_folder / 'data.csv'


def test_end_to_end_geojson_without_overrides(geojson_folder, tmp_path):
    out = tmp_path / 'out'
    result = run_end_to_end(geojson_folder, out)
    # group 1: 'ביצוע'(1.0) + 'תכנון מפורט'(.5) of max 1.0 each -> 75 %
    assert _progress(result) == {1: 75.0, 2: 0.0, 3: 0.0}
    assert result.n_overridden == 0
    assert not result.joined_df['status_overridden'].any()
    for name in ('hub_progress.csv', 'hub_project_joined.csv', 'hub_status_breakdown.csv',
                 'status_zero_projects.csv', 'hubs_with_inventar_exploded.csv',
                 'status_weights_template.csv'):
        assert (out / name).exists(), name
    # zero-project hub 3 is not reported as a status-zero project
    assert result.status_zero_df['project_uid'].tolist() == [3]


def test_end_to_end_applies_overrides_when_file_exists(geojson_folder, tmp_path):
    pd.DataFrame({'uid': [2, 3, 999], 'Proj_status': ['ביצוע', 'תכנון מפורט ', 'ביצוע']}) \
        .to_csv(geojson_folder / 'status_overrides.csv', index=False, encoding='utf-8-sig')
    result = run_end_to_end(geojson_folder, tmp_path / 'out')
    assert result.n_overridden == 2          # uid 999 is unknown and ignored
    assert _progress(result) == {1: 100.0, 2: 50.0, 3: 0.0}
    joined = result.joined_df.set_index('project_uid')
    assert joined.loc[2, 'Proj_status_original'] == 'תכנון מפורט'
    assert bool(joined.loc[2, 'status_overridden']) is True
    assert bool(joined.loc[1, 'status_overridden']) is False


def test_end_to_end_overrides_file_may_use_windows_1255(geojson_folder, tmp_path):
    pd.DataFrame({'uid': [2], 'Proj_status': ['ביצוע']}) \
        .to_csv(geojson_folder / 'status_overrides.csv', index=False, encoding='windows-1255')
    assert _progress(run_end_to_end(geojson_folder, tmp_path / 'out'))[1] == 100.0


def test_end_to_end_missing_weights_writes_template(geojson_folder, tmp_path):
    (geojson_folder / 'status_weights.csv').unlink()
    out = tmp_path / 'out'
    with pytest.raises(FileNotFoundError, match="status_weights_template.csv"):
        run_end_to_end(geojson_folder, out)
    template = pd.read_csv(out / 'status_weights_template.csv', encoding='utf-8-sig')
    assert set(template['Proj_status']) == {'ביצוע', 'תכנון מפורט', '?'}
    assert template.set_index('Proj_status').loc['ביצוע', 'weight'] == pytest.approx(0.85)
    assert not (out / 'hubs_with_inventar.csv').exists()   # failed before the slow stage


def test_end_to_end_warns_on_unmapped_status(geojson_folder, tmp_path):
    _write_weights(geojson_folder, labels=('?', 'ביצוע'), weights=(0, 1.0))
    result = run_end_to_end(geojson_folder, tmp_path / 'out')
    assert result.unmapped_statuses == ['תכנון מפורט']


def test_end_to_end_shapefiles_with_data_csv(shapefile_folder, tmp_path):
    result = run_end_to_end(shapefile_folder, tmp_path / 'out')
    assert _progress(result) == {1: 75.0, 2: 0.0, 3: 0.0}


def test_end_to_end_shapefiles_without_attributes_explains(shapefile_folder, tmp_path):
    (shapefile_folder / 'data.csv').unlink()
    with pytest.raises(ValueError, match="data.csv"):
        run_end_to_end(shapefile_folder, tmp_path / 'out')


# =============================================================================
# Map / report export and notebook UI
# =============================================================================

def test_end_to_end_writes_map_and_report(geojson_folder, tmp_path):
    pd.DataFrame({'uid': [3, 999], 'Proj_status': ['ביצוע', 'ביצוע']}) \
        .to_csv(geojson_folder / 'status_overrides.csv', index=False, encoding='utf-8-sig')
    _write_weights(geojson_folder, labels=('?', 'ביצוע'), weights=(0, 1.0))   # uid 2's 'תכנון מפורט' is unmapped
    out = tmp_path / 'out'
    result = run_end_to_end(geojson_folder, out)

    report = (out / 'hub_urgency_report.html').read_text(encoding='utf-8')
    assert result.outputs['report'] == out / 'hub_urgency_report.html'
    assert 'Hub Urgency Report' in report
    assert 'Override UIDs not found' in report and '999' in report
    assert 'Statuses with no weight' in report
    assert 'Manual status overrides' in report
    assert 'hub_urgency_map.html' in report

    page = (out / 'hub_urgency_map.html').read_text(encoding='utf-8')
    for text in ('נקודה', 'קו מרובה', 'קו', 'ריק', 'no projects'):
        assert json.dumps(text)[1:-1] in page, text   # folium embeds GeoJSON with \\u escapes
    assert page.count('"type": "Feature"') == 4 + 3     # 4 hub H3 cells + 3 projects (polygon excluded)


def test_report_still_written_without_folium(geojson_folder, tmp_path, monkeypatch):
    monkeypatch.setitem(__import__('sys').modules, 'folium', None)   # make `import folium` fail
    out = tmp_path / 'out'
    result = run_end_to_end(geojson_folder, out)
    assert 'map' not in result.outputs and (out / 'hub_urgency_report.html').exists()
    assert 'Open the interactive map' not in (out / 'hub_urgency_report.html').read_text(encoding='utf-8')


def test_make_report_false_skips_html(geojson_folder, tmp_path):
    out = tmp_path / 'out'
    run_end_to_end(geojson_folder, out, make_report=False)
    assert not (out / 'hub_urgency_report.html').exists()
    assert not (out / 'hub_urgency_map.html').exists()


def test_ui_run_uses_form_values(geojson_folder, tmp_path):
    pytest.importorskip('ipywidgets')
    from huburgency.widgets import HubUrgencyUI

    ui = HubUrgencyUI(input_dir=geojson_folder, output_dir=tmp_path, show=False)
    assert ui.input_dir == geojson_folder
    assert ui.output_dir == tmp_path          # an explicit output_dir is used as given
    result = ui.run()
    assert result is not None and ui.error is None
    assert (tmp_path / 'hub_urgency_report.html').exists()
    assert ui._run.disabled is False


def test_ui_accepts_output_folder_that_does_not_exist_yet(geojson_folder, tmp_path):
    pytest.importorskip('ipywidgets')
    from huburgency.widgets import HubUrgencyUI

    ui = HubUrgencyUI(input_dir=geojson_folder, output_dir=tmp_path / 'new' / 'results', show=False)
    assert ui.output_dir == tmp_path / 'new' / 'results'
    assert ui.run() is not None
    assert (tmp_path / 'new' / 'results' / 'hub_urgency_map.html').exists()


def test_ui_reports_errors_instead_of_raising(geojson_folder, tmp_path):
    pytest.importorskip('ipywidgets')
    from huburgency.widgets import HubUrgencyUI

    (geojson_folder / 'status_weights.csv').unlink()
    ui = HubUrgencyUI(input_dir=geojson_folder, output_dir=tmp_path, show=False)
    assert ui.run() is None
    assert isinstance(ui.error, FileNotFoundError)
    assert (tmp_path / 'status_weights_template.csv').exists()
