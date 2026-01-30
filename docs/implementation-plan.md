# NR-ISAAC Format Implementation Plan

## Overview

This project converts neutron reflectometry data from `data-assembler` to the **ISAAC AI-Ready Scientific Record v1.0** format. The converter transforms `AssemblyResult` objects into JSON records optimized for autonomous agent reasoning.

---

## Current Status

### ✅ Phase 1: Core Infrastructure (Complete)

| Component | File | Description |
|-----------|------|-------------|
| Project setup | `pyproject.toml` | Dependencies, build config, CLI entry point |
| Package init | `src/nr_isaac_format/__init__.py` | Package exports |
| ULID generator | `src/nr_isaac_format/ulid.py` | ISAAC-compliant 26-char record IDs |
| Base mapper | `src/nr_isaac_format/mappers/base.py` | Abstract `Mapper` class, `MapperContext` |
| Converter | `src/nr_isaac_format/converter.py` | `IsaacRecordConverter` orchestrator |
| CLI skeleton | `src/nr_isaac_format/cli.py` | `convert`, `from-json`, `validate` commands |
| Core tests | `tests/test_converter.py` | 18 unit tests |

### ✅ Phase 2: Essential Mappers (Complete)

| Mapper | File | ISAAC Block | Source Data |
|--------|------|-------------|-------------|
| `TimestampsMapper` | `mappers/timestamps.py` | `timestamps` | `reflectivity.created_at`, `run_start` |
| `AcquisitionSourceMapper` | `mappers/acquisition_source.py` | `acquisition_source` | `reflectivity.facility`, `instrument_name` |
| `MeasurementMapper` | `mappers/measurement.py` | `measurement` | Q/R/dR/dQ arrays → series/channels |
| `DescriptorsMapper` | `mappers/descriptors.py` | `descriptors` | Automated feature extraction |

### ✅ Phase 3: Optional Block Mappers (Complete)

| Mapper | File | ISAAC Block | Source Data |
|--------|------|-------------|-------------|
| `SampleMapper` | `mappers/sample.py` | `sample` | `sample.layers`, `main_composition` |
| `SystemMapper` | `mappers/system.py` | `system` | `reflectivity.facility`, `instrument_name` |
| `ContextMapper` | `mappers/context.py` | `context` | `environment.temperature`, `ambient_medium` |
| `AssetsMapper` | `mappers/assets.py` | `assets` | `raw_file_path`, `reduced_file` → URIs with sha256 |
| `LinksMapper` | `mappers/links.py` | `links` | Record relationships (derived_from, cites, etc.) |

**Tests:** 166 passing (unit + integration + schema validation)

### ✅ Phase 4: CLI & Integration Enhancements (Complete)

| Feature | Description |
|---------|-------------|
| Batch conversion | `nr-isaac-format batch -i input_dir/ -o output_dir/` |
| Output formatting | `--pretty`, `--compact`, `--include-nulls` options |
| Progress indicators | Progress bar for batch operations |
| Enhanced validation | Detailed error messages with paths and values |
| Glob patterns | `--pattern "run_*.json"` for selective batch processing |
| Error handling | `--continue-on-error` for resilient batch processing |

### ✅ Phase 5: Code Quality & Production Readiness (Complete)

| Feature | Description |
|---------|-------------|
| Type-safe constants | `constants.py` with enums for all ISAAC field values |
| Bundled schema | `schema/isaac_record_v1.json` included in package |
| CLI schema option | `--schema PATH` option for custom schema location |
| Protocol-based design | `Mapper` Protocol, `MeasurementData` TypedDict |
| Dependency injection | Clock injectable via `set_clock()` for testing |
| Configurable schema | Schema path via CLI, env var, or constructor |

---

## Remaining Phases

### 🔲 Phase 6: CI/CD & Distribution

| Task | Description |
|------|-------------|
| GitHub Actions | Automated testing on push/PR |
| PyPI publishing | Package distribution |
| Documentation hosting | ReadTheDocs or GitHub Pages |

---

## Architecture

```
src/nr_isaac_format/
├── __init__.py                 # Package exports
├── constants.py                # Type-safe enums for ISAAC values
├── converter.py                # IsaacRecordConverter (orchestrator)
├── cli.py                      # Click CLI commands
├── ulid.py                     # ULID generation
├── schema/
│   └── isaac_record_v1.json    # Bundled ISAAC v1.0 schema
└── mappers/
    ├── __init__.py             # Mapper exports
    ├── base.py                 # Mapper Protocol, MapperContext, MeasurementData
    ├── timestamps.py           # ✅ TimestampsMapper
    ├── acquisition_source.py   # ✅ AcquisitionSourceMapper
    ├── measurement.py          # ✅ MeasurementMapper
    ├── descriptors.py          # ✅ DescriptorsMapper
    ├── sample.py               # ✅ SampleMapper
    ├── system.py               # ✅ SystemMapper
    ├── context.py              # ✅ ContextMapper
    ├── assets.py               # ✅ AssetsMapper
    └── links.py                # ✅ LinksMapper
```

