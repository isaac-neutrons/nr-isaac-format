# NR-ISAAC Format Converter

## Overview

This project provides a utility that uses the `data-assembler` package to create JSON files conforming to the **ISAAC AI-Ready Scientific Record v1.0** schema. It bridges the neutron reflectometry data assembled by `data-assembler` into a format optimized for autonomous agent reasoning.

---

## Implementation Plan

### 1. Project Structure

```
nr-isaac-format/
├── pyproject.toml
├── README.md
├── docs/
│   └── project.md
├── src/
│   └── nr_isaac_format/
│       ├── __init__.py
│       ├── cli.py                    # CLI commands
│       ├── constants.py              # Type-safe enums for ISAAC values
│       ├── converter.py              # Main conversion orchestration
│       ├── ulid.py                   # ULID generation utility
│       ├── schema/
│       │   └── isaac_record_v1.json  # Bundled ISAAC v1.0 schema
│       └── mappers/
│           ├── __init__.py
│           ├── base.py               # Mapper Protocol, MapperContext
│           ├── record_metadata.py    # Root record fields mapper
│           ├── timestamps.py         # Timestamps block mapper
│           ├── acquisition_source.py # Acquisition source mapper
│           ├── sample.py             # Sample block mapper
│           ├── system.py             # System block mapper
│           ├── context.py            # Context block mapper
│           ├── measurement.py        # Measurement block mapper
│           ├── assets.py             # Assets array mapper
│           ├── links.py              # Links array mapper
│           └── descriptors.py        # Descriptors block mapper
├── tests/
│   ├── test_converter.py
│   ├── test_mappers/
│   └── fixtures/
└── examples/
    └── output/
```

---

### 2. Data Mapping Analysis

#### 2.1 Source Data (data-assembler `AssemblyResult`)

The `data-assembler` produces three linked records:

| Record | Source | Key Fields |
|--------|--------|------------|
| **Reflectivity** | Reduced + Parquet | Q/R/dR/dQ arrays, run metadata, facility, instrument, geometry |
| **Environment** | Parquet DAS logs + Model | temperature, pressure, ambient_medium |
| **Sample** | Model JSON | layers (thickness, SLD, material), substrate, composition |

#### 2.2 Target Schema (ISAAC AI-Ready Record v1.0)

The ISAAC schema has 8 main blocks:

| Block | Required | Maps From |
|-------|----------|-----------|
| **Root metadata** | Yes | Generated + Reflectivity record |
| **timestamps** | Yes | Reflectivity.run_start, Reflectivity.created_at |
| **acquisition_source** | Yes | Reflectivity (facility, instrument) |
| **sample** | No | Sample record (layers, composition) |
| **system** | No | Reflectivity + Environment (instrument config) |
| **context** | No | Environment record |
| **measurement** | No | Reflectivity (Q/R/dR/dQ as series/channels) |
| **links** | No | Computed relationships |
| **assets** | No | Reflectivity.raw_file_path + reduction metadata |
| **descriptors** | Required if evidence | Placeholder / future extraction |

---

### 3. Field Mapping Specification

#### 3.1 Root Record Metadata

| ISAAC Field | Source | Mapping Logic |
|-------------|--------|---------------|
| `isaac_record_version` | Constant | `"1.0"` |
| `record_id` | Generated | ULID (26-char alphanumeric) |
| `record_type` | Constant | `"evidence"` (measurement data) |
| `record_domain` | Constant | `"characterization"` (reflectometry) |

#### 3.2 Timestamps Block

| ISAAC Field | Source | Mapping Logic |
|-------------|--------|---------------|
| `created_utc` | `reflectivity.created_at` | ISO 8601 format |
| `acquired_start_utc` | `reflectivity.run_start` | ISO 8601 format |
| `acquired_end_utc` | `reflectivity.run_start` | Same as start (duration unknown) |

#### 3.3 Acquisition Source Block

| ISAAC Field | Source | Mapping Logic |
|-------------|--------|---------------|
| `source_type` | Constant | `"facility"` |
| `facility.site` | `reflectivity.facility` | e.g., "SNS" |
| `facility.beamline` | `reflectivity.instrument_name` | e.g., "REF_L" |
| `facility.endstation` | Constant | `"reflectometer"` |

