"""
Map and Report Export
=====================

Turns a ``WorkflowResult`` into two shareable HTML files:

    hub_urgency_map.html      interactive Leaflet map: hub H3 cells coloured by
                              status progress, project geometries coloured by
                              status weight (needs ``folium``)
    hub_urgency_report.html   single self-contained page: key figures, warnings,
                              status weights and counts, overrides, progress
                              histogram, top / bottom hubs (no extra packages)

Usage::

    from huburgency.report import export_report
    export_report(result, 'out/map.html', 'out/report.html')
"""

from datetime import datetime
from html import escape
from pathlib import Path
from typing import Dict, List, Optional
import logging

import geopandas as gpd
import numpy as np
import pandas as pd

from .inventar_hub_linker import H3PolygonConverter, InventarLoaderFactory

logger = logging.getLogger(__name__)

NO_PROJECTS_COLOR = '#c8c8c8'
PROGRESS_COLORS = ['#440154', '#3b528b', '#21908d', '#5dc863', '#fde725']  # viridis
_STATUS_COL_PREFIX = 'num_proj_status_'


# =============================================================================
# Data preparation
# =============================================================================

def _group_col(result) -> str:
    return getattr(result, 'group_col', 'group')


def hub_table(result) -> pd.DataFrame:
    """Per-hub progress with a readable ``status_mix`` string (e.g. "ביצוע: 2, תכנון מפורט: 1")."""
    group = _group_col(result)
    breakdown = result.status_breakdown_df
    status_cols = [c for c in breakdown.columns if c.startswith(_STATUS_COL_PREFIX)]

    def _mix(row) -> str:
        parts = [f"{c[len(_STATUS_COL_PREFIX):]}: {int(row[c])}" for c in status_cols if row[c] > 0]
        return ', '.join(parts)

    mix = breakdown[[group]].copy()
    mix['status_mix'] = breakdown.apply(_mix, axis=1)
    hubs = result.progress_df.merge(mix, on=group, how='left')
    hubs['status_mix'] = hubs['status_mix'].fillna('')
    return hubs


def project_layer(result) -> gpd.GeoDataFrame:
    """Project geometries (all layers) joined to their final status and weight."""
    loaders = InventarLoaderFactory(result.config).create_all_loaders()
    frames = [l.load()[['uid', 'geometry']] for l in loaders.values()]
    frames = [f for f in frames if len(f)]
    if not frames:
        return gpd.GeoDataFrame({'uid': [], 'geometry': []}, geometry='geometry', crs='EPSG:4326')
    gdf = pd.concat(frames, ignore_index=True)
    gdf = gpd.GeoDataFrame(gdf, geometry='geometry', crs='EPSG:4326')

    weights = dict(zip(result.weights_df['Proj_status'], result.weights_df['weight']))
    max_weight = max(weights.values()) or 1.0
    projects = result.project_df.copy()
    projects['weight'] = projects['Proj_status'].map(weights).fillna(0.0)
    projects['weight_pct'] = (100 * projects['weight'] / max_weight).clip(0, 100)

    gdf['uid'] = pd.to_numeric(gdf['uid'], errors='coerce')
    keep = ['uid', 'proj_name', 'Proj_status', 'Proj_status_original', 'status_overridden',
            'weight_pct']
    return gdf.merge(projects[keep], on='uid', how='left')


# =============================================================================
# Map
# =============================================================================

