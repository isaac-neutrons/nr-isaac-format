"""
Tests for ISAAC block mappers.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from nr_isaac_format.mappers import (
    AcquisitionSourceMapper,
    DescriptorsMapper,
    MapperContext,
    MeasurementMapper,
    TimestampsMapper,
)


def create_mock_context(
    reflectivity: dict = None,
    sample: dict = None,
    environment: dict = None,
) -> MapperContext:
    """Helper to create a mock MapperContext."""
    mock_result = MagicMock()
    mock_result.reflectivity = reflectivity
    mock_result.sample = sample
    mock_result.environment = environment
    mock_result.warnings = []
    mock_result.errors = []

    return MapperContext(
        result=mock_result,
        record_id="01JFH3Q8Z1Q9F0XG3V7N4K2M8C",
        created_utc=datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
    )


class TestTimestampsMapper:
    """Tests for TimestampsMapper."""

    def test_block_name(self):
        """Should return 'timestamps' as block name."""
        mapper = TimestampsMapper()
        assert mapper.block_name == "timestamps"

    def test_is_required(self):
        """Timestamps block is required."""
        mapper = TimestampsMapper()
        assert mapper.is_required() is True

    def test_map_with_reflectivity_data(self):
        """Should map timestamps from reflectivity record."""
        context = create_mock_context(
            reflectivity={
                "created_at": datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
                "run_start": datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
            }
        )

        mapper = TimestampsMapper()
        result = mapper.map(context)

        assert result is not None
        assert result["created_utc"] == "2025-01-15T12:00:00Z"
        assert result["acquired_start_utc"] == "2025-01-15T10:30:00Z"

    def test_map_without_reflectivity(self):
        """Should use context timestamp when no reflectivity data."""
        context = create_mock_context()

        mapper = TimestampsMapper()
        result = mapper.map(context)

        assert result is not None
        assert result["created_utc"] == "2025-01-15T12:00:00Z"
        assert "acquired_start_utc" not in result

    def test_map_with_string_timestamps(self):
        """Should handle ISO string timestamps."""
        context = create_mock_context(
            reflectivity={
                "created_at": "2025-01-15T12:00:00+00:00",
                "run_start": "2025-01-15T10:30:00Z",
            }
        )

        mapper = TimestampsMapper()
        result = mapper.map(context)

        assert result["created_utc"] == "2025-01-15T12:00:00Z"
        assert result["acquired_start_utc"] == "2025-01-15T10:30:00Z"


class TestAcquisitionSourceMapper:
    """Tests for AcquisitionSourceMapper."""

    def test_block_name(self):
        """Should return 'acquisition_source' as block name."""
        mapper = AcquisitionSourceMapper()
        assert mapper.block_name == "acquisition_source"

    def test_is_required(self):
        """Acquisition source block is required."""
        mapper = AcquisitionSourceMapper()
        assert mapper.is_required() is True

    def test_map_with_facility_data(self):
        """Should map facility information correctly."""
        context = create_mock_context(
            reflectivity={
                "facility": "SNS",
                "instrument_name": "REF_L",
                "laboratory": "ORNL",
            }
        )

        mapper = AcquisitionSourceMapper()
        result = mapper.map(context)

        assert result is not None
        assert result["source_type"] == "facility"
        assert result["facility"]["site"] == "SNS"
        assert result["facility"]["beamline"] == "REF_L"
        assert result["facility"]["endstation"] == "reflectometer"

    def test_map_without_reflectivity(self):
        """Should handle missing reflectivity data gracefully."""
        context = create_mock_context()

        mapper = AcquisitionSourceMapper()
        result = mapper.map(context)

        assert result is not None
        assert result["source_type"] == "facility"
        assert len(context.warnings) > 0

    def test_validate_valid_source_type(self):
        """Should validate correct source_type values."""
        mapper = AcquisitionSourceMapper()
        context = create_mock_context()

        valid_block = {"source_type": "facility"}
        assert mapper.validate(valid_block, context) is True

    def test_validate_invalid_source_type(self):
        """Should reject invalid source_type values."""
        mapper = AcquisitionSourceMapper()
        context = create_mock_context()

        invalid_block = {"source_type": "invalid_type"}
        assert mapper.validate(invalid_block, context) is False
        assert len(context.errors) > 0


class TestMeasurementMapper:
    """Tests for MeasurementMapper."""

    def test_block_name(self):
        """Should return 'measurement' as block name."""
        mapper = MeasurementMapper()
        assert mapper.block_name == "measurement"

    def test_map_with_reflectivity_data(self):
        """Should map Q/R/dR/dQ arrays to series/channels."""
        context = create_mock_context(
            reflectivity={
                "reflectivity": {
                    "q": [0.01, 0.02, 0.03],
                    "r": [0.95, 0.85, 0.70],
                    "dr": [0.01, 0.01, 0.02],
                    "dq": [0.001, 0.002, 0.003],
                    "measurement_geometry": "front reflection",
                    "reduction_version": "quicknxs 4.0.0",
                }
            }
        )

        mapper = MeasurementMapper()
        result = mapper.map(context)

        assert result is not None
        assert "series" in result
        assert "qc" in result

        series = result["series"][0]
        assert series["series_id"] == "reflectivity_profile"

        # Check independent variable (Q)
        iv = series["independent_variables"][0]
        assert iv["name"] == "q"
        assert iv["unit"] == "Å⁻¹"
        assert iv["values"] == [0.01, 0.02, 0.03]

        # Check channels
        channels = series["channels"]
        assert len(channels) == 3  # R, dR, dQ

        r_channel = channels[0]
        assert r_channel["name"] == "R"
        assert r_channel["role"] == "primary_signal"
        assert r_channel["values"] == [0.95, 0.85, 0.70]

        dr_channel = channels[1]
        assert dr_channel["name"] == "dR"
        assert dr_channel["role"] == "quality_monitor"

        dq_channel = channels[2]
        assert dq_channel["name"] == "dQ"
        assert dq_channel["role"] == "quality_monitor"

    def test_map_stores_metadata(self):
        """Should store Q stats in context metadata for descriptors."""
        context = create_mock_context(
            reflectivity={
                "reflectivity": {
                    "q": [0.01, 0.02, 0.03],
                    "r": [0.95, 0.85, 0.70],
                    "dr": [0.01, 0.01, 0.02],
                    "dq": [0.001, 0.002, 0.003],
                }
            }
        )

        mapper = MeasurementMapper()
        mapper.map(context)

        assert context.metadata["q_min"] == 0.01
        assert context.metadata["q_max"] == 0.03
        assert context.metadata["n_points"] == 3

    def test_map_without_reflectivity(self):
        """Should return None when no reflectivity data."""
        context = create_mock_context()

        mapper = MeasurementMapper()
        result = mapper.map(context)

        assert result is None
        assert len(context.warnings) > 0

    def test_map_with_missing_dr_dq(self):
        """Should handle missing dR and dQ arrays."""
        context = create_mock_context(
            reflectivity={
                "reflectivity": {
                    "q": [0.01, 0.02, 0.03],
                    "r": [0.95, 0.85, 0.70],
                    "dr": [],
                    "dq": [],
                }
            }
        )

        mapper = MeasurementMapper()
        result = mapper.map(context)

        assert result is not None
        channels = result["series"][0]["channels"]
        # Only R channel when dR and dQ are empty
        assert len(channels) == 1
        assert channels[0]["name"] == "R"


class TestDescriptorsMapper:
    """Tests for DescriptorsMapper."""

    def test_block_name(self):
        """Should return 'descriptors' as block name."""
        mapper = DescriptorsMapper()
        assert mapper.block_name == "descriptors"

    def test_is_required(self):
        """Descriptors block is required for evidence records."""
        mapper = DescriptorsMapper()
        assert mapper.is_required() is True

    def test_map_with_measurement_metadata(self):
        """Should generate descriptors from measurement metadata."""
        context = create_mock_context(
            reflectivity={"probe": "neutrons"}
        )
        # Simulate metadata populated by MeasurementMapper
        context.metadata["q_min"] = 0.01
        context.metadata["q_max"] = 0.30
        context.metadata["n_points"] = 150
        context.metadata["measurement_geometry"] = "front reflection"

        mapper = DescriptorsMapper()
        result = mapper.map(context)

        assert result is not None
        assert "policy" in result
        assert result["policy"]["requires_at_least_one"] is True

        outputs = result["outputs"]
        assert len(outputs) == 1

        output = outputs[0]
        assert "automated_extraction" in output["label"]
        assert output["generated_by"]["agent"] == "nr-isaac-format"

        descriptors = output["descriptors"]
        names = [d["name"] for d in descriptors]

        assert "q_range_min" in names
        assert "q_range_max" in names
        assert "total_points" in names
        assert "measurement_geometry" in names
        assert "probe_type" in names

    def test_map_without_metadata(self):
        """Should generate minimal descriptors when no metadata."""
        context = create_mock_context()

        mapper = DescriptorsMapper()
        result = mapper.map(context)

        assert result is not None
        descriptors = result["outputs"][0]["descriptors"]

        # Should have at least measurement_geometry (undetermined) and conversion_status
        assert len(descriptors) >= 1

    def test_descriptor_kinds(self):
        """Should use correct descriptor kinds."""
        context = create_mock_context()
        context.metadata["q_min"] = 0.01
        context.metadata["measurement_geometry"] = "back reflection"

        mapper = DescriptorsMapper()
        result = mapper.map(context)

        descriptors = result["outputs"][0]["descriptors"]
        desc_by_name = {d["name"]: d for d in descriptors}

        # Q values are absolute
        assert desc_by_name["q_range_min"]["kind"] == "absolute"

        # Geometry is categorical
        assert desc_by_name["measurement_geometry"]["kind"] == "categorical"

    def test_validate_valid_descriptors(self):
        """Should validate correct descriptor structure."""
        mapper = DescriptorsMapper()
        context = create_mock_context()

        valid_block = {
            "outputs": [{
                "label": "test",
                "generated_utc": "2025-01-15T12:00:00Z",
                "generated_by": {"agent": "test"},
                "descriptors": [{
                    "name": "test",
                    "kind": "absolute",
                    "source": "computed",
                    "value": 1.0,
                    "uncertainty": {"sigma": 0.1},
                }]
            }]
        }

        assert mapper.validate(valid_block, context) is True

    def test_validate_invalid_kind(self):
        """Should reject invalid descriptor kind."""
        mapper = DescriptorsMapper()
        context = create_mock_context()

        invalid_block = {
            "outputs": [{
                "label": "test",
                "generated_utc": "2025-01-15T12:00:00Z",
                "generated_by": {"agent": "test"},
                "descriptors": [{
                    "name": "test",
                    "kind": "invalid_kind",
                    "source": "computed",
                    "value": 1.0,
                    "uncertainty": {"sigma": 0.1},
                }]
            }]
        }

        assert mapper.validate(invalid_block, context) is False