#### 3.4 Sample Block

| ISAAC Field | Source | Mapping Logic |
|-------------|--------|---------------|
| `material.name` | `sample.main_composition` | Primary material name |
| `material.formula` | `sample.main_composition` | Extract formula if available |
| `material.provenance` | Constant | `"model_fitted"` |
| `sample_form` | Constant | `"thin_film"` (reflectometry assumption) |
| `composition` | `sample.layers` | Extract composition from layer stack |
| `geometry` | `sample.layers` | Total thickness, layer count |

#### 3.5 System Block

| ISAAC Field | Source | Mapping Logic |
|-------------|--------|---------------|
| `domain` | Constant | `"experimental"` |
| `facility.facility_name` | `reflectivity.facility` | e.g., "SNS" |
| `facility.organization` | `reflectivity.laboratory` | e.g., "ORNL" |
| `facility.beamline` | `reflectivity.instrument_name` | Instrument ID |
| `instrument.instrument_type` | Constant | `"beamline_endstation"` |
| `instrument.instrument_name` | `reflectivity.instrument_name` | e.g., "REF_L" |
| `configuration` | `reflectivity.reflectivity` | `measurement_geometry`, `probe` |

#### 3.6 Context Block

| ISAAC Field | Source | Mapping Logic |
|-------------|--------|---------------|
| `environment` | `environment.ambient_medium` | e.g., "air", "D2O" → `"ex_situ"` or `"in_situ"` |
| `temperature_K` | `environment.temperature` | Direct mapping |
| `pressure_Pa` | `environment.pressure` | Direct mapping (optional) |
| `ambient_medium` | `environment.ambient_medium` | e.g., "air" |

#### 3.7 Measurement Block

| ISAAC Field | Source | Mapping Logic |
|-------------|--------|---------------|
| `processing.type` | Constant | `"reduced_reflectivity"` |
| `series[0].series_id` | Generated | `"reflectivity_profile"` |
| `series[0].independent_variables[0]` | `reflectivity.reflectivity.q` | `{name: "q", unit: "Å⁻¹", values: [...]}` |
| `series[0].channels[0]` | `reflectivity.reflectivity.r` | `{name: "R", unit: "dimensionless", role: "primary_signal"}` |
| `series[0].channels[1]` | `reflectivity.reflectivity.dr` | `{name: "dR", unit: "dimensionless", role: "quality_monitor"}` |
| `series[0].channels[2]` | `reflectivity.reflectivity.dq` | `{name: "dQ", unit: "Å⁻¹", role: "quality_monitor"}` |
| `qc.status` | Computed | Based on data validation (warnings/errors) |

#### 3.8 Assets Block

| ISAAC Field | Source | Mapping Logic |
|-------------|--------|---------------|
| `assets[0].asset_id` | Generated | `"raw_nexus_file"` |
| `assets[0].content_role` | Constant | `"raw_data_pointer"` |
| `assets[0].uri` | `reflectivity.raw_file_path` | NeXus file path |
| `assets[0].sha256` | Computed | Hash of raw file (if accessible) |
| `assets[1].asset_id` | Generated | `"reduction_output"` |
| `assets[1].content_role` | Constant | `"reduction_product"` |
| `assets[1].uri` | `result.reduced_file` | Reduced data file path |

#### 3.9 Links Block

For reflectometry, links are typically empty unless:
- Multiple runs are combined → `derived_from`
- Calibration run exists → `calibration_of`

#### 3.10 Descriptors Block (Required for `record_type: evidence`)

| ISAAC Field | Source | Mapping Logic |
|-------------|--------|---------------|
| `policy.requires_at_least_one` | Constant | `true` |
| `outputs[0].label` | Generated | `"automated_extraction_{date}"` |
| `outputs[0].generated_utc` | `datetime.now()` | Current timestamp |
| `outputs[0].generated_by.agent` | Constant | `"nr-isaac-format"` |
| `outputs[0].descriptors` | Extracted | Q-range, total counts, geometry |

Example automated descriptors:
- `q_range_min` (absolute): minimum Q value
- `q_range_max` (absolute): maximum Q value  
- `measurement_geometry` (categorical): "front reflection" / "back reflection"
- `total_points` (absolute): number of data points