def build_map(result, path):
    """Write the interactive map to ``path`` and return it."""
    import folium
    from branca.colormap import LinearColormap

    group = _group_col(result)
    cmap = LinearColormap(PROGRESS_COLORS, vmin=0, vmax=100,
                          caption='Status progress (%)')

    # --- hubs: one polygon per H3 cell ---
    hubs = hub_table(result).set_index(group)
    cells = result.linker_outputs['base'][[group, 'h3_index']].dropna().drop_duplicates()
    cells = cells.assign(geometry=H3PolygonConverter.convert_series(cells['h3_index']))
    cells = cells[cells['geometry'].notna()]
    info = hubs.reindex(cells[group])
    cells['hub'] = info.get('HubNameHE', pd.Series(index=info.index, dtype=object)).fillna('').values
    cells['progress'] = info['status_progress_pct'].values
    cells['n_projects'] = info['total_projects'].fillna(0).astype(int).values
    cells['status_mix'] = info['status_mix'].fillna('').values
    cells['color'] = [
        cmap(p) if n > 0 else NO_PROJECTS_COLOR
        for p, n in zip(cells['progress'].fillna(0), cells['n_projects'])
    ]
    cells['progress_txt'] = [f"{p:.1f}%" if n > 0 else 'no projects'
                             for p, n in zip(cells['progress'].fillna(0), cells['n_projects'])]
    hex_gdf = gpd.GeoDataFrame(
        cells[[group, 'hub', 'progress_txt', 'n_projects', 'status_mix', 'color', 'geometry']],
        geometry='geometry', crs='EPSG:4326',
    )

    projects = project_layer(result)
    bounds_source = pd.concat([hex_gdf.geometry, projects.geometry]) if len(projects) else hex_gdf.geometry
    minx, miny, maxx, maxy = gpd.GeoSeries(bounds_source, crs='EPSG:4326').total_bounds

    fmap = folium.Map(tiles=None, control_scale=True)
    folium.TileLayer('OpenStreetMap', name='Basemap', control=False).add_to(fmap)
    fmap.fit_bounds([[miny, minx], [maxy, maxx]])

    folium.GeoJson(
        hex_gdf,
        name='Hubs (colour = progress %; grey = no projects)',
        style_function=lambda f: {
            'fillColor': f['properties']['color'], 'color': '#555555',
            'weight': 0.6, 'fillOpacity': 0.65,
        },
        tooltip=folium.GeoJsonTooltip(
            fields=[group, 'hub', 'progress_txt', 'n_projects', 'status_mix'],
            aliases=['Hub', 'Name', 'Progress', 'Projects', 'By status'],
        ),
    ).add_to(fmap)

    if len(projects):
        projects = projects.copy()
        projects['color'] = [cmap(p) if pd.notna(p) else NO_PROJECTS_COLOR
                             for p in projects['weight_pct']]
        projects['status_now'] = projects['Proj_status'].fillna('')
        projects['status_orig'] = [
            f"{o} → {n}" if ov is True or ov == True else '' for o, n, ov  # noqa: E712
            in zip(projects['Proj_status_original'], projects['Proj_status'], projects['status_overridden'])
        ]
        projects['proj_name'] = projects['proj_name'].fillna('')
        proj_gdf = gpd.GeoDataFrame(
            projects[['uid', 'proj_name', 'status_now', 'status_orig', 'color', 'geometry']],
            geometry='geometry', crs='EPSG:4326',
        )
        proj_gdf['uid'] = proj_gdf['uid'].astype('Int64').astype(str)
        folium.GeoJson(
            proj_gdf,
            name='Projects (colour = status weight, % of max)',
            style_function=lambda f: {'color': f['properties']['color'], 'weight': 4, 'opacity': 0.95},
            marker=folium.CircleMarker(radius=5, weight=1.5, fill=True, fill_opacity=0.95),
            tooltip=folium.GeoJsonTooltip(
                fields=['uid', 'proj_name', 'status_now', 'status_orig'],
                aliases=['UID', 'Project', 'Status', 'Overridden'],
            ),
        ).add_to(fmap)

    cmap.add_to(fmap)
    folium.LayerControl(collapsed=False).add_to(fmap)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fmap.save(str(path))
    return path


# =============================================================================
# Report
# =============================================================================

