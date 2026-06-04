# 1. Project Overview

## 1.1 The goal

HubUrgency answers one practical planning question:

> **"For each transit hub in our network, how far along are the infrastructure
> projects that touch it — and which hubs are stuck?"**

Transit authorities plan dozens or hundreds of infrastructure projects (rail
lines, light-rail/BRT corridors, stations, terminals, road works). Each project
sits somewhere on a development pipeline, from "planning initiated" to "fully
operational". Decision-makers need to know, **per hub**, whether the projects in
that hub's footprint are progressing or stalling, so they can prioritize
attention, money, and intervention.

HubUrgency turns raw geospatial project data into a small set of **per-hub
metrics** that make this prioritization possible:

- A **weighted progress percentage** (0–100%) summarizing how advanced a hub's
  projects are.
- A **status breakdown** (how many projects sit at each status level).
- A **status-zero report** highlighting hubs with cancelled / not-started /
  stalled projects.

## 1.2 The core idea (conceptual model)

The model rests on three ideas:

1. **A hub is an area, represented as a set of H3 hexagons.**
   Rather than treating a hub as a single point, each hub (a "group") is
   described by one or more [H3](https://h3geo.org/) hexagonal grid cells that
   tile its footprint. H3 is Uber's hierarchical hexagonal spatial index; it lets
   us do fast, consistent "is this thing inside this area?" tests.

2. **A project belongs to a hub if it spatially intersects the hub's hexagons.**
   Projects are geometries — points, lines, or multilines. If any part of a
   project geometry intersects any of a hub's hexagons, that project is *linked*
   to the hub. This is the job of **Stage 1** (the "Inventar Hub Linker").

3. **Progress is a weighted average of project statuses.**
   Every project has an engineering status (e.g. "detailed design", "under
   construction"). Each status maps to a **weight** between 0.0 and 1.0
   representing how complete that stage is. A hub's progress is the sum of its
   projects' weights divided by the maximum possible sum — i.e., a normalized,
   weighted completion score. This is the job of **Stage 2** (the "Status
   Calculator").

```
        ┌─────────────────────────────────────────────────────────────┐
        │                     CONCEPTUAL MODEL                          │
        │                                                               │
        │   HUB  =  a "group"  =  set of H3 hexagons                    │
        │                                                               │
        │   ┌───────┐ ┌───────┐                                         │
        │   │ hex 1 │ │ hex 2 │   ← a hub's footprint                   │
        │   └───────┘ └───────┘                                         │
        │       ▲         ▲                                             │
        │       │ intersects                                            │
        │   ╱╲  │   ●      │  ────  projects (point / line / multiline) │
        │  ╱  ╲ │          │        each carries a STATUS               │
        │                                                               │
        │   PROGRESS(hub) = Σ weight(status) / (n_projects × max_weight)│
        └─────────────────────────────────────────────────────────────┘
```

## 1.3 What the system is (and is not)

**It is:**
- A **batch analytics pipeline**, run on prepared input files, producing CSV
  outputs.
- A **two-stage** system: spatial linking, then status scoring. The stages are
  independent and can be run separately.
- Built on **SOLID-structured Python** — small single-responsibility classes,
  factories and protocols for extensibility, and a facade/orchestrator per stage.

**It is not:**
- A live service or API. There is no database or web server; it reads files and
  writes files.
- A geometry editor. It consumes pre-built shapefiles and a pre-built hub list
  (the hubs with their H3 cells come from an upstream "Transit Hub Processing
  Pipeline" that is outside this repository).

## 1.4 Where this fits in the larger pipeline

HubUrgency is the tail end of a longer hub-prioritization effort. The upstream
stages (not in this repo) produce the hub list with H3 indices:

```
Part 1: H3 Processing  →  Part 2: Demand  →  Part 3: Influence Area
                                                      │
                                                      ▼
                              ┌───────────────────────────────────────┐
                              │              HubUrgency                │
                              │                                        │
                              │  Stage 1: Inventar Hub Linker          │
                              │           (spatial linking)            │
                              │                  │                     │
                              │                  ▼                     │
                              │  Stage 2: Hub Project Status Calculator│
                              │           (weighted progress)          │
                              └───────────────────────────────────────┘
                                                      │
                                                      ▼
                                     Hub prioritization / reporting
```

Only **Stage 1** and **Stage 2** are implemented in this repository (`src/`). The
upstream parts are assumed to have already produced the hubs CSV that Stage 1
consumes.

## 1.5 Key technologies

| Technology | Role in the model |
|------------|-------------------|
| **H3** (Uber hexagonal index) | Represents each hub as a set of hexagonal cells; converts cells to polygons for intersection. |
| **GeoPandas / Shapely** | Loads project shapefiles and performs the geometric intersection tests. |
| **R-tree spatial index** (`GeoDataFrame.sindex`) | Makes intersection fast: a bounding-box pre-filter before precise checks. |
| **pandas / numpy** | All tabular joins, aggregation, and the weighted-progress math. |
| **windows-1255 encoding** | Default file encoding so Hebrew hub names round-trip correctly. |

## 1.6 Primary use cases

- **Hub prioritization** — rank hubs by progress to focus effort.
- **Bottleneck detection** — find hubs with many projects but low progress.
- **Risk / cancellation analysis** — find hubs concentrated with status-zero
  (stalled/cancelled) projects.
- **Investment coverage** — see which hubs are touched by planned infrastructure
  at all.

Continue to **[2. Inputs](02_inputs.md)** to see exactly what data the pipeline
consumes.
</content>
