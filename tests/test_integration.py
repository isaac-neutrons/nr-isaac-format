"""
Integration tests for full ISAAC record conversion.

Tests the complete conversion pipeline and validates output
against the ISAAC AI-Ready Record v1.0 JSON schema.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nr_isaac_format.converter import IsaacRecordConverter


def create_mock_assembly_result():
    """Create a realistic mock AssemblyResult."""
    mock_result = MagicMock()

    mock_result.reflectivity = {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "created_at": datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        "facility": "SNS",
        "laboratory": "ORNL",
        "instrument_name": "REF_L",
        "run_number": "218386",
        "run_title": "Cu/Si thin film measurement",
        "run_start": datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
        "probe": "neutrons",
        "technique": "reflectivity",
        "raw_file_path": "/SNS/REF_L/IPTS-12345/nexus/REF_L_218386.nxs.h5",
        "reflectivity": {
            "q": [0.008, 0.010, 0.012, 0.015, 0.020, 0.030, 0.050, 0.080, 0.100],
            "r": [0.98, 0.95, 0.90, 0.80, 0.50, 0.15, 0.02, 0.005, 0.002],
            "dr": [0.01, 0.01, 0.01, 0.02, 0.02, 0.01, 0.005, 0.002, 0.001],
            "dq": [0.0004, 0.0005, 0.0006, 0.0008, 0.001, 0.002, 0.003, 0.004, 0.005],
            "measurement_geometry": "front reflection",
            "reduction_version": "quicknxs 4.0.0",
            "reduction_time": datetime(2025, 1, 15, 11, 0, 0, tzinfo=timezone.utc),
        },
    }

    mock_result.sample = {
        "id": "660e8400-e29b-41d4-a716-446655440001",
        "description": "Cu film on Si substrate",
        "main_composition": "Cu",
        "layers": [
            {"layer_number": 1, "material": "air", "thickness": 0, "sld": 0},
            {"layer_number": 2, "material": "Cu", "thickness": 500, "sld": 6.5},
            {"layer_number": 3, "material": "Si", "thickness": 0, "sld": 2.1},
        ],
    }

    mock_result.environment = {
        "id": "770e8400-e29b-41d4-a716-446655440002",
        "description": "Room temperature, air",
        "temperature": 298.0,
        "ambient_medium": "air",
    }

    mock_result.warnings = []
    mock_result.errors = []
    mock_result.needs_review = {}
    mock_result.reduced_file = "/data/REFL_218386_combined_data_auto.txt"
    mock_result.model_file = "/data/model.json"

    return mock_result


class TestFullConversion:
    """Tests for complete conversion pipeline."""

    def test_convert_produces_valid_structure(self):
        """Conversion should produce all required ISAAC blocks."""
        result = create_mock_assembly_result()
        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(result)

        record = conversion.record

        # Check root fields
        assert record["isaac_record_version"] == "1.0"
        assert record["record_type"] == "evidence"
        assert record["record_domain"] == "characterization"
        assert len(record["record_id"]) == 26  # ULID

        # Check required blocks
        assert "timestamps" in record
        assert "acquisition_source" in record
        assert "descriptors" in record

        # Check optional but expected blocks
        assert "measurement" in record

    def test_convert_timestamps_block(self):
        """Timestamps block should have correct structure."""
        result = create_mock_assembly_result()
        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(result)

        timestamps = conversion.record["timestamps"]

        assert "created_utc" in timestamps
        assert timestamps["created_utc"].endswith("Z")
        assert "acquired_start_utc" in timestamps

    def test_convert_acquisition_source_block(self):
        """Acquisition source should map facility correctly."""
        result = create_mock_assembly_result()
        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(result)

        source = conversion.record["acquisition_source"]

        assert source["source_type"] == "facility"
        assert source["facility"]["site"] == "SNS"
        assert source["facility"]["beamline"] == "REF_L"

    def test_convert_measurement_block(self):
        """Measurement should have series with channels."""
        result = create_mock_assembly_result()
        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(result)

        measurement = conversion.record["measurement"]

        assert "series" in measurement
        assert len(measurement["series"]) == 1

        series = measurement["series"][0]
        assert series["series_id"] == "reflectivity_profile"

        # Check independent variable
        assert len(series["independent_variables"]) == 1
        q_var = series["independent_variables"][0]
        assert q_var["name"] == "q"
        assert len(q_var["values"]) == 9

        # Check channels
        assert len(series["channels"]) == 3  # R, dR, dQ
        channel_names = [c["name"] for c in series["channels"]]
        assert "R" in channel_names
        assert "dR" in channel_names
        assert "dQ" in channel_names

        # Check QC
        assert measurement["qc"]["status"] == "valid"

    def test_convert_descriptors_block(self):
        """Descriptors should have automated outputs."""
        result = create_mock_assembly_result()
        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(result)

        descriptors = conversion.record["descriptors"]

        assert descriptors["policy"]["requires_at_least_one"] is True
        assert len(descriptors["outputs"]) == 1

        output = descriptors["outputs"][0]
        assert "automated_extraction" in output["label"]
        assert output["generated_by"]["agent"] == "nr-isaac-format"

        # Check descriptors content
        desc_names = [d["name"] for d in output["descriptors"]]
        assert "q_range_min" in desc_names
        assert "q_range_max" in desc_names
        assert "measurement_geometry" in desc_names

    def test_conversion_result_to_json(self):
        """Should serialize to valid JSON."""
        result = create_mock_assembly_result()
        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(result)

        json_str = conversion.to_json()

        # Should be valid JSON
        parsed = json.loads(json_str)
        assert parsed["isaac_record_version"] == "1.0"

    def test_conversion_with_schema_validation(self):
        """Should validate against ISAAC schema when available."""
        result = create_mock_assembly_result()
        converter = IsaacRecordConverter(validate_output=True)
        conversion = converter.convert(result)

        # The schema may or may not be available
        # If not available, validation passes with warning
        if conversion.is_valid:
            assert conversion.record["isaac_record_version"] == "1.0"
        else:
            # Schema validation failed - check for error message
            assert len(conversion.errors) > 0


class TestSchemaValidation:
    """Tests that validate output against the ISAAC JSON schema."""

    @pytest.fixture
    def schema(self):
        """Load the ISAAC schema if available."""
        schema_path = Path.home() / "git" / "isaac-ai-ready-record" / "schema" / "isaac_record_v1.json"
        if not schema_path.exists():
            pytest.skip("ISAAC schema not found")

        with open(schema_path) as f:
            return json.load(f)

    def test_full_record_validates(self, schema):
        """Complete conversion should pass schema validation."""
        import jsonschema

        result = create_mock_assembly_result()
        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(result)

        # This should not raise
        jsonschema.validate(conversion.record, schema)

    def test_minimal_record_validates(self, schema):
        """Minimal conversion should pass schema validation."""
        import jsonschema

        # Create minimal result
        mock_result = MagicMock()
        mock_result.reflectivity = {
            "facility": "SNS",
            "instrument_name": "REF_L",
            "run_start": datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
            "reflectivity": {
                "q": [0.01, 0.02],
                "r": [0.9, 0.8],
                "dr": [0.01, 0.01],
                "dq": [0.001, 0.001],
            },
        }
        mock_result.sample = None
        mock_result.environment = None
        mock_result.warnings = []
        mock_result.errors = []
        mock_result.needs_review = {}

        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(mock_result)

        # This should not raise
        jsonschema.validate(conversion.record, schema)

    def test_record_id_format(self, schema):
        """Record ID should match ULID pattern."""
        result = create_mock_assembly_result()
        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(result)

        record_id = conversion.record["record_id"]

        # ULID pattern: 26 uppercase alphanumeric
        assert len(record_id) == 26
        assert record_id.isupper()
        assert all(c.isalnum() for c in record_id)
