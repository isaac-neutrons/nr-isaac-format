"""Tests for the minimal IsaacWriter."""

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nr_isaac_format.writer import IsaacWriter, write_isaac_record


def create_mock_result(
    reflectivity: dict | None = None,
    sample: dict | None = None,
    environment: dict | None = None,
    reduced_file: str | None = None,
):
    """Create a mock AssemblyResult for testing."""
    mock = MagicMock()
    mock.reflectivity = reflectivity
    mock.sample = sample
    mock.environment = environment
    mock.reduced_file = reduced_file
    mock.parquet_dir = None
    mock.model_file = None
    mock.warnings = []
    mock.errors = []
    return mock


class TestIsaacWriter:
    """Tests for IsaacWriter class."""

    def test_minimal_record(self):
        """Should create valid minimal ISAAC record."""
        result = create_mock_result()
        writer = IsaacWriter()
        record = writer.to_isaac(result)

        assert record["isaac_record_version"] == "1.0"
        assert record["record_type"] == "evidence"
        assert record["record_domain"] == "characterization"
        assert "record_id" in record
        assert len(record["record_id"]) == 26  # ULID length
        assert "timestamps" in record
        assert "created_utc" in record["timestamps"]

    def test_with_reflectivity_data(self):
        """Should map reflectivity data to measurement block."""
        result = create_mock_result(
            reflectivity={
                "facility": "SNS",
                "instrument_name": "REF_L",
                "run_start": datetime(2025, 1, 15, 10, 30, tzinfo=timezone.utc),
                "reflectivity": {
                    "q": [0.01, 0.02, 0.03],
                    "r": [0.95, 0.85, 0.70],
                    "dr": [0.01, 0.01, 0.02],
                    "dq": [0.001, 0.002, 0.003],
                    "measurement_geometry": "front reflection",
                },
            }
        )

        writer = IsaacWriter()
        record = writer.to_isaac(result)

        # Check acquisition_source
        acq = record["acquisition_source"]
        assert acq["source_type"] == "facility"
        assert acq["facility"]["site"] == "SNS"
        assert acq["facility"]["beamline"] == "REF_L"

        # Check measurement
        meas = record["measurement"]
        assert meas is not None
        series = meas["series"][0]
        assert series["series_id"] == "reflectivity_profile"
        assert series["independent_variables"][0]["name"] == "q"
        assert series["independent_variables"][0]["values"] == [0.01, 0.02, 0.03]

        channels = series["channels"]
        assert len(channels) == 3
        assert channels[0]["name"] == "R"
        assert channels[0]["role"] == "primary_signal"

        # Check descriptors
        desc = record["descriptors"]
        outputs = desc["outputs"][0]
        descriptors = outputs["descriptors"]
        names = [d["name"] for d in descriptors]
        assert "q_range_min" in names
        assert "q_range_max" in names
        assert "total_points" in names
        assert "measurement_geometry" in names

    def test_with_sample_data(self):
        """Should map sample data when present."""
        result = create_mock_result(
            reflectivity={"facility": "SNS"},
            sample={
                "main_composition": "Fe/Si",
                "layers": [
                    {"material": "Fe", "thickness": 10.0},
                    {"material": "Si", "thickness": 500.0},
                ],
            },
        )

        writer = IsaacWriter()
        record = writer.to_isaac(result)

        assert "sample" in record
        assert record["sample"]["material"]["name"] == "Fe/Si"
        assert record["sample"]["geometry"]["layer_count"] == 2
        assert record["sample"]["geometry"]["total_thickness_nm"] == 510.0

    def test_with_environment_data(self):
        """Should map environment data to context block."""
        result = create_mock_result(
            reflectivity={"facility": "SNS"},
            environment={
                "temperature": 298.0,
                "pressure": 101325.0,
                "ambient_medium": "D2O",
            },
        )

        writer = IsaacWriter()
        record = writer.to_isaac(result)

        assert "context" in record
        ctx = record["context"]
        assert ctx["temperature_K"] == 298.0
        assert ctx["pressure_Pa"] == 101325.0
        assert ctx["ambient_medium"] == "D2O"
        assert ctx["environment"] == "in_situ"

    def test_write_to_file(self, tmp_path):
        """Should write ISAAC record to JSON file."""
        result = create_mock_result(
            reflectivity={
                "facility": "SNS",
                "reflectivity": {"q": [0.01], "r": [0.95]},
            }
        )

        output_path = tmp_path / "output.json"
        writer = IsaacWriter()
        path = writer.write(result, output_path)

        assert path.exists()
        with open(path) as f:
            record = json.load(f)
        assert record["isaac_record_version"] == "1.0"

    def test_write_with_output_dir(self, tmp_path):
        """Should write to output_dir when no path specified."""
        result = create_mock_result()

        writer = IsaacWriter(output_dir=tmp_path)
        path = writer.write(result)

        assert path == tmp_path / "isaac_record.json"
        assert path.exists()


class TestConvenienceFunction:
    """Tests for write_isaac_record convenience function."""

    def test_write_isaac_record(self, tmp_path):
        """Should write record using convenience function."""
        result = create_mock_result(
            reflectivity={"facility": "SNS", "reflectivity": {"q": [0.01], "r": [0.9]}}
        )

        output_path = tmp_path / "record.json"
        path = write_isaac_record(result, output_path)

        assert path.exists()
        with open(path) as f:
            record = json.load(f)
        assert "record_id" in record