---

### 4. Implementation Phases

#### Phase 1: Core Infrastructure (Week 1)

**Tasks:**
1. Set up project structure with `pyproject.toml`
2. Add `data-assembler` as dependency
3. Implement ULID generator (or use `python-ulid` package)
4. Create abstract `Mapper` base class
5. Implement `IsaacRecordConverter` orchestrator class

**Deliverables:**
- Basic project scaffolding
- `converter.py` skeleton
- Unit test infrastructure

#### Phase 2: Essential Mappers (Week 2)

**Tasks:**
1. Implement `RecordMetadataMapper` (root fields)
2. Implement `TimestampsMapper`
3. Implement `AcquisitionSourceMapper`
4. Implement `MeasurementMapper` (Q/R/dR/dQ → series/channels)
5. Implement `DescriptorsMapper` (basic automated extraction)

**Deliverables:**
- Minimal valid ISAAC record generation
- JSON schema validation against `isaac_record_v1.json`

#### Phase 3: Optional Blocks (Week 3)

**Tasks:**
1. Implement `SampleMapper` (layer stack conversion)
2. Implement `SystemMapper` (instrument configuration)
3. Implement `ContextMapper` (environment conditions)
4. Implement `AssetsMapper` (file references)
5. Implement `LinksMapper` (relationship tracking)

**Deliverables:**
- Full schema coverage
- Rich metadata in output records

#### Phase 4: CLI & Integration (Week 4)

**Tasks:**
1. Create CLI with Click (`nr-isaac-format convert`)
2. Add batch conversion support
3. Integrate with `data-assembler` pipeline
4. Add `--validate` flag for JSON schema validation
5. Write documentation

**Deliverables:**
- Standalone CLI tool
- Integration example with data-assembler workflow

#### Phase 5: Testing & Validation (Week 5)

**Tasks:**
1. Create test fixtures from real data
2. Validate output against ISAAC golden records
3. Add edge case handling (missing data, partial assemblies)
4. Performance testing for batch conversion
5. Documentation and examples

**Deliverables:**
- Comprehensive test suite
- Validated against ISAAC schema
- Production-ready release

---

### 5. CLI Interface Design

```bash
# Convert a single assembled result to ISAAC format
nr-isaac-format convert \
    --input assembled_result.json \
    --output isaac_record.json \
    --validate

# Convert from data-assembler pipeline directly
nr-isaac-format from-assembler \
    --reduced /path/to/reduced.txt \
    --parquet /path/to/parquet/ \
    --model /path/to/model.json \
    --output isaac_record.json

# Batch conversion
nr-isaac-format batch \
    --input-dir /path/to/assembled/ \
    --output-dir /path/to/isaac/ \
    --validate

# Use custom schema
nr-isaac-format convert \
    --input assembled_result.json \
    --output isaac_record.json \
    --schema /path/to/custom_schema.json
```

**Schema Configuration:**

The converter includes a bundled ISAAC v1.0 schema. Override with:
1. CLI: `--schema /path/to/schema.json`
2. Environment: `ISAAC_SCHEMA_PATH=/path/to/schema.json`
3. Python: `IsaacRecordConverter(schema_path="/path/to/schema.json")`

---

### 6. Dependencies

```toml
[project]
dependencies = [
    "data-assembler",           # Core assembly functionality
    "jsonschema>=4.0",          # ISAAC schema validation
    "python-ulid>=2.0",         # ULID generation
    "click>=8.0",               # CLI framework
    "pydantic>=2.0",            # Data validation
]
```

---

### 7. Key Design Decisions

1. **Mapper Pattern**: Each ISAAC block has a dedicated mapper class for maintainability
2. **ULID over UUID**: ISAAC schema requires ULID format (26-char, sortable)
3. **Graceful Degradation**: Missing data produces valid but sparse records
4. **Validation-First**: Every output validated against JSON schema before writing
5. **Reuse data-assembler**: Don't duplicate parsing logic; use `AssemblyResult` directly

---

### 8. Example Conversion

