"""
Golden record comparison tests.

Validates converter output against known-good ISAAC record examples.
"""

import pytest

from nr_isaac_format.converter import IsaacRecordConverter

from .fixtures import (
    create_full_assembly,
    create_minimal_assembly,
    GOLDEN_RECORD_FULL,
    GOLDEN_RECORD_MINIMAL,
)
from .fixtures.golden_records import validate_against_golden


class TestGoldenRecordComparison:
    """Tests comparing output to golden records."""

    def test_minimal_record_structure(self):
        """Minimal record should match expected structure."""
        mock = create_minimal_assembly()
        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(mock)

        differences = validate_against_golden(
            conversion.record, GOLDEN_RECORD_MINIMAL, strict=False
        )

        # Should have no structural differences
        assert len([d for d in differences if "Missing" in d]) == 0, \
            f"Missing blocks: {differences}"

    def test_full_record_has_all_blocks(self):
        """Full record should include core required blocks."""
        mock = create_full_assembly()
        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(mock)

        record = conversion.record

        # Check required blocks are present
        required_blocks = [
            "timestamps",
            "acquisition_source",
            "measurement",
            "descriptors",
        ]

        for block in required_blocks:
            assert block in record, f"Missing required block: {block}"
            assert record[block] is not None, f"Block is None: {block}"

        # Check optional blocks that should be present with full data
        optional_expected = ["sample", "system", "assets"]
        for block in optional_expected:
            assert block in record, f"Missing expected optional block: {block}"

    def test_timestamps_format(self):
        """Timestamps should be ISO 8601 format."""
        mock = create_full_assembly()
        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(mock)

        timestamps = conversion.record.get("timestamps", {})

        # Check created_utc format
        created = timestamps.get("created_utc", "")
        assert "T" in str(created), "created_utc should be ISO format"

    def test_measurement_series_structure(self):
        """Measurement series should have correct structure."""
        mock = create_full_assembly()
        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(mock)

        measurement = conversion.record.get("measurement", {})
        series = measurement.get("series", [])

        assert len(series) > 0, "Should have at least one series"

        for s in series:
            assert "series_id" in s, "Series needs series_id"
            # Check for channels or independent_variables (schema may vary)
            has_data = "channels" in s or "independent_variables" in s
            assert has_data, "Series needs channels or independent_variables"

    def test_sample_material_structure(self):
        """Sample material should have name and formula."""
        mock = create_full_assembly()
        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(mock)

        sample = conversion.record.get("sample", {})

        if sample:
            assert "sample_form" in sample, "Sample needs sample_form"

            material = sample.get("material", {})
            if material:
                assert "name" in material or "formula" in material, \
                    "Material needs name or formula"

    def test_system_domain_value(self):
        """System domain should be valid enum value."""
        mock = create_full_assembly()
        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(mock)

        system = conversion.record.get("system", {})

        if system:
            domain = system.get("domain")
            valid_domains = {"experimental", "simulated", "hybrid"}
            assert domain in valid_domains, f"Invalid domain: {domain}"

    def test_assets_content_roles(self):
        """Assets should have valid content_role values."""
        mock = create_full_assembly()
        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(mock)

        assets = conversion.record.get("assets", [])

        valid_roles = {
            "raw_data_pointer",
            "reduction_product",
            "processing_recipe",
            "input_structure",
            "metadata_snapshot",
            "supplementary_image",
            "other",
        }

        for asset in assets:
            role = asset.get("content_role")
            assert role in valid_roles, f"Invalid content_role: {role}"

    def test_assets_have_required_fields(self):
        """Assets should have all required fields."""
        mock = create_full_assembly()
        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(mock)

        assets = conversion.record.get("assets", [])

        for asset in assets:
            assert "asset_id" in asset, "Asset needs asset_id"
            assert "content_role" in asset, "Asset needs content_role"
            assert "uri" in asset, "Asset needs uri"
            assert "sha256" in asset, "Asset needs sha256"

    def test_descriptors_have_required_fields(self):
        """Descriptors block should have expected structure."""
        mock = create_full_assembly()
        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(mock)

        descriptors = conversion.record.get("descriptors", {})

        # Descriptors may be a dict with policy/outputs or a list
        if isinstance(descriptors, dict):
            # New schema format with policy and outputs
            if "outputs" in descriptors:
                for output in descriptors["outputs"]:
                    assert "descriptors" in output or "label" in output, \
                        "Output needs descriptors or label"
        elif isinstance(descriptors, list):
            # Old format - list of descriptors
            for desc in descriptors:
                assert "descriptor_id" in desc or "name" in desc, \
                    "Descriptor needs descriptor_id or name"

    def test_context_required_fields(self):
        """Context should have required environment and temperature_K."""
        mock = create_full_assembly()
        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(mock)

        context = conversion.record.get("context", {})

        if context:
            assert "environment" in context, "Context needs environment"
            assert "temperature_K" in context, "Context needs temperature_K"
            assert isinstance(context["temperature_K"], (int, float)), \
                "temperature_K should be numeric"


class TestRecordIdFormat:
    """Tests for record ID format compliance."""

    def test_record_id_is_ulid(self):
        """Record ID should be valid ULID format."""
        from nr_isaac_format.ulid import validate_ulid

        mock = create_minimal_assembly()
        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(mock)

        assert validate_ulid(conversion.record_id), \
            f"Invalid ULID: {conversion.record_id}"

    def test_record_id_is_26_chars(self):
        """Record ID should be exactly 26 characters."""
        mock = create_minimal_assembly()
        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(mock)

        assert len(conversion.record_id) == 26

    def test_record_id_matches_in_record(self):
        """Record ID in result should match record_id field."""
        mock = create_minimal_assembly()
        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(mock)

        assert conversion.record_id == conversion.record["record_id"]


class TestVersionCompliance:
    """Tests for ISAAC version compliance."""

    def test_isaac_version_is_1_0(self):
        """ISAAC record version should be 1.0."""
        mock = create_minimal_assembly()
        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(mock)

        assert conversion.record["isaac_record_version"] == "1.0"

    def test_record_type_is_evidence(self):
        """Record type should be 'evidence' for measurement data."""
        mock = create_minimal_assembly()
        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(mock)

        assert conversion.record["record_type"] == "evidence"

    def test_record_domain_is_characterization(self):
        """Record domain should be 'characterization'."""
        mock = create_minimal_assembly()
        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(mock)

        assert conversion.record["record_domain"] == "characterization"