_CSS = """
:root{--bg:#fff;--fg:#1d2430;--muted:#5d6675;--card:#f4f6f9;--line:#d9dee6;--accent:#21908d;--warn:#b45309;--warn-bg:#fef3c7}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#12161c;--fg:#e6e9ee;--muted:#9aa4b2;--card:#1b212b;--line:#2d3644;--accent:#4cc2bf;--warn:#fbbf24;--warn-bg:#3a2e0b}}
:root[data-theme="dark"]{--bg:#12161c;--fg:#e6e9ee;--muted:#9aa4b2;--card:#1b212b;--line:#2d3644;--accent:#4cc2bf;--warn:#fbbf24;--warn-bg:#3a2e0b}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,"Segoe UI",Arial,sans-serif}
main{max-width:980px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:1.6rem;margin:0 0 4px}h2{font-size:1.15rem;margin:32px 0 10px}
.sub{color:var(--muted);margin:0 0 20px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px}
.kpi{background:var(--card);border-radius:8px;padding:12px 14px}.kpi b{display:block;font-size:1.5rem}.kpi span{color:var(--muted);font-size:.85rem}
.warn{background:var(--warn-bg);color:var(--warn);border-radius:8px;padding:10px 14px;margin:8px 0}
table{border-collapse:collapse;width:100%;margin:6px 0}th,td{text-align:left;padding:6px 10px;border-bottom:1px solid var(--line)}
th{color:var(--muted);font-weight:600;font-size:.85rem}td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.tables{display:grid;grid-template-columns:repeat(auto-fit,minmax(420px,1fr));gap:20px}
svg text{fill:var(--muted);font-size:11px}svg rect{fill:var(--accent)}
code{background:var(--card);padding:1px 5px;border-radius:4px}
@media print{.tables{grid-template-columns:1fr}}
"""


def _fmt(n) -> str:
    return f"{int(n):,}"


def _table(headers: List[str], rows: List[List[str]], num_cols=()) -> str:
    head = ''.join(f'<th class="num">{escape(h)}</th>' if i in num_cols else f'<th>{escape(h)}</th>'
                   for i, h in enumerate(headers))
    body = ''.join(
        '<tr>' + ''.join(
            f'<td class="num">{escape(str(c))}</td>' if i in num_cols
            else f'<td dir="auto">{escape(str(c))}</td>' for i, c in enumerate(r)) + '</tr>'
        for r in rows)
    return f'<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def _histogram_svg(values: pd.Series, bins: int = 10) -> str:
    counts, edges = np.histogram(values, bins=bins, range=(0, 100))
    w, h, pad_l, pad_b, top = 560, 190, 34, 26, 12
    bar_w = (w - pad_l) / bins
    max_c = max(int(counts.max()), 1)
    parts = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Histogram of hub status progress" '
             f'width="100%" style="max-width:{w}px">']
    for i, c in enumerate(counts):
        bh = (h - pad_b - top) * c / max_c
        x = pad_l + i * bar_w
        parts.append(f'<rect x="{x + 1:.1f}" y="{h - pad_b - bh:.1f}" width="{bar_w - 2:.1f}" '
                     f'height="{bh:.1f}" rx="2"><title>{int(edges[i])}–{int(edges[i + 1])}%: {int(c)} hubs</title></rect>')
        if c:
            parts.append(f'<text x="{x + bar_w / 2:.1f}" y="{h - pad_b - bh - 3:.1f}" text-anchor="middle">{int(c)}</text>')
        parts.append(f'<text x="{x:.1f}" y="{h - 8}" text-anchor="middle">{int(edges[i])}</text>')
    parts.append(f'<text x="{w - 2}" y="{h - 8}" text-anchor="end">100%</text>')
    parts.append('</svg>')
    return ''.join(parts)


