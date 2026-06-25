# NR-ISAAC Format Writer

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: BSD-3-Clause](https://img.shields.io/badge/License-BSD--3--Clause-blue.svg)](https://opensource.org/licenses/BSD-3-Clause)

CLI for converting neutron reflectometry data from [data-assembler](https://github.com/isaac-neutrons/data-assembler) into [ISAAC AI-Ready Record](https://github.com/dimosthenisSLAC/isaac-ai-ready-record) format, with commands for schema validation and pushing records to the ISAAC Portal API.

## Overview

This tool owns the **ISAAC-schema mapping**: it turns the data-assembler's neutral typed records (reflectivity, sample, environment, fitted model with σ/χ²/conditions) into validated ISAAC AI-Ready Records, and pushes them to the Portal.

Two entry points:

- **`convert-ingest` (canonical).** Consumes a data-assembler ingest directory. In the standard pipeline the assembler pulls everything from a fit run directory (`data-assembler ingest-workflow <run>`), so fitted layers + uncertainties, χ², and experimental conditions all reach the record automatically. This is the route the AuRE workflow uses.
- **`convert` (manual/standalone).** Builds a record directly from a YAML **manifest** (fitted result) or **plan** (pre-fit), re-running the assembler from raw files. Handy for ad-hoc conversions; the manifest is no longer the pipeline handoff.

## Installation

```bash
pip install -e .
```

This installs the `nr-isaac-format` CLI and pulls in all dependencies, including [data-assembler](https://github.com/isaac-neutrons/data-assembler).

## Quick Start

### Canonical: from a fit run directory

The data-assembler pulls everything (data, fitted model with σ, χ², conditions) from a standard fit run directory; this tool maps the resulting records to ISAAC:

```bash
data-assembler ingest-workflow ./workflow/230539 -o ./ingest --json
nr-isaac-format convert-ingest ./ingest -o ./ingest/isaac_record.json
nr-isaac-format validate ./ingest/isaac_record_230539.json
```

This is the route the AuRE workflow drives automatically — no manifest involved.

### Manual: from a manifest or plan

For ad-hoc conversions you can build a record directly from a YAML manifest (fitted) or plan (pre-fit). This re-runs the assembler from raw files.

### 1. Create a manifest

```yaml
title: "IPTS-34347 Cu/THF non-aqueous experiment"

sample:
  description: "Cu in THF on Si"
  model: /path/to/model.json
  model_dataset_index: 1

output: ./output

measurements:
  - name: "Steady-state OCV"
    reduced: ./REFL_218386_reduced_data.txt
    raw: /SNS/REF_L/IPTS-34347/nexus/REF_L_218386.nxs.h5
    parquet: ./parquet/
    model: ./model.json
    model_dataset_index: 1
    environment: "operando"
    context: "Electrochemical cell, THF electrolyte, steady-state OCV"

  - name: "Final OCV"
    reduced: ./REFL_218393_combined_data_auto.txt
    raw: /SNS/REF_L/IPTS-34347/nexus/REF_L_218393.nxs.h5
    model: ./model.json
    model_dataset_index: 2
    environment: "operando"
    context: "Electrochemical cell, THF electrolyte, final OCV"
```

### 2. Convert

```bash
nr-isaac-format convert experiment.yaml
```

Output:

```
Converting: IPTS-34347 Cu/THF non-aqueous experiment
  Output: ./output
  Measurements: 2

[1/2] Steady-state OCV
  Sample: Cu in THF on Si (40e82482...)
  Reflectivity: run 218386, 248 Q points
  Wrote: output/isaac_record_218386.json

[2/2] Final OCV
  Sample: 40e82482... (reused)
  Reflectivity: run 218393, 732 Q points
  Wrote: output/isaac_record_218393.json
```

### 3. Validate

```bash
nr-isaac-format validate output/isaac_record_218386.json
# ✓ Valid ISAAC record: output/isaac_record_218386.json
```

### 4. Push to ISAAC Portal

```bash
# Set credentials (or use --url / --token flags)
cp .env.example .env
# Edit .env with your ISAAC_KEY

# Push all records in a directory
nr-isaac-format push output/

# Validate against the remote API without persisting
nr-isaac-format push output/ --validate-only
```

## CLI Reference

### `nr-isaac-format convert-ingest` (canonical)

Map a data-assembler ingest directory (the `reflectivity`/`sample`/`environment`/`reflectivity_model` records, as Parquet or JSON) to a single ISAAC record. This is the canonical route — fitted layers + σ, χ², and structured conditions flow straight through from the assembler.

```bash
nr-isaac-format convert-ingest [OPTIONS] INGEST_DIR
```

| Option | Description |
|--------|-------------|
| `-o, --output PATH` | Output file or directory (defaults to the ingest dir) |
| `--context TEXT` | Free-text measurement notes (→ `measurement.series[].notes`) |
| `--result-out FILE` | Write a neutral `ndip-tool-result/1` manifest describing the conversion |
| `--compact` / `--dry-run` | Compact JSON / assemble without writing |

### `nr-isaac-format convert` (manual)

Build a record directly from a YAML **manifest** (fitted result) or **plan** (pre-fit), re-running the assembler from raw files. The format is detected automatically. This is the manual/standalone route — the manifest is no longer the pipeline handoff (see `convert-ingest`).

```bash
nr-isaac-format convert [OPTIONS] INPUT_FILE
```

| Option | Description |
|--------|-------------|
| `-o, --output DIR` | Output directory. Required for a plan; overrides a manifest's `output:` when given. |
| `-d, --data-dir DIR` | Directory holding the reduced data files. Required for a plan. |
| `--compact` | Output compact JSON (no indentation) |
| `--dry-run` | Parse and assemble but don't write output |

```bash
# manifest (fitted result, paths/output in the file)
nr-isaac-format convert experiment.yaml

# plan (pre-fit; bare data filenames resolved against -d, written under -o)
nr-isaac-format convert plan/job_230539.yaml -d Rawdata/ -o records/
```

### `nr-isaac-format validate`

Validate an ISAAC record against the local schema. Automatically uses the latest `ornl-rev*` schema if available.

```bash
nr-isaac-format validate FILE
```

### `nr-isaac-format push`

Push ISAAC record JSON files to the ISAAC Portal API. Accepts files and/or directories.

```bash
nr-isaac-format push [OPTIONS] PATHS...
```

| Option | Description |
|--------|-------------|
| `--validate-only` | Validate records against the remote API without persisting |
| `--url TEXT` | Override `ISAAC_URL` from `.env` |
| `--token TEXT` | Override `ISAAC_KEY` from `.env` |

### `nr-isaac-format health`

Check connectivity to the ISAAC Portal API.

```bash
nr-isaac-format health [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--url TEXT` | Override `ISAAC_URL` from `.env` |
| `--token TEXT` | Override `ISAAC_KEY` from `.env` |

### `nr-isaac-format fetch-schema`

Fetch the latest ISAAC schema from the Portal API and save it locally. Schemas are saved to `src/nr_isaac_format/schema/isaac_record_v<N>-ornl-rev<M>.json` with an auto-incremented local revision. If the fetched schema is identical to the latest local revision, no new file is written.

```bash
nr-isaac-format fetch-schema [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `--url TEXT` | Override `ISAAC_URL` from `.env` |
| `--token TEXT` | Override `ISAAC_KEY` from `.env` |

## Manifest Format

| Field | Required | Description |
|-------|----------|-------------|
| `title` | No | Experiment title |
| `sample.description` | No | Free-text sample description (→ `sample.material.notes`) |
| `sample.model` | No | Default model JSON file for all measurements |
| `sample.model_dataset_index` | No | Default 1-based dataset index in co-refinement models |
| `output` | Yes | Output directory for ISAAC JSON files |
| `measurements` | Yes | List of measurements (at least one) |

### Per-measurement fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Human-readable measurement name |
| `reduced` | Yes | Path to reduced reflectivity data file |
| `parquet` | No | Directory containing parquet metadata files |
| `model` | No | Model JSON file (overrides `sample.model`) |
| `model_dataset_index` | No | Dataset index (overrides `sample.model_dataset_index`) |
| `environment` | No | Environment enum value (`operando`, `in_situ`, `ex_situ`, `in_silico`) or free text that will be classified |
| `context` | No | Free-text description of how the measurement was made (→ `measurement.series[].notes`). Applied potentials mentioned here (`OCV`, `-1 V`, `0.5 V vs RHE`, …) are also parsed into `context.electrochemistry`, defaulting to the SHE scale. |
| `raw` | No | Path to raw NeXus file (→ `assets[]` with `content_role: "raw_data_pointer"`) |

The first measurement's model is used to create the sample record. All subsequent measurements reuse the same sample ID.

## Plan Format

A **plan** is a pre-fit job spec (no fitted model yet). `convert` accepts it directly with `-d` (where the reduced data files live) and `-o` (output directory). Each `state` becomes one ISAAC record built from its **primary** reduced data file (the first entry in `data`; sibling partials are not merged).

```yaml
describe: "D2O / Cu oxide / 50 nm Cu / 3 nm Ti on Si. Beam enters from the Si substrate side."
states:
  - name: run_230539
    data:                       # bare filenames; resolved against -d
      - REFL_230539_1_230539_partial.txt
      - REFL_230539_2_230540_partial.txt
    back_reflection: true       # → measurement_geometry descriptor
    extra_description: "OCV measurement in D2O electrolyte (pH 8.25, 0.1 M NaHCO3, N2 sparged)."
```

| Field | Required | Description |
|-------|----------|-------------|
| `describe` | No | Sample stack description (→ `sample.material.notes`) |
| `states` | Yes | List of measurement states (one record each) |
| `states[].name` | Yes | State name (used for the filename when no run number) |
| `states[].data` | Yes | Reduced data filenames; the first is used as the primary curve |
| `states[].back_reflection` | No | When true, sets the `measurement_geometry` descriptor |
| `states[].extra_description` | No | Measurement context (→ `measurement.series[].notes`; potentials parsed into `context.electrochemistry`) |

Because a plan is pre-fit, no layer model is assembled — the record captures the measured reflectivity, the sample/measurement descriptions, and any applied potential, but not fitted layer parameters.

## Environment Configuration

API commands (`push`, `health`, `fetch-schema`) require credentials. These are read from a `.env` file in the working directory or via environment variables:

```dotenv
ISAAC_KEY = "your-api-token"
ISAAC_URL = "https://isaac.slac.stanford.edu/portal/api"
```

Copy `.env.example` to `.env` and fill in your `ISAAC_KEY`. Credentials can also be passed per-command with `--url` and `--token`.

## Python API

### IsaacWriter

```python
from assembler.parsers import ManifestParser, ReducedParser
from assembler.workflow import DataAssembler
from nr_isaac_format import IsaacWriter

# Parse and assemble
manifest = ManifestParser().parse("experiment.yaml")
reduced = ReducedParser().parse(manifest.measurements[0].reduced)
result = DataAssembler().assemble(reduced=reduced)

# Convert to ISAAC format
writer = IsaacWriter()
record = writer.to_isaac(
    result,
    environment_description="operando",
    context_description="Electrochemical cell, THF electrolyte",
    raw_file_path="/SNS/REF_L/IPTS-34347/nexus/REF_L_218386.nxs.h5",
)

# Or write directly to file
writer.write(result, "isaac_record.json")
```

### Convenience Function

```python
from nr_isaac_format import write_isaac_record

path = write_isaac_record(result, "output.json")
```

## Output Format

Each ISAAC record is a JSON file conforming to the ISAAC AI-Ready Scientific Record schema (`v1-ornl-rev4`). Key blocks:

| Block | Description |
|-------|-------------|
| `isaac_record_version` | Always `"1.05"` |
| `record_id` | Auto-generated ULID |
| `record_type` | `"evidence"` |
| `record_domain` | `"characterization"` |
| `timestamps` | `created_utc` and `acquired_start_utc` from run metadata |
| `source_type` | Origin of the data (`"facility"`) |
| `measurement` | Q/R/dR/dQ reflectivity series, QC status, and a free-text `series[].notes` describing how the measurement was made |
| `descriptors` | Computed descriptors: q-range, total points, geometry, etc. |
| `sample` | Composition, sample form (`film`), provenance, and free-text `material.notes` |
| `context` | Environment enum, temperature, thermodynamics, and `electrochemistry`. When the assembler supplies structured conditions (control_mode, potential, scale, pH, electrolyte) they are used directly; otherwise applied potentials are parsed from the description (defaulting to the SHE scale) |
| `system` | Instrument, facility, configuration |
| `assets` | Raw NeXus file pointer, reduced data file with SHA-256 |

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Lint
ruff check src/ tests/
```

## Project Structure

```
src/nr_isaac_format/
├── __init__.py        # Package init, exports IsaacWriter
├── cli.py             # Click CLI (convert, validate, push, health, fetch-schema)
├── client.py          # ISAAC Portal API client (httpx)
├── writer.py          # AssemblyResult → ISAAC record conversion
└── schema/
    ├── isaac_record_v1.json           # Original upstream schema
    └── isaac_record_v1-ornl-rev1.json # ORNL revision with enum constraints
tests/
├── test_cli.py        # Convert and validate command tests
├── test_client.py     # API client unit tests
├── test_push.py       # Push, health, and fetch-schema command tests
└── test_writer.py     # Writer unit tests
```

## License

BSD-3-Clause
