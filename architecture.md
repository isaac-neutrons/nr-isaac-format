# Architecture: nr-isaac-format

This document records the design decisions behind nr-isaac-format so they are not
accidentally undone. It is the reference for *why* the conversion is shaped the way it is.

## 1. What this package owns

nr-isaac-format owns **one thing: the ISAAC-schema mapping.** It turns the data-assembler's
neutral, typed records (reflectivity / sample / environment / fit) into validated **ISAAC
AI-Ready Records** (JSON) and pushes them to the ISAAC Portal. It does not fit, reduce, or
assemble data — that is the data-assembler's job.

Decision: keep this package a thin, well-tested **mapping + transport** layer. Scientific
truth lives upstream (data-assembler); ISAAC is a downstream *representation*.

## 2. The two entry points

- **`convert-ingest` (canonical).** Consumes a data-assembler ingest directory (the
  run-level store, as JSON or Parquet) and emits ISAAC records. This is the route AuRE drives
  (`data-assembler ingest-workflow` → `convert-ingest`). Fitted layers + σ, χ², and
  conditions flow straight through.
- **`convert` (manual).** Builds a record directly from a YAML **manifest** (fitted) or
  **plan** (pre-fit), re-running the assembler from raw files. Handy for ad-hoc conversions;
  not the pipeline handoff.

Other commands: `validate` (schema check), `push`/`health` (Portal API), `fetch-schema` /
`fetch-ontology` (sync the bundled schema), `migrate` (schema-only record upgrade),
`update` (full regeneration from a manifest), `plan-to-manifest` (scaffold a manifest).

## 3. The central principle: ISAAC is a representation of a run-level store

The data-assembler store is **run-level** (one `reflectivity` record per run/angle), with the
grouping recoverable from foreign keys (`sample_id`, `environment_id`). nr-isaac-format does
**not** invent grouping — it reads what the store encodes and *represents* it:

| Store (run level) | ISAAC record |
|---|---|
| one reflectivity run | one `measurement.series` |
| a state = runs sharing `(sample_id, environment_id)` | one record, N series |
| the run's `sample_id` FK | `sample.sample_id` (stable physical-sample identity) |
| runs sharing one `sample_id` across states | records cross-linked via `links[].same_sample_as` |
| a co-refinement fit over N runs | shared descriptors across the per-state records |

## 4. Multi-series and multi-state (the key behaviors)

- **Multi-series.** `IsaacWriter.to_isaac` builds one `measurement.series` per run in
  `result.reflectivities` (`writer.py`). The free-text description rides on the first series'
  `notes`. `_map_descriptors` aggregates the Q-range (`min`/`max`/summed `total_points`)
  across the runs; the fitted-model descriptors are emitted **once** (a property of the state,
  not the angle).
  - **Back-compat invariant:** a single run keeps `series_id = "reflectivity_profile"`;
    multiple runs are named `run_<run_number>` (uniquified on collision). Single-run records
    are byte-stable vs. the pre-multi-series writer.
- **Multi-state split.** `convert-ingest` loads **all** run-level records
  (`_load_ingest_records`) and groups them by `(sample_id, environment_id)`
  (`_load_states_from_ingest`) → **one ISAAC record per state**, each with its own
  environment/context, the shared sample, and the shared fit's descriptors. Single-state dirs
  yield exactly one record (unchanged). Grouping comes entirely from the store's FKs — **no
  manifest, no file-name parsing.**

Decision: a multi-state co-refinement therefore produces **N records sharing a sample**, not
one merged record. `convert-ingest` writes one file per state (named by the state's primary
run); `--result-out` reports `isaac_record` for one record or `isaac_records` (a list) for N.
An explicit `.json` `-o` target is rejected when N > 1 (can't write N records to one file).

- **Sample identity + same-sample links.** Every record carries `sample.sample_id` — the
  data-assembler's `sample_id` FK (preferred from the sample record's `id`, else the
  reflectivity's FK), the schema's stable physical-sample identity. `convert-ingest` builds all
  records first, then `_wire_same_sample_links` adds reciprocal `links[]` entries
  (`rel: same_sample_as`, `basis: same_sample_id`, `target:` the sibling's `record_id`) between
  records that share a `sample_id`. This is why records are built before any is written — the
  link target is another record's freshly minted ULID. A `distinct_sample` co-refinement carries
  a **distinct** `sample_id` per state upstream, so its records get distinct `sample.sample_id`
  and are **not** linked. `distinct_sample` is the data-assembler/AuRE identity decision; this
  package only represents the FKs it finds.

## 5. The fit → descriptors mapping

A fitted model (`reflectivity_model`, the data-assembler's first-class *fit* entity) becomes a
`reflectivity_model_fit` descriptor output: per-layer thickness/SLD/roughness carrying the
fitted σ as `uncertainty.sigma`, plus reduced χ². The writer reads the **top-level** `layers`
(the primary dataset's mirror) for back-compat; the fit's per-dataset breakdown lives in the
store, not (yet) in the ISAAC record.

## 6. Schema management

Records target the latest bundled ORNL revision (`schema/isaac_record_v1-ornl-rev*.json`,
currently rev4 / `isaac_record_version` "1.05"). `validate` and `migrate` auto-select the
latest. `migrate` applies structural record upgrades (rev1→4) without re-running the pipeline;
prefer `update` (full regeneration) when raw data is available.

## 7. Contracts not to break

- CLI surface `{convert, convert-ingest, validate}` is locked by `tests/test_cli_contract.py`
  (ndip-workflows calls `convert-ingest`; AuRE's export extra subprocesses `convert`/`validate`
  and imports `nr_isaac_format.cli:main`).
- `convert-ingest` on a single-run dir stays one record with one series — ndip-workflows
  depends on it.
- The writer must accept the data-assembler's `AssemblyResult` shape; it reads
  `reflectivities` (all runs) defensively and falls back to the single `reflectivity` record.

## 8. Dependency on data-assembler

Pinned via `pyproject.toml` (`data-assembler @ git+…`). The ISAAC mapping is coupled to the
assembler's record shapes (reflectivity FKs, the fit's `layers`/`chi_squared`). Bump the pin
deliberately and in lockstep with assembler record-shape changes; keep single-run
`convert-ingest` output stable across bumps.
