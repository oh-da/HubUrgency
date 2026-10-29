"""
Notebook UI
===========

Folder pickers and a Run button for the end-to-end workflow, for use in
Jupyter / Colab::

    from huburgency.widgets import launch_ui
    ui = launch_ui()          # shows the form
    ...
    ui.result                 # WorkflowResult after Run was pressed

Needs ``ipywidgets``; ``ipyfilechooser`` adds real folder browsing (without it
the folders are typed into text boxes). Note that pickers browse the machine
the notebook kernel runs on (in Colab: the Colab / mounted Drive file system).
"""

from html import escape
from pathlib import Path
from typing import Optional

from .workflow import WorkflowResult, run_end_to_end

DEFAULT_OUTPUT_SUBFOLDER = 'hub_urgency_output'


class HubUrgencyUI:
    """Input/output folder form that runs ``run_end_to_end`` on a button press."""

    def __init__(self, input_dir=None, output_dir=None, show: bool = True):
        try:
            import ipywidgets as w
        except ImportError as exc:  # pragma: no cover - message only
            raise ImportError("The notebook UI needs ipywidgets: pip install ipywidgets") from exc
        self._w = w
        self.result: Optional[WorkflowResult] = None
        self.error: Optional[Exception] = None

        start_in, _ = self._existing_parent(input_dir or Path.cwd())
        # A not-yet-created output folder: browse from its nearest existing parent and
        # prefill the missing part as the sub-folder.
        start_out, missing = self._existing_parent(output_dir or Path.cwd())
        sub_default = missing or (DEFAULT_OUTPUT_SUBFOLDER if output_dir is None else '')

        try:
            from ipyfilechooser import FileChooser
        except ImportError:
            FileChooser = None
        self._choosers = FileChooser is not None

        if self._choosers:
            self._in = FileChooser(start_in, title='<b>Input folder</b>', show_only_dirs=True,
                                   select_default=True)
            self._out = FileChooser(start_out, title='<b>Output folder</b> (existing folder)',
                                    show_only_dirs=True, select_default=True)
            self._subfolder = w.Text(value=sub_default, description='Sub-folder:',
                                     placeholder='created inside the output folder; empty = use it directly',
                                     layout=w.Layout(width='600px'))
        else:
            self._in = w.Text(value=start_in, description='Input folder:',
                              layout=w.Layout(width='700px'))
            self._out = w.Text(value=start_out, description='Output folder:',
                               layout=w.Layout(width='700px'))
            self._subfolder = None

        # Advanced: file names relative to the input folder.
        self._hubs = w.Text(value='', description='Hubs CSV:', placeholder='auto-detect')
        self._inventar = w.Text(value='', description='Inventar:', placeholder='auto-detect')
        self._weights = w.Text(value='status_weights.csv', description='Weights:')
        self._overrides = w.Text(value='status_overrides.csv', description='Overrides:')
        self._project_data = w.Text(value='data.csv', description='Project data:')
        self._hub_selection = w.Text(value='hub_selection.csv', description='Hub list:',
                                     placeholder='optional: CSV of hub ids -> selected_hubs_report.xlsx')
        self._threshold = w.BoundedFloatText(value=50.0, min=0, max=100, step=1,
                                             description='Urgent from %:')
        self._encoding = w.Dropdown(options=['windows-1255', 'utf-8-sig'], value='windows-1255',
                                    description='Encoding:')
        self._link_only = w.Checkbox(
            value=False, indent=False,
            description='Link only: stop after project_hub_links.csv + status_overrides_template.csv '
                        '(no scoring, no weights file needed)')
        self._report = w.Checkbox(value=True, description='Write map + report (HTML)', indent=False)
        self._preview_map = w.Checkbox(value=False, description='Preview the map inside the notebook '
                                       '(makes the notebook file larger)', indent=False)
        advanced = w.VBox([self._hubs, self._inventar, self._weights, self._overrides,
                           self._project_data, self._hub_selection, self._threshold,
                           self._encoding, self._report, self._preview_map])
        accordion = w.Accordion(children=[advanced], selected_index=None)
        accordion.set_title(0, 'Advanced (file names, encoding, report)')

        self._run = w.Button(description='Run', button_style='primary', icon='play',
                             tooltip='Run the whole pipeline')
        self._run.on_click(self.run)
        self.out = w.Output()

        header = w.HTML('<h3>Hub Urgency — end-to-end run</h3>'
                        '<p>Pick the folders and press <b>Run</b>. The overrides and project-data files '
                        'are optional; a missing overrides file means statuses stay as in the inventar.</p>')
        parts = [header, self._in, self._out]
        if self._subfolder is not None:
            parts.append(self._subfolder)
        parts += [self._link_only, accordion, self._run, self.out]
        self.widget = w.VBox(parts)
        if show:
            from IPython.display import display
            display(self.widget)

    @staticmethod
    def _existing_parent(path):
        """(nearest existing directory at or above ``path``, the missing remainder)."""
        path = Path(path).expanduser()
        existing = path
        while not existing.is_dir() and existing != existing.parent:
            existing = existing.parent
        remainder = path.relative_to(existing).as_posix() if existing != path else ''
        return str(existing), remainder

    # ------------------------------------------------------------------ values
    @staticmethod
    def _path(widget) -> str:
        """Selected folder of a FileChooser, or the text of a Text box."""
        if hasattr(widget, 'selected_path'):
            return str(widget.selected_path or widget.default_path)
        return str(widget.value)

    @property
    def input_dir(self) -> Path:
        return Path(self._path(self._in))

    @property
    def output_dir(self) -> Path:
        base = Path(self._path(self._out))
        sub = self._subfolder.value.strip() if self._subfolder is not None else ''
        return base / sub if sub else base

    # --------------------------------------------------------------------- run
    def run(self, _button=None) -> Optional[WorkflowResult]:
        """Run the pipeline with the current form values (also callable directly)."""
        from IPython.display import HTML, display

        self.out.clear_output(wait=True)
        self._run.disabled = True
        self.result, self.error = None, None
        try:
            with self.out:
                try:
                    self.result = run_end_to_end(
                        self.input_dir, self.output_dir,
                        hubs_csv=self._hubs.value.strip() or None,
                        inventar=self._inventar.value.strip() or None,
                        status_weights_csv=self._weights.value.strip() or 'status_weights.csv',
                        status_overrides_csv=self._overrides.value.strip() or 'status_overrides.csv',
                        project_data_csv=self._project_data.value.strip() or 'data.csv',
                        encoding=self._encoding.value,
                        make_report=self._report.value,
                        link_only=self._link_only.value,
                        hub_selection_csv=self._hub_selection.value.strip() or 'hub_selection.csv',
                        urgent_threshold=self._threshold.value,
                    )
                except Exception as exc:  # shown in the form instead of a traceback wall
                    self.error = exc
                    print(f"✗ {type(exc).__name__}: {exc}")
                    return None
                display(HTML(self.summary_html(self.result)))
                report = self.result.outputs.get('report')
                if report is not None:
                    display(HTML('<h4>Report</h4>'))
                    display(HTML(self._iframe(report.read_text(encoding='utf-8'), 900)))
                if self._preview_map.value and 'map' in self.result.outputs:
                    display(HTML('<h4>Map</h4>'))
                    display(HTML(self._iframe(self.result.outputs['map'].read_text(encoding='utf-8'), 650)))
        finally:
            self._run.disabled = False
        return self.result

    @staticmethod
    def _iframe(page_html: str, height: int) -> str:
        return (f'<iframe srcdoc="{escape(page_html, quote=True)}" width="100%" height="{height}" '
                'style="border:1px solid #ccc"></iframe>')

    @staticmethod
    def summary_html(result: WorkflowResult) -> str:
        files = ''.join(f"<li>{escape(k)}: <code>{escape(str(v))}</code></li>"
                        for k, v in result.outputs.items())
        if result.progress_df is None:  # link_only run
            return (f"<b>✓ Linking done</b> (scoring skipped): {result.links_df['uid'].nunique():,} projects in "
                    f"{len(result.links_df):,} project-hub rows. Edit <code>status_overrides_template.csv</code>, "
                    f"save it as <code>status_overrides.csv</code> in the input folder and run again."
                    f"<details><summary>Output files</summary><ul>{files}</ul></details>")
        progress = result.progress_df
        lines = [
            f"<b>✓ Done.</b> {len(progress):,} hubs "
            f"({int((progress['total_projects'] > 0).sum()):,} with projects), "
            f"{len(result.project_df):,} projects, {result.n_overridden:,} statuses overridden.",
        ]
        if result.unmapped_statuses:
            lines.append(f"⚠ Statuses with no weight (counted as 0): {escape(', '.join(result.unmapped_statuses))}")
        if result.unknown_override_uids:
            lines.append(f"⚠ Override UIDs not in the project data (ignored): "
                         f"{', '.join(map(str, result.unknown_override_uids))}")
        return '<br>'.join(lines) + f'<details><summary>Output files</summary><ul>{files}</ul></details>'


def launch_ui(input_dir=None, output_dir=None) -> HubUrgencyUI:
    """Show the form and return it; ``ui.result`` holds the result after Run."""
    return HubUrgencyUI(input_dir, output_dir, show=True)
