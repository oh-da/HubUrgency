# 4. The Model & Methodology

This chapter explains precisely **how the numbers are computed and what they
mean**. There are two analytical models: the *spatial linking model* (which
projects belong to a hub) and the *weighted progress model* (how advanced a hub
is). A third, derived view is the *status-zero model*.

---

## 4.1 The spatial linking model

**Question:** does project *p* belong to hub *h*?

**Definition used:** project *p* belongs to hub *h* if the geometry of *p*
**intersects** any H3 hexagon belonging to *h*.

Formally, let `H(h)` be the set of hexagon polygons of hub *h* and `g(p)` the
geometry of project *p*. Then

```
linked(p, h)  ⇔  ∃ cell ∈ H(h) :  g(p) ∩ polygon(cell) ≠ ∅
```

Notes and consequences:

- **Intersection, not containment.** A line that merely touches or crosses a
  hexagon links the project — it need not be fully inside. This is deliberate:
  corridors and road segments should attach to every hub they pass through.
- **A project can link to many hubs.** If a long line crosses several hubs'
  hexagons, it is counted in each. This is intended (the project is relevant to
  each hub it touches).
- **De-duplication is per hub.** Within a hub, the same `uid` arriving from
  multiple hexagons or multiple geometry types is collapsed to a single project
  (Stage 2, step 2.1). So a hub never double-counts one project.
- **Resolution sensitivity.** The H3 resolution chosen upstream sets the
  granularity of "near". Finer cells = tighter footprints = fewer links; coarser
  cells = looser footprints = more links. The model does not choose the
  resolution; it inherits it from the hubs CSV.

**Why H3 + R-tree?** Converting hexagons to polygons and testing geometry
intersection directly would be slow at scale. The R-tree index gives a fast
bounding-box pre-filter so only a few candidate geometries get the expensive exact
intersection test. This is what keeps runtime to minutes rather than hours on
tens of thousands of cells.

---

## 4.2 The weighted progress model

**Question:** how far along are hub *h*'s projects, as one number?

### 4.2.1 Status → weight

Each engineering status `s` maps to a weight `w(s) ∈ [0, 1]` via the
status-weights table. The weight represents the **fraction of the lifecycle
completed** at that stage (e.g. detailed design ≈ 0.40, under construction ≈ 0.75,
operational = 1.00).

### 4.2.2 The hub progress formula

For hub *h* with linked projects `P(h)`:

```
                    Σ_{p ∈ P(h)}  w(status(p))
progress(h) = 100 × ───────────────────────────
                       |P(h)| × max_w
```

where `max_w = max_s w(s)` is the largest weight in the table.

In code (`StatusProgressCalculator.calculate_hub_progress`):

```
current_weighted_sum =  Σ status_weight
max_possible_sum     =  total_projects × max_weight
status_progress_pct  =  100 × current_weighted_sum / max_possible_sum
```

### 4.2.3 What the number means

- **0%** — every project is at weight 0 (not started / cancelled / unmapped).
- **100%** — every project is at the maximum weight (typically fully operational).
- **In between** — the hub's projects are, on a completion-weighted basis, that
  fraction of the way to "all done".

Because the denominator divides by `max_w`, the **absolute scale of the weights
doesn't matter** — only their ratios. A weight table of `[0.1 … 1.0]` and one of
`[1 … 10]` produce identical percentages.

When `max_w = 1.0` (the recommended convention), the formula simplifies to the
**mean project weight × 100**:

```
progress(h) = 100 × mean_{p ∈ P(h)} w(status(p))
```

### 4.2.4 Worked example

A hub has 4 projects with statuses mapping to weights `0.40, 0.75, 0.10, 1.00`,
and the table's max weight is `1.00`:

```
current_weighted_sum = 0.40 + 0.75 + 0.10 + 1.00 = 2.25
max_possible_sum     = 4 × 1.00 = 4.00
status_progress_pct  = 100 × 2.25 / 4.00 = 56.25%
```

The hub is ~56% of the way to having all its projects complete.

### 4.2.5 Properties, assumptions, and caveats

- **Unweighted by project size.** Every project counts equally; a small
  bus-stop upgrade and a metro line contribute the same. If you need size or cost
  weighting, extend `StatusProgressCalculator` (see the extensibility example in
  [Appendix A](appendix_a_code_reference.md)).
- **Monotonicity assumed.** The percentage is only intuitive if later stages have
  higher weights. Non-monotonic weights are allowed by the code but make the
  score hard to interpret.
- **Unmapped → 0.** Statuses missing from the weights table become weight 0,
  which *lowers* progress. This is conservative (unknown = not credited) and is
  why the status-zero report also catches unmapped statuses.
- **Companion metrics.** `unique_statuses` (how spread across stages the hub is)
  and the per-status `num_proj_status_X` breakdown give context the single
  percentage can hide (e.g. 50% could be "all mid-stage" or "half done, half not
  started").

---

## 4.3 The status-zero model

**Question:** which hubs are stuck?

A project is **status-zero** when its `status_weight == 0` — i.e. it maps to a
zero weight or has no mapping at all. Conceptually this captures projects that are
**not started, cancelled, on hold, or of unknown status**.

`get_status_zero_projects()` returns these hub–project rows. From them you derive a
per-hub stalled-rate:

```
status_zero_pct(h) = 100 × (status-zero projects in h) / (total projects in h)
```

### Interpretation bands

| `status_zero_pct` | Reading | Suggested action |
|-------------------|---------|------------------|
| 0% | No stalled/cancelled projects | Healthy |
| 1–25% | Low | Monitor |
| 26–50% | Moderate | Review / investigate |
| 51–75% | High | Immediate attention |
| 76–100% | Very high | Critical — full review |

### Combining progress and stalled-rate into a priority score

Progress and stalled-rate together identify hubs that most need intervention —
low progress *and* high cancellation:

```python
intervention_priority = (100 - status_progress_pct) * 0.6   # how far from done
                      +  status_zero_pct           * 0.4   # how stalled
```

(The 0.6 / 0.4 split is a reporting convention, not part of the core code — tune
it to your priorities.)

> **Code-vs-docs note.** Some older guides describe a ready-made
> `hub_status_zero_report.csv` with aggregated `status_zero_count` /
> `status_zero_pct` columns. The current code's `get_status_zero_projects()`
> returns the **project-level** zero-weight rows; the per-hub count/percentage is
> a one-line `groupby` you compute on top of it (or via the breakdown's
> `num_proj_status_0` column). See [Chapter 5](05_outputs.md).

---

## 4.4 End-to-end, in one line of math

For each hub *h*:

```
P(h)        = { p : g(p) intersects any hexagon of h }          (spatial model)
progress(h) = 100 · Σ_{p∈P(h)} w(status(p)) / (|P(h)| · max_w)   (progress model)
stalled(h)  = 100 · |{ p∈P(h) : w(status(p)) = 0 }| / |P(h)|     (status-zero model)
```

These three quantities — *what's linked*, *how advanced*, *how stuck* — are the
complete analytical output of HubUrgency.

Continue to **[5. Outputs](05_outputs.md)** for the exact files and columns.
</content>
