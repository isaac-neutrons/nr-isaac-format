# NR-ISAAC Format Writer

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: BSD-3-Clause](https://img.shields.io/badge/License-BSD--3--Clause-blue.svg)](https://opensource.org/licenses/BSD-3-Clause)

Write neutron reflectometry data from [data-assembler](https://github.com/mdoucet/data-assembler) to [ISAAC AI-Ready Record](https://github.com/dimosthenisSLAC/isaac-ai-ready-record) v1.0 format.

## Overview

This package provides a manifest-driven CLI and writer that converts neutron reflectometry data into the ISAAC AI-Ready Scientific Record format. You describe your sample and measurements in a single YAML manifest file, and the tool handles parsing, assembly via [data-assembler](https://github.com/mdoucet/data-assembler), and ISAAC record generation — one record per measurement.

## Installation

```bash
pip install -e .
```

## Quick Start

### 1. Create a manifest

Write a YAML file describing your sample and measurements:

```yaml
title: "IPTS-34347 Cu/THF non-aqueous experiment"

sample:
  description: "Cu in THF on Si"
  model: /path/to/model.json
  model_dataset_index: 1

output: ./output

measurements:
  - name: "Steady-state OCV"
    reduced: /path/to/REFL_218386_reduced_data.txt
    parquet: /path/to/parquet/
    model: /path/to/model.json
    model_dataset_index: 1
    environment: "Electrochemical cell, THF electrolyte, steady-state OCV"

  - name: "Final OCV"
    reduced: /path/to/REFL_218393_combined_data_auto.txt
    model: /path/to/model.json
    model_dataset_index: 2
    environment: "Electrochemical cell, THF electrolyte, final OCV"
```

### 2. Run the conversion

```bash
nr-isaac-format convert experiment.yaml
```

This produces one ISAAC JSON file per measurement in the `output` directory:

```
output/
  isaac_record_01_steady-state_ocv.json
  isaac_record_02_final_ocv.json
```

### Command Line Reference

```bash
# Convert measurements from a manifest
nr-isaac-format convert experiment.yaml

# Preview without writing files
nr-isaac-format convert --dry-run experiment.yaml

# Output compact (non-indented) JSON
nr-isaac-format convert --compact experiment.yaml

# Validate an existing ISAAC record against the schema
nr-isaac-format validate output/isaac_record_01_steady-state_ocv.json
```

### Manifest Format

| Field | Required | Description |
|-------|----------|-------------|
| `title` | No | Experiment title (included in each ISAAC record) |
| `sample.description` | No | Sample description text |
| `sample.model` | No | Default model JSON file for all measurements |
| `sample.model_dataset_index` | No | Default 1-based dataset index in co-refinement models |
| `output` | Yes | Output directory for ISAAC JSON files |
| `measurements` | Yes | List of measurements (at least one) |
| `measurements[].name` | Yes | Human-readable measurement name |
| `measurements[].reduced` | Yes | Path to reduced reflectivity data file |
| `measurements[].parquet` | No | Directory containing parquet metadata files |
| `measurements[].model` | No | Model JSON (overrides `sample.model`) |
| `measurements[].model_dataset_index` | No | Dataset index (overrides `sample.model_dataset_index`) |
| `measurements[].environment` | No | Environment description text |

The first measurement's model is used to create the sample record. All subsequent measurements reuse the same sample ID.

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
record = writer.to_isaac(result, title=manifest.title)

# Or write directly to file
writer.write(result, "isaac_record.json", title=manifest.title)
```

### Convenience Function

```python
from nr_isaac_format import write_isaac_record

path = write_isaac_record(result, "output.json")
```

## Output Format

Each ISAAC record is a JSON file conforming to the ISAAC AI-Ready Scientific Record v1.0 schema:

```json
{
  "isaac_record_version": "1.0",
  "record_id": "01JFH3Q8Z1Q9F0XG3V7N4K2M8C",
  "record_type": "evidence",
  "record_domain": "characterization",
  "title": "IPTS-34347 Cu/THF non-aqueous experiment",
  "timestamps": {"created_utc": "...", "acquired_start_utc": "..."},
  "acquisition_source": {"source_type": "facility", "facility": {...}},
  "measurement": {"series": [...], "qc": {"status": "valid"}},
  "descriptors": {"outputs": [...]},
  "sample": {...},
  "context": {"environment": "Electrochemical cell, THF electrolyte, ..."},
  "system": {...},
  "assets": [...]
}
```

## License

BSD-3-Clause
