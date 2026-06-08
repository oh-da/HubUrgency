# HubUrgency Documentation

This folder is the **complete documentation** of the HubUrgency model: what the
project is for, what data goes in, every processing step and what it does, the
analytical model behind the numbers, a full code reference, and task-focused
how-to guides.

The numbered chapters (01–05) plus the appendices read top-to-bottom as a single
narrative reference; the task guides at the end are standalone how-tos. If you
only have five minutes, read [01 — Project Overview](01_project_overview.md) and
the [Process at a glance](03_process_workflow.md#process-at-a-glance) section.

---

## How to read this documentation

| # | Chapter | What it answers |
|---|---------|-----------------|
| 1 | [Project Overview](01_project_overview.md) | What is the goal? What problem does it solve? What is the conceptual model? |
| 2 | [Inputs](02_inputs.md) | What files and data are required? What are their exact schemas? |
| 3 | [Process Workflow](03_process_workflow.md) | What are the steps, start to finish, and what happens in each? |
| 4 | [The Model & Methodology](04_model_methodology.md) | How is "progress" actually computed? What does each number mean? |
| 5 | [Outputs](05_outputs.md) | What files are produced and what does every column mean? |
| A | [Appendix A — Code Documentation](appendix_a_code_reference.md) | Reference for every module, class, and function in `src/huburgency/`. |
| B | [Appendix B — Glossary & FAQ](appendix_b_glossary.md) | Terms, encodings, CRS, and common questions. |

---

## One-paragraph summary

HubUrgency is a two-stage geospatial analytics pipeline for transit-hub
prioritization in Israel. **Stage 1** (`inventar_hub_linker.py`) takes a list of
transit hubs — each described as a set of H3 hexagonal grid cells — and finds
which planned infrastructure projects (points, lines, multilines from an
"Inventar" of shapefiles) spatially intersect each hub. **Stage 2**
(`hub_project_status_calculator.py`) joins the engineering status of each linked
project, converts statuses to numeric weights, and computes a **weighted
completion-progress score** per hub, plus breakdowns and a stalled/cancelled
("status-zero") report. The result is a ranked, evidence-based view of which hubs
are advancing and which are stuck.

---

## Task-focused guides

Alongside the narrative chapters above, these standalone how-tos cover specific
tasks:

| Guide | Use it when you want to… |
|-------|--------------------------|
| [Usage Guide](USAGE_GUIDE.md) | Run the status calculator, including status overrides, pre-exploded input, and all-hubs backfill. |
| [Spatial Linker Guide](INVENTAR_LINKER_README.md) | Link infrastructure projects to hubs (Stage 1) and understand its options. |
| [Status-Zero Guide](STATUS_ZERO_GUIDE.md) | Analyze stalled/cancelled (status = 0) projects. |

Where these guides and the source code ever differ, the chapters and Appendix A
follow the **actual behavior of the code in `src/huburgency/`**.
