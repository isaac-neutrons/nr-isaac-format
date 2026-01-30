# NR-ISAAC Format Converter

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: BSD-3-Clause](https://img.shields.io/badge/License-BSD--3--Clause-blue.svg)](https://opensource.org/licenses/BSD-3-Clause)
[![Tests](https://img.shields.io/badge/tests-166%20passing-brightgreen.svg)]()

Convert neutron reflectometry data from [data-assembler](../data-assembler) to [ISAAC AI-Ready Record](https://github.com/dimosthenisSLAC/isaac-ai-ready-record) v1.0 format.

## Overview

This package bridges neutron reflectometry data processing pipelines with AI-ready scientific data formats. It takes the output from `data-assembler` (which processes reduced reflectometry data, instrument metadata, and fitting models) and converts it to the ISAAC AI-Ready Scientific Record format optimized for autonomous agent reasoning.

## Installation

```bash
# Install in development mode
pip install -e .

# With development dependencies
pip install -e ".[dev]"
```

**Requirements:**
- Python 3.11+
- `data-assembler` package (local dependency)
- `jsonschema`, `python-ulid`, `click`, `pydantic`

## Quick Start

### From Command Line

```bash
# Convert reduced data directly
nr-isaac-format convert \
    -r ~/data/REFL_218386_combined_data_auto.txt \
    -o output/isaac_record.json

# With parquet metadata and model
nr-isaac-format convert \
    -r ~/data/reduced.txt \
    -p ~/data/parquet/ \
    -m ~/data/model.json \
    -o output/isaac_record.json

# Validate an existing ISAAC record
nr-isaac-format validate output/isaac_record.json
```

### From Python

```python
from assembler.parsers import ReducedParser
from assembler.workflow import DataAssembler
from nr_isaac_format import IsaacRecordConverter

# Parse and assemble data
reduced = ReducedParser().parse("reduced.txt")
assembler = DataAssembler()
result = assembler.assemble(reduced=reduced)

# Convert to ISAAC format
converter = IsaacRecordConverter()
conversion = converter.convert(result)

# Check result
if conversion.is_valid:
    converter.write_json(conversion, "isaac_record.json")
    print(f"Created record: {conversion.record_id}")
else:
    print("Errors:", conversion.errors)
```

## CLI Commands

### `convert` — Direct conversion pipeline

Runs the full data-assembler pipeline and converts to ISAAC format.

```bash
nr-isaac-format convert [OPTIONS]
```

| Option | Description |
|--------|-------------|
| `-r, --reduced PATH` | Path to reduced reflectivity data file (required) |
| `-p, --parquet PATH` | Directory with parquet files from nexus-processor |
| `-m, --model PATH` | Path to refl1d/bumps model JSON file |
| `-o, --output PATH` | Output path for ISAAC JSON file (required) |
| `--validate/--no-validate` | Validate output against ISAAC schema (default: on) |
| `--schema PATH` | Path to custom ISAAC JSON schema file |
| `--dry-run` | Parse and convert but don't write output |
| `--pretty/--no-pretty` | Pretty-print JSON output (default: on) |
| `--compact` | Output compact JSON (overrides --pretty) |

### `from-json` — Convert pre-assembled data

Convert data-assembler JSON output to ISAAC format.

```bash
nr-isaac-format from-json -i assembled.json -o isaac_record.json
```

| Option | Description |
|--------|-------------|
| `-i, --input PATH` | Path to assembled result JSON (required) |
| `-o, --output PATH` | Output path for ISAAC JSON file (required) |
| `--validate/--no-validate` | Validate output against ISAAC schema |
| `--schema PATH` | Path to custom ISAAC JSON schema file |

### `batch` — Batch conversion

Convert multiple pre-assembled JSON files to ISAAC format.

```bash
# Convert all JSON files in a directory
nr-isaac-format batch -i input_dir/ -o output_dir/

# With pattern matching
nr-isaac-format batch -i data/ -o records/ --pattern "run_*.json"

# Continue on errors
nr-isaac-format batch -i data/ -o records/ --continue-on-error
```

| Option | Description |
|--------|-------------|
| `-i, --input-dir PATH` | Input directory with data-assembler JSON files (required) |
| `-o, --output-dir PATH` | Output directory for ISAAC JSON files (required) |
| `--pattern TEXT` | Glob pattern for input files (default: `*.json`) |
| `--validate/--no-validate` | Validate outputs against schema (default: on) |
| `--schema PATH` | Path to custom ISAAC JSON schema file |
| `--continue-on-error` | Continue processing if a file fails |

### `validate` — Validate ISAAC records

Check a JSON file against the ISAAC v1.0 schema.

```bash
nr-isaac-format validate isaac_record.json
nr-isaac-format validate output.json --verbose
```

## Schema Configuration

The converter includes a bundled ISAAC v1.0 schema. You can override it:

1. **CLI option**: `--schema /path/to/schema.json`
2. **Environment variable**: `ISAAC_SCHEMA_PATH=/path/to/schema.json`
3. **Python API**: `IsaacRecordConverter(schema_path="/path/to/schema.json")`

## Output Format

The converter produces JSON files conforming to [ISAAC AI-Ready Record v1.0](https://github.com/dimosthenisSLAC/isaac-ai-ready-record):

```json
{
  "isaac_record_version": "1.0",
  "record_id": "01JFH3Q8Z1Q9F0XG3V7N4K2M8C",
  "record_type": "evidence",
  "record_domain": "characterization",
  "timestamps": {
    "created_utc": "2025-01-15T12:00:00Z",
    "acquired_start_utc": "2025-01-15T10:30:00Z"
  },
  "acquisition_source": {
    "source_type": "facility",
    "facility": {
      "site": "SNS",
      "beamline": "REF_L",
      "endstation": "reflectometer"
    }
  },
  "measurement": {
    "series": [{
      "series_id": "reflectivity_profile",
      "independent_variables": [{"name": "q", "unit": "Å⁻¹", "values": [...]}],
      "channels": [
        {"name": "R", "unit": "dimensionless", "role": "primary_signal", "values": [...]},
        {"name": "dR", "unit": "dimensionless", "role": "quality_monitor", "values": [...]}
      ]
    }],
    "qc": {"status": "valid"}
  },
  "descriptors": {
    "outputs": [{
      "label": "automated_extraction_2025-01-15",
      "generated_by": {"agent": "nr-isaac-format", "version": "0.1.0"},
      "descriptors": [
        {"name": "q_range_min", "kind": "absolute", "value": 0.008, "unit": "Å⁻¹", ...},
        {"name": "q_range_max", "kind": "absolute", "value": 0.100, "unit": "Å⁻¹", ...}
      ]
    }]
  }
}
```

## ISAAC Block Mappers

The converter uses dedicated mappers for each ISAAC schema block:

| Mapper | ISAAC Block | Description |
|--------|-------------|-------------|
| `TimestampsMapper` | `timestamps` | Created/acquired timestamps |
| `AcquisitionSourceMapper` | `acquisition_source` | Facility, beamline, instrument |
| `MeasurementMapper` | `measurement` | Q/R/dR/dQ data as series/channels |
| `DescriptorsMapper` | `descriptors` | Automated feature extraction |
| `SampleMapper` | `sample` | Material, composition, geometry |
| `SystemMapper` | `system` | Instrument configuration |
| `ContextMapper` | `context` | Environment conditions |
| `AssetsMapper` | `assets` | File references with SHA-256 |
| `LinksMapper` | `links` | Record relationships |

## Development

```bash
# Run tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=nr_isaac_format

# Run specific test file
pytest tests/test_converter.py -v

# Format code
black src/ tests/
ruff check src/ tests/
```

### Test Summary

| Test Category | Tests |
|---------------|-------|
| Core converter & ULID | 15 |
| Individual mappers | 70+ |
| Integration & schema | 20 |
| Edge cases | 20 |
| Performance | 10 |
| **Total** | **166** |

## Architecture

```
src/nr_isaac_format/
├── __init__.py           # Package exports
├── constants.py          # Type-safe enums for ISAAC values
├── converter.py          # IsaacRecordConverter orchestrator
├── cli.py                # Click CLI commands
├── ulid.py               # ULID generation utility
├── schema/
│   └── isaac_record_v1.json  # Bundled ISAAC schema
└── mappers/
    ├── base.py           # Abstract Mapper class, MapperContext
    ├── timestamps.py
    ├── acquisition_source.py
    ├── measurement.py
    ├── descriptors.py
    ├── sample.py
    ├── system.py
    ├── context.py
    ├── assets.py
    └── links.py
```

## License

BSD-3-Clause
