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

        # Check source_type (rev2: top-level, replaces acquisition_source)
        assert record["source_type"] == "facility"
        assert "acquisition_source" not in record

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
        # All descriptors must have uncertainty and valid source
        for d in descriptors:
            assert "uncertainty" in d
            assert d["source"] in ("auto", "manual", "imported")

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
        assert record["sample"]["sample_form"] == "film"
        assert record["sample"]["material"]["name"] == "Fe/Si"
        assert record["sample"]["material"]["formula"] == "Fe/Si"
        # No provenance in enum for plain mock data → key omitted
        assert "provenance" not in record["sample"]["material"]
        assert record["sample"]["geometry"]["layer_count"] == 2
        assert record["sample"]["geometry"]["total_thickness_nm"] == 510.0

    def test_sample_provenance_mapping(self):
        """Should map known provenance strings to schema enum values."""
        result = create_mock_result(
            reflectivity={"facility": "SNS"},
            sample={
                "main_composition": "CuO",
                "provenance": "commercial",
                "layers": [],
            },
        )
        writer = IsaacWriter()
        record = writer.to_isaac(result)
        assert record["sample"]["material"]["provenance"] == "commercial"

    def test_sample_provenance_normalised(self):
        """Should normalise non-standard provenance to closest enum value."""
        result = create_mock_result(
            reflectivity={"facility": "SNS"},
            sample={
                "main_composition": "CuO",
                "provenance": "model_fitted",
                "layers": [],
            },
        )
        writer = IsaacWriter()
        record = writer.to_isaac(result)
        assert record["sample"]["material"]["provenance"] == "theoretical"

    def test_with_environment_data(self):
        """Should map environment data to context block."""
        result = create_mock_result(
            reflectivity={"facility": "SNS"},
            environment={
                "temperature": 298.0,
                "pressure": 101325.0,
                "ambient_medium": "D2O",
                "description": "in_situ",
            },
        )

        writer = IsaacWriter()
        record = writer.to_isaac(result)

        assert "context" in record
        ctx = record["context"]
        assert ctx["temperature_K"] == 298.0
        assert ctx["pressure_Pa"] == 101325.0
        assert ctx["ambient_medium"] == "D2O"
        assert ctx["environment"] == "in_situ"  # enum value

    def test_context_classifies_electrochemical(self):
        """Should classify electrochemical descriptions as operando."""
        result = create_mock_result(
            reflectivity={"facility": "SNS"},
            environment={
                "description": "Electrochemical cell, THF electrolyte, steady-state OCV",
            },
        )
        writer = IsaacWriter()
        record = writer.to_isaac(result)
        ctx = record["context"]
        assert ctx["environment"] == "operando"
        assert ctx["description"] == "Electrochemical cell, THF electrolyte, steady-state OCV"

    def test_context_defaults_required_fields(self):
        """Should default temperature_K and environment when not provided."""
        result = create_mock_result(
            reflectivity={"facility": "SNS"},
            environment={"ambient_medium": "air"},
        )

        writer = IsaacWriter()
        record = writer.to_isaac(result)

        ctx = record["context"]
        assert ctx["temperature_K"] == 295.0  # default
        assert ctx["environment"] == "ex_situ"  # default classification

    def test_system_includes_technique(self):
        """Should include required technique field in system block."""
        result = create_mock_result(
            reflectivity={
                "facility": "SNS",
                "instrument_name": "REF_L",
                "reflectivity": {"measurement_geometry": "front reflection"},
            },
        )

        writer = IsaacWriter()
        record = writer.to_isaac(result)

        assert "system" in record
        assert record["system"]["technique"] == "neutron_reflectometry"
        assert record["system"]["domain"] == "experimental"

    def test_with_environment_description_no_env_record(self):
        """Should create context block from manifest environment_description."""
        result = create_mock_result(reflectivity={"facility": "SNS"})
        writer = IsaacWriter()
        record = writer.to_isaac(
            result, environment_description="Electrochemical cell, THF electrolyte"
        )

        assert "context" in record
        # Electrochemical → classified as operando
        assert record["context"]["environment"] == "operando"
        assert record["context"]["description"] == "Electrochemical cell, THF electrolyte"
        assert "temperature_K" in record["context"]  # required by schema

    def test_environment_description_does_not_override_existing(self):
        """Should not override existing environment description."""
        result = create_mock_result(
            reflectivity={"facility": "SNS"},
            environment={"description": "in_situ"},
        )
        writer = IsaacWriter()
        record = writer.to_isaac(
            result, environment_description="From manifest"
        )

        # Original description is "in_situ" which classifies directly
        assert record["context"]["environment"] == "in_situ"

    def test_context_description_from_manifest(self):
        """Should use context_description for the context.description field."""
        result = create_mock_result(reflectivity={"facility": "SNS"})
        writer = IsaacWriter()
        record = writer.to_isaac(
            result,
            environment_description="operando",
            context_description="Electrochemical cell, THF electrolyte, steady-state OCV",
        )

        ctx = record["context"]
        assert ctx["environment"] == "operando"
        assert ctx["description"] == "Electrochemical cell, THF electrolyte, steady-state OCV"

    def test_context_description_overrides_env_text(self):
        """Explicit context_description should take precedence over env description."""
        result = create_mock_result(
            reflectivity={"facility": "SNS"},
            environment={"description": "Electrochemical cell"},
        )
        writer = IsaacWriter()
        record = writer.to_isaac(
            result,
            context_description="Custom context note",
        )

        ctx = record["context"]
        assert ctx["description"] == "Custom context note"

    def test_raw_file_path_from_manifest(self):
        """Should include manifest raw_file_path in assets."""
        result = create_mock_result(
            reflectivity={"facility": "SNS", "reflectivity": {"q": [0.01], "r": [0.9]}},
        )
        writer = IsaacWriter()
        record = writer.to_isaac(
            result,
            raw_file_path="/SNS/REF_L/IPTS-34347/nexus/REF_L_218386.nxs.h5",
        )

        assert "assets" in record
        raw_assets = [a for a in record["assets"] if a["content_role"] == "raw_data_pointer"]
        assert len(raw_assets) == 1
        assert raw_assets[0]["uri"] == "/SNS/REF_L/IPTS-34347/nexus/REF_L_218386.nxs.h5"

    def test_raw_file_path_overrides_refl_metadata(self):
        """Manifest raw_file_path should take precedence over refl metadata."""
        result = create_mock_result(
            reflectivity={
                "facility": "SNS",
                "raw_file_path": "/old/path.nxs.h5",
                "reflectivity": {"q": [0.01], "r": [0.9]},
            },
        )
        writer = IsaacWriter()
        record = writer.to_isaac(
            result,
            raw_file_path="/new/manifest/path.nxs.h5",
        )

        raw_assets = [a for a in record["assets"] if a["content_role"] == "raw_data_pointer"]
        assert len(raw_assets) == 1
        assert raw_assets[0]["uri"] == "/new/manifest/path.nxs.h5"

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


