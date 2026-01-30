# NR-ISAAC Format Writer

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: BSD-3-Clause](https://img.shields.io/badge/License-BSD--3--Clause-blue.svg)](https://opensource.org/licenses/BSD-3-Clause)

Write neutron reflectometry data from [data-assembler](https://github.com/mdoucet/data-assembler) to [ISAAC AI-Ready Record](https://github.com/dimosthenisSLAC/isaac-ai-ready-record) v1.0 format.

## Overview

This package provides a minimal writer that converts `AssemblyResult` from data-assembler into the ISAAC AI-Ready Scientific Record format. It follows the same pattern as data-assembler's `JSONWriter` and `ParquetWriter`.

## Installation

```bash
pip install -e .
```

## Quick Start

### From Python

```python
from assembler.workflow import DataAssembler
from nr_isaac_format import IsaacWriter

# Get assembled data from data-assembler
assembler = DataAssembler()
result = assembler.assemble(reduced=reduced_data)

# Write to ISAAC format
writer = IsaacWriter()
writer.write(result, "isaac_record.json")

# Or get dict directly
record = writer.to_isaac(result)
```

### From Command Line

```bash
# Convert reduced data via data-assembler pipeline
nr-isaac-format convert -r reduced.txt -o isaac_record.json

# With parquet metadata and model
nr-isaac-format convert -r reduced.txt -p parquet/ -m model.json -o output.json

# Convert pre-assembled JSON
nr-isaac-format from-json -i assembled.json -o isaac_record.json

# Validate an existing ISAAC record
nr-isaac-format validate isaac_record.json
```

## API

### IsaacWriter

```python
class IsaacWriter:
    def __init__(self, output_dir: str | Path | None = None):
        """Initialize writer with optional default output directory."""

    def to_isaac(self, result: AssemblyResult) -> dict:
        """Convert AssemblyResult to ISAAC record dict."""

    def write(self, result: AssemblyResult, output_path: str | Path | None = None) -> Path:
        """Write AssemblyResult as ISAAC JSON file."""
```

### Convenience Function

```python
from nr_isaac_format import write_isaac_record

path = write_isaac_record(result, "output.json")
```

## Output Format

```json
{
  "isaac_record_version": "1.0",
  "record_id": "01JFH3Q8Z1Q9F0XG3V7N4K2M8C",
  "record_type": "evidence",
  "record_domain": "characterization",
  "timestamps": {"created_utc": "...", "acquired_start_utc": "..."},
  "acquisition_source": {"source_type": "facility", "facility": {...}},
  "measurement": {"series": [...], "qc": {"status": "valid"}},
  "descriptors": {"outputs": [...]},
  "sample": {...},
  "context": {...},
  "system": {...},
  "assets": [...]
}
```

## License

BSD-3-Clause