---

## Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    data-assembler                                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │ReducedParser│  │ParquetParser│  │ ModelParser │              │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘              │
│         └────────────────┼────────────────┘                      │
│                          ▼                                       │
│                  ┌───────────────┐                               │
│                  │ DataAssembler │                               │
│                  └───────┬───────┘                               │
│                          ▼                                       │
│                  ┌───────────────┐                               │
│                  │AssemblyResult │                               │
│                  │ • reflectivity│                               │
│                  │ • sample      │                               │
│                  │ • environment │                               │
│                  └───────┬───────┘                               │
└──────────────────────────┼───────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                   nr-isaac-format                                 │
│                          │                                        │
│                          ▼                                        │
│              ┌─────────────────────┐                              │
│              │IsaacRecordConverter │                              │
│              └──────────┬──────────┘                              │
│                         │                                         │
│         ┌───────────────┼───────────────┐                         │
│         ▼               ▼               ▼                         │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐                  │
│  │  Timestamps │ │Acquisition  │ │ Measurement │  ...             │
│  │   Mapper    │ │SourceMapper │ │   Mapper    │                  │
│  └──────┬──────┘ └──────┬──────┘ └──────┬──────┘                  │
│         └───────────────┼───────────────┘                         │
│                         ▼                                         │
│              ┌─────────────────────┐                              │
│              │  ISAAC Record v1.0  │                              │
│              │      (JSON)         │                              │
│              └─────────────────────┘                              │
└──────────────────────────────────────────────────────────────────┘
```

---

## Current Output Example

With Phase 1 & 2 complete, the converter produces records like:

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
    "processing": { "type": "reduced_reflectivity" },
    "series": [{
      "series_id": "reflectivity_profile",
      "independent_variables": [{
        "name": "q",
        "unit": "Å⁻¹",
        "values": [0.008, 0.010, 0.012, ...]
      }],
      "channels": [
        {"name": "R", "unit": "dimensionless", "role": "primary_signal", "values": [...]},
        {"name": "dR", "unit": "dimensionless", "role": "quality_monitor", "values": [...]},
        {"name": "dQ", "unit": "Å⁻¹", "role": "quality_monitor", "values": [...]}
      ]
    }],
    "qc": { "status": "valid", "evidence": "Data passed assembly validation." }
  },
  "descriptors": {
    "policy": { "requires_at_least_one": true },
    "outputs": [{
      "label": "automated_extraction_2025-01-15",
      "generated_utc": "2025-01-15T12:00:00Z",
      "generated_by": { "agent": "nr-isaac-format", "version": "0.1.0" },
      "descriptors": [
        {"name": "q_range_min", "kind": "absolute", "source": "computed", "value": 0.008, "unit": "Å⁻¹", "uncertainty": {"sigma": 0.00008}},
        {"name": "q_range_max", "kind": "absolute", "source": "computed", "value": 0.100, "unit": "Å⁻¹", "uncertainty": {"sigma": 0.001}},
        {"name": "total_points", "kind": "absolute", "source": "computed", "value": 9, "unit": "count", "uncertainty": {"sigma": 0}},
        {"name": "measurement_geometry", "kind": "categorical", "source": "model", "value": "front reflection", "uncertainty": {"confidence": 0.95}},
        {"name": "probe_type", "kind": "categorical", "source": "metadata", "value": "neutrons", "uncertainty": {"confidence": 1.0}}
      ]
    }]
  }
}
```

---

## Dependencies

```toml
[project]
dependencies = [
    "data-assembler",      # Core assembly (local)
    "jsonschema>=4.0",     # Schema validation
    "python-ulid>=2.0",    # ULID generation
    "click>=8.0",          # CLI framework
    "pydantic>=2.0",       # Data validation
]
```

---

## Usage

### CLI

```bash
# Convert with full pipeline
nr-isaac-format convert \
    -r reduced.txt \
    -p parquet/ \
    -m model.json \
    -o output.json

# Validate existing record
nr-isaac-format validate output.json
```

### Python API

```python
from assembler.workflow import DataAssembler
from nr_isaac_format import IsaacRecordConverter

result = assembler.assemble(reduced=reduced_data)
converter = IsaacRecordConverter()
conversion = converter.convert(result)

if conversion.is_valid:
    converter.write_json(conversion, "output.json")
```

---

## Test Summary

| Test Category | Tests | Description |
|---------------|-------|-------------|
| Core converter & ULID | 15 | Converter orchestration, ULID generation |
| Individual mappers | 70+ | All 9 ISAAC block mappers |
| Integration & schema | 20 | Full conversion, schema validation |
| Edge cases | 20 | Missing fields, partial data |
| Performance | 10 | Batch processing benchmarks |
| **Total** | **166** | **All passing** |