class TestSampleFromManifest:
    """Tests for sample_name / sample_formula override from manifest."""

    def test_creates_sample_when_no_assembler_sample(self):
        """Should create sample block from manifest fields when result.sample is None."""
        result = create_mock_result(reflectivity={"facility": "SNS"})
        writer = IsaacWriter()
        record = writer.to_isaac(
            result, sample_name="Cu in THF on Si", sample_formula="THF | CuOx | Cu | Ti | Si"
        )

        assert "sample" in record
        assert record["sample"]["sample_form"] == "film"
        assert record["sample"]["material"]["name"] == "Cu in THF on Si"
        assert record["sample"]["material"]["formula"] == "THF | CuOx | Cu | Ti | Si"

    def test_overrides_unknown_composition(self):
        """Should replace 'Unknown' composition with manifest fields."""
        result = create_mock_result(
            reflectivity={"facility": "SNS"},
            sample={"main_composition": "Unknown", "layers": []},
        )
        writer = IsaacWriter()
        record = writer.to_isaac(
            result, sample_name="Cu in THF on Si", sample_formula="THF | CuOx | Cu | Ti | Si"
        )

        assert record["sample"]["material"]["name"] == "Cu in THF on Si"
        assert record["sample"]["material"]["formula"] == "THF | CuOx | Cu | Ti | Si"

    def test_does_not_override_valid_composition(self):
        """Should NOT override an existing valid material from the assembler."""
        result = create_mock_result(
            reflectivity={"facility": "SNS"},
            sample={"main_composition": "Fe/Si", "layers": []},
        )
        writer = IsaacWriter()
        record = writer.to_isaac(
            result, sample_name="Cu in THF on Si", sample_formula="THF | CuOx | Cu | Ti | Si"
        )

        # Assembler composition wins
        assert record["sample"]["material"]["name"] == "Fe/Si"

    def test_no_manifest_fields_no_sample(self):
        """Should not create sample block when no manifest sample fields and no assembler sample."""
        result = create_mock_result(reflectivity={"facility": "SNS"})
        writer = IsaacWriter()
        record = writer.to_isaac(result, sample_name=None, sample_formula=None)

        assert "sample" not in record

    def test_name_only_uses_name_for_both(self):
        """When only sample_name is given, use it for both name and formula."""
        result = create_mock_result(reflectivity={"facility": "SNS"})
        writer = IsaacWriter()
        record = writer.to_isaac(result, sample_name="Cu in THF on Si")

        assert record["sample"]["material"]["name"] == "Cu in THF on Si"
        assert record["sample"]["material"]["formula"] == "Cu in THF on Si"

    def test_formula_only_uses_formula_for_both(self):
        """When only sample_formula is given, use it for both name and formula."""
        result = create_mock_result(reflectivity={"facility": "SNS"})
        writer = IsaacWriter()
        record = writer.to_isaac(result, sample_formula="THF | CuOx | Cu | Ti | Si")

        assert record["sample"]["material"]["name"] == "THF | CuOx | Cu | Ti | Si"
        assert record["sample"]["material"]["formula"] == "THF | CuOx | Cu | Ti | Si"
