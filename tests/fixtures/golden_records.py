"""
Golden record fixtures for comparison testing.

These represent known-good ISAAC AI-Ready Record v1.0 outputs
that can be used to verify converter behavior.
"""

# Minimal valid ISAAC record
GOLDEN_RECORD_MINIMAL = {
    "record_id": "01HV9Z0ABCDEF123456789GOLD",
    "isaac_record_version": "1.0",
    "record_type": "evidence",
    "record_domain": "characterization",
    "timestamps": {
        "created_utc": "2025-01-15T12:00:00+00:00",
    },
    "acquisition_source": {
        "source_type": "experiment",
        "facility": "unknown",
        "instrument": "unknown",
    },
    "measurement": {
        "technique": "reflectivity",
        "probe": "neutrons",
        "series": [
            {
                "series_id": "refl_001",
                "series_type": "spectrum",
                "channels": [
                    {
                        "channel_id": "Q",
                        "label": "Momentum transfer",
                        "unit": "1/angstrom",
                        "values": [0.01, 0.02, 0.03],
                    },
                    {
                        "channel_id": "R",
                        "label": "Reflectivity",
                        "unit": "dimensionless",
                        "values": [1.0, 0.5, 0.1],
                    },
                ],
            }
        ],
    },
    "descriptors": [
        {
            "descriptor_id": "d001",
            "kind": "measurement_statistics",
            "key": "q_range",
            "value": {"min": 0.01, "max": 0.03, "unit": "1/angstrom"},
        },
    ],
}


# Full ISAAC record with all optional blocks
GOLDEN_RECORD_FULL = {
    "record_id": "01HV9FULLRECORD1234567890",
    "isaac_record_version": "1.0",
    "record_type": "evidence",
    "record_domain": "characterization",
    "timestamps": {
        "created_utc": "2025-01-15T12:00:00+00:00",
        "acquired_utc": "2025-01-15T10:30:00+00:00",
        "processed_utc": "2025-01-15T11:50:00+00:00",
    },
    "acquisition_source": {
        "source_type": "experiment",
        "facility": "SNS",
        "instrument": "REF_L",
        "run_id": "218386",
        "proposal_id": "IPTS-12345",
    },
    "measurement": {
        "technique": "reflectivity",
        "probe": "neutrons",
        "geometry": "front reflection",
        "series": [
            {
                "series_id": "refl_main",
                "series_type": "spectrum",
                "channels": [
                    {
                        "channel_id": "Q",
                        "label": "Momentum transfer",
                        "unit": "1/angstrom",
                        "values": [0.008, 0.010, 0.012, 0.015, 0.020],
                    },
                    {
                        "channel_id": "R",
                        "label": "Reflectivity",
                        "unit": "dimensionless",
                        "values": [0.98, 0.95, 0.90, 0.80, 0.50],
                    },
                    {
                        "channel_id": "dR",
                        "label": "Reflectivity uncertainty",
                        "unit": "dimensionless",
                        "values": [0.01, 0.01, 0.01, 0.02, 0.02],
                    },
                    {
                        "channel_id": "dQ",
                        "label": "Q resolution",
                        "unit": "1/angstrom",
                        "values": [0.0004, 0.0005, 0.0006, 0.0008, 0.001],
                    },
                ],
            }
        ],
    },
    "sample": {
        "sample_form": "thin_film",
        "material": {
            "name": "Copper",
            "formula": "Cu",
        },
        "composition": {
            "Cu_fraction": 1.0,
        },
        "geometry": {
            "total_thickness_angstrom": 500,
            "layer_count": 3,
        },
    },
    "system": {
        "domain": "experimental",
        "facility": {
            "facility_name": "SNS",
            "organization": "ORNL",
        },
        "instrument": {
            "instrument_type": "beamline_endstation",
            "instrument_name": "REF_L",
        },
        "configuration": {
            "measurement_geometry": "front reflection",
            "probe": "neutrons",
        },
    },
    "context": {
        "environment": "ex_situ",
        "temperature_K": 298.15,
    },
    "descriptors": [
        {
            "descriptor_id": "d001",
            "kind": "measurement_statistics",
            "key": "q_range",
            "value": {"min": 0.008, "max": 0.020, "unit": "1/angstrom"},
        },
        {
            "descriptor_id": "d002",
            "kind": "measurement_statistics",
            "key": "data_points",
            "value": 5,
        },
    ],
    "assets": [
        {
            "asset_id": "01HV9FULLRECORD1234567890-A001",
            "content_role": "raw_data_pointer",
            "uri": "file:///SNS/REF_L/IPTS-12345/nexus/REF_L_218386.nxs.h5",
            "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "format": "NeXus",
            "description": "Raw measurement data file",
        },
    ],
    "links": [],
}


def validate_against_golden(record: dict, golden: dict, strict: bool = False) -> list[str]:
    """
    Compare a generated record against a golden record.

    Args:
        record: Generated ISAAC record
        golden: Golden reference record
        strict: If True, requires exact match; otherwise checks structure

    Returns:
        List of differences found
    """
    differences = []

    # Check required root fields
    for field in ["isaac_record_version", "record_type", "record_domain"]:
        if record.get(field) != golden.get(field):
            differences.append(
                f"Root field '{field}': got {record.get(field)}, expected {golden.get(field)}"
            )

    # Check required blocks exist
    for block in ["timestamps", "acquisition_source", "measurement", "descriptors"]:
        if block in golden and block not in record:
            differences.append(f"Missing required block: {block}")

    # Check optional blocks if present in golden
    for block in ["sample", "system", "context", "assets", "links"]:
        if block in golden:
            if block not in record:
                differences.append(f"Missing optional block: {block}")
            elif strict:
                # Deep comparison for strict mode
                _compare_blocks(record[block], golden[block], block, differences)

    return differences


def _compare_blocks(actual: dict, expected: dict, path: str, differences: list[str]):
    """Recursively compare block structures."""
    if isinstance(expected, dict):
        for key in expected:
            if key not in actual:
                differences.append(f"{path}.{key}: missing")
            elif isinstance(expected[key], (dict, list)):
                _compare_blocks(actual[key], expected[key], f"{path}.{key}", differences)
    elif isinstance(expected, list):
        if len(actual) != len(expected):
            differences.append(f"{path}: length mismatch ({len(actual)} vs {len(expected)})")