**Input (data-assembler `AssemblyResult`):**
```python
result.reflectivity = {
    "id": "uuid",
    "facility": "SNS",
    "instrument_name": "REF_L",
    "run_number": "218386",
    "run_start": datetime(2024, 1, 15, 10, 30),
    "reflectivity": {
        "q": [0.01, 0.02, 0.03, ...],
        "r": [0.95, 0.85, 0.70, ...],
        "dr": [0.01, 0.01, 0.02, ...],
        "dq": [0.001, 0.002, 0.003, ...],
        "measurement_geometry": "front reflection"
    }
}
```

**Output (ISAAC AI-Ready Record):**
```json
{
  "isaac_record_version": "1.0",
  "record_id": "01JFH3Q8Z1Q9F0XG3V7N4K2M8C",
  "record_type": "evidence",
  "record_domain": "characterization",
  "timestamps": {
    "created_utc": "2024-01-15T12:00:00Z",
    "acquired_start_utc": "2024-01-15T10:30:00Z"
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
    "processing": {"type": "reduced_reflectivity"},
    "series": [{
      "series_id": "reflectivity_profile",
      "independent_variables": [{
        "name": "q",
        "unit": "Å⁻¹",
        "values": [0.01, 0.02, 0.03]
      }],
      "channels": [
        {"name": "R", "unit": "dimensionless", "role": "primary_signal", "values": [0.95, 0.85, 0.70]},
        {"name": "dR", "unit": "dimensionless", "role": "quality_monitor", "values": [0.01, 0.01, 0.02]},
        {"name": "dQ", "unit": "Å⁻¹", "role": "quality_monitor", "values": [0.001, 0.002, 0.003]}
      ]
    }],
    "qc": {"status": "valid"}
  },
  "descriptors": {
    "policy": {"requires_at_least_one": true},
    "outputs": [{
      "label": "automated_extraction_2024-01-15",
      "generated_utc": "2024-01-15T12:00:00Z",
      "generated_by": {"agent": "nr-isaac-format", "version": "1.0"},
      "descriptors": [
        {"name": "q_range_min", "kind": "absolute", "source": "computed", "value": 0.01, "unit": "Å⁻¹", "uncertainty": {"sigma": 0.001}},
        {"name": "q_range_max", "kind": "absolute", "source": "computed", "value": 0.03, "unit": "Å⁻¹", "uncertainty": {"sigma": 0.001}},
        {"name": "measurement_geometry", "kind": "categorical", "source": "model", "value": "front reflection", "uncertainty": {"confidence": 0.95}}
      ]
    }]
  }
}
```

---

### 9. Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Schema version changes | Pin to v1.0, monitor ISAAC repo for updates |
| Missing required data | Generate warnings, use sensible defaults |
| Large data arrays | Consider external asset references vs inline values |
| Invalid ULID format | Use established `python-ulid` library |
| Instrument-specific quirks | Extend mapper pattern per instrument |

---

### 10. Success Criteria

1. ✅ Generated records pass ISAAC JSON schema validation
2. ✅ All data from `AssemblyResult` is preserved or mapped
3. ✅ CLI integrates seamlessly with `data-assembler` workflow
4. ✅ Batch conversion handles 100+ records without errors
5. ✅ Output records usable by ISAAC-compatible AI agents

---

### 11. Implementation Status

All phases complete. Total: **166 tests passing**.

| Phase | Status | Notes |
|-------|--------|-------|
| Phase 1: Core Infrastructure | ✅ Complete | `IsaacRecordConverter`, `Mapper` base class, ULID generation |
| Phase 2: Essential Mappers | ✅ Complete | `TimestampsMapper`, `AcquisitionSourceMapper`, `MeasurementMapper`, `DescriptorsMapper` |
| Phase 3: Optional Blocks | ✅ Complete | `SampleMapper`, `SystemMapper`, `ContextMapper`, `AssetsMapper`, `LinksMapper` |
| Phase 4: CLI & Integration | ✅ Complete | `convert`, `from-json`, `batch`, `validate` commands |
| Phase 5: Testing & Production | ✅ Complete | Test fixtures, edge cases, golden records, CI/CD, performance benchmarks |

**Key Deliverables:**

- `/src/nr_isaac_format/` - Complete package with 10 mappers
- `/tests/` - 166 tests covering edge cases, golden records, performance
- `/.github/workflows/ci.yml` - GitHub Actions CI pipeline
- `/README.md` - User documentation with examples