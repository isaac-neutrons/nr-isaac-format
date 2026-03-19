# ISAAC Schema Changelog

Tracks changes between bundled schema revisions and their impact on the writer.

## Update workflow

1. `nr-isaac-format fetch-schema` — downloads and saves new revision
2. Diff new rev against previous: `diff schema/isaac_record_v1-ornl-rev1.json schema/isaac_record_v1-ornl-rev2.json`
3. Update `writer.py` to match new schema
4. Bump `SCHEMA_REVISION` in `writer.py`
5. Update tests, run `pytest`

---

## v1-ornl-rev2 (from rev1)

### Breaking changes

| Change | Detail | Writer action |
|--------|--------|--------------|
| `acquisition_source` removed | `source_type` moved to top-level required field; added `"industrial"` option | Removed `_map_acquisition_source()`; emit `"source_type": "facility"` at top level |
| `descriptors[].source` enum | `computed`/`metadata` → `auto`/`manual`/`imported` | Changed to `"auto"` |
| `system.technique` added (required) | Enum of techniques including `neutron_reflectometry` | Added `"technique": "neutron_reflectometry"` |
| `system.domain` restricted | Removed `"empirical"` (kept `experimental`, `computational`) | No change needed (we use `experimental`) |
| `system.configuration` keys restricted | Enum of allowed keys only | Removed freeform keys (`measurement_geometry`, `probe`) |
| `system.simulation` removed | Techniques now in `system.technique` | No change needed (not used) |
| `links.basis` required enum | Must be one of 11 values when links present | No change needed (links not emitted) |

### Non-breaking additions

- `assets.content_role`: added `raw_data`, `workflow_recipe`, `processing_script`, `calibration_reference`, `auxiliary_reference`, `documentation`
- `descriptors.kind`: added `theoretical_metric`
- `source_type`: added `"industrial"`
- `context`: now `additionalProperties: true`

---

## v1-ornl-rev1 (initial)

Baseline schema. See `isaac_record_v1-ornl-rev1.json`.