def build_report(result, path, map_file: Optional[Path] = None):
    """Write the self-contained HTML report to ``path`` and return it."""
    group = _group_col(result)
    hubs = hub_table(result)
    with_projects = hubs[hubs['total_projects'] > 0]
    projects = result.project_df
    weights = result.weights_df
    weight_of = dict(zip(weights['Proj_status'], weights['weight']))
    linked = result.joined_df['project_uid'].dropna().nunique()
    zero_weight = int((projects['Proj_status'].map(weight_of).fillna(0) == 0).sum())

    kpis = [
        (_fmt(len(hubs)), 'hubs'),
        (_fmt(len(with_projects)), 'hubs with projects'),
        (_fmt(len(projects)), 'projects in inventar'),
        (_fmt(linked), 'projects linked to a hub'),
        (f"{with_projects['status_progress_pct'].mean():.1f}%" if len(with_projects) else '–',
         'mean progress (hubs with projects)'),
        (f"{with_projects['status_progress_pct'].median():.1f}%" if len(with_projects) else '–',
         'median progress'),
        (_fmt(zero_weight), 'projects with weight 0'),
        (_fmt(result.n_overridden), 'statuses overridden'),
    ]

    warnings = []
    if result.unmapped_statuses:
        warnings.append('Statuses with no weight (counted as 0): '
                        + ', '.join(result.unmapped_statuses))
    if result.unknown_override_uids:
        warnings.append('Override UIDs not found in the project data (ignored): '
                        + ', '.join(map(str, result.unknown_override_uids)))
    n_empty = int((hubs['total_projects'] == 0).sum())
    if n_empty:
        warnings.append(f"{n_empty} hub(s) have no linked project (progress 0%, shown grey on the map).")

    counts = projects['Proj_status'].value_counts()
    status_rows = []
    for _, r in weights.iterrows():
        status_rows.append([r['Proj_status'], f"{r['weight']:g}", _fmt(counts.get(r['Proj_status'], 0))])
    for label in result.unmapped_statuses:
        status_rows.append([label, 'missing', _fmt(counts.get(label, 0))])

    overrides_html = ''
    if result.n_overridden:
        changed = projects[projects['status_overridden']]
        rows = [[int(r['uid']), r['proj_name'], r['Proj_status_original'], r['Proj_status']]
                for _, r in changed.iterrows()]
        overrides_html = ('<h2>Manual status overrides</h2>'
                          + _table(['UID', 'Project', 'Original status', 'New status'], rows))

    def hub_rows(df):
        return [[r[group], r.get('HubNameHE', ''), f"{r['status_progress_pct']:.1f}%",
                 int(r['total_projects'])] for _, r in df.iterrows()]

    hub_headers = ['Hub', 'Name', 'Progress', 'Projects']
    ranked = with_projects.sort_values(['status_progress_pct', group], ascending=[False, True])
    top = _table(hub_headers, hub_rows(ranked.head(15)), num_cols=(2, 3))
    bottom = _table(hub_headers, hub_rows(ranked.tail(15).iloc[::-1]), num_cols=(2, 3))

    map_link = (f'<p><a href="{escape(Path(map_file).name)}">Open the interactive map</a> '
                f'(<code>{escape(Path(map_file).name)}</code>, same folder).</p>') if map_file else ''
    sources = [result.inputs.hubs_csv.name, result.inputs.inventar.name,
               result.inputs.status_weights_csv.name]
    if result.inputs.status_overrides_csv is not None:
        sources.append(result.inputs.status_overrides_csv.name)
    else:
        sources.append('(no status overrides file)')

    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Hub Urgency Report</title><style>{_CSS}</style></head><body><main>
<h1>Hub Urgency Report</h1>
<p class="sub">Generated {datetime.now():%Y-%m-%d %H:%M} · inputs: {escape(' · '.join(sources))}</p>
{map_link}
<div class="kpis">{''.join(f'<div class="kpi"><b>{escape(v)}</b><span>{escape(k)}</span></div>' for v, k in kpis)}</div>
{''.join(f'<div class="warn">⚠ {escape(w)}</div>' for w in warnings)}
<h2>Hub status progress</h2>
{_histogram_svg(with_projects['status_progress_pct']) if len(with_projects) else '<p>No hub has a linked project.</p>'}
<p class="sub">Number of hubs (with at least one project) per 10-point progress band.</p>
<h2>Status weights and project counts</h2>
{_table(['Status', 'Weight', 'Projects'], status_rows, num_cols=(1, 2))}
{overrides_html}
<div class="tables"><div><h2>Highest progress</h2>{top}</div><div><h2>Lowest progress</h2>{bottom}</div></div>
</main></body></html>"""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding='utf-8')
    return path


def export_report(result, map_path, report_path) -> Dict[str, Path]:
    """
    Write the report and the map; returns ``{'report': ..., 'map': ...}``.

    Without ``folium`` the map is skipped (with a warning) and the report is
    still written.
    """
    outputs: Dict[str, Path] = {}
    map_file = None
    try:
        map_file = build_map(result, map_path)
        outputs['map'] = map_file
    except ImportError as exc:
        logger.warning(f"Map skipped ({exc}). Install with: pip install folium")
    outputs['report'] = build_report(result, report_path, map_file=map_file)
    return outputs
