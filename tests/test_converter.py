"""
Tests for the ISAAC Record Converter.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from nr_isaac_format.converter import ConversionResult, IsaacRecordConverter, ISAAC_VERSION
from nr_isaac_format.mappers.base import Mapper, MapperContext
from nr_isaac_format.ulid import generate_ulid, validate_ulid


class TestULID:
    """Tests for ULID generation and validation."""

    def test_generate_ulid_format(self):
        """Generated ULID should be 26 uppercase alphanumeric characters."""
        ulid = generate_ulid()

        assert len(ulid) == 26
        assert ulid.isupper()
        assert all(c.isalnum() for c in ulid)

    def test_generate_ulid_with_timestamp(self):
        """ULID generation should accept a timestamp."""
        ts = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        ulid = generate_ulid(ts)

        assert len(ulid) == 26
        assert validate_ulid(ulid)

    def test_validate_ulid_valid(self):
        """Valid ULIDs should pass validation."""
        valid_ulids = [
            "01JFH3Q8Z1Q9F0XG3V7N4K2M8C",
            "00000000000000000000000000",
            "7ZZZZZZZZZZZZZZZZZZZZZZZZZ",
        ]
        for ulid in valid_ulids:
            assert validate_ulid(ulid), f"Should be valid: {ulid}"

    def test_validate_ulid_invalid_length(self):
        """ULIDs with wrong length should fail validation."""
        assert not validate_ulid("01JFH3Q8Z1")  # Too short
        assert not validate_ulid("01JFH3Q8Z1Q9F0XG3V7N4K2M8CABC")  # Too long

    def test_validate_ulid_invalid_characters(self):
        """ULIDs with invalid characters should fail validation."""
        assert not validate_ulid("01jfh3q8z1q9f0xg3v7n4k2m8c")  # Lowercase
        assert not validate_ulid("01JFH3Q8Z1Q9F0XG3V7N4K2M8!")  # Special char


class TestMapperContext:
    """Tests for MapperContext."""

    def test_context_creation(self):
        """Context should be created with AssemblyResult."""
        mock_result = MagicMock()
        mock_result.reflectivity = {"id": "test"}
        mock_result.sample = None
        mock_result.environment = None

        context = MapperContext(
            result=mock_result,
            record_id="01JFH3Q8Z1Q9F0XG3V7N4K2M8C",
        )

        assert context.reflectivity == {"id": "test"}
        assert context.sample is None
        assert context.environment is None
        assert len(context.warnings) == 0
        assert len(context.errors) == 0

    def test_context_add_warning(self):
        """Context should accumulate warnings."""
        mock_result = MagicMock()
        context = MapperContext(
            result=mock_result,
            record_id="01JFH3Q8Z1Q9F0XG3V7N4K2M8C",
        )

        context.add_warning("Test warning 1")
        context.add_warning("Test warning 2")

        assert len(context.warnings) == 2
        assert "Test warning 1" in context.warnings

    def test_context_add_error(self):
        """Context should accumulate errors."""
        mock_result = MagicMock()
        context = MapperContext(
            result=mock_result,
            record_id="01JFH3Q8Z1Q9F0XG3V7N4K2M8C",
        )

        context.add_error("Test error")

        assert len(context.errors) == 1
        assert "Test error" in context.errors


class TestIsaacRecordConverter:
    """Tests for IsaacRecordConverter."""

    def test_converter_creation(self):
        """Converter should be created with default settings."""
        converter = IsaacRecordConverter()

        assert converter.validate_output is True
        assert isinstance(converter.mappers, list)

    def test_converter_builds_root_record(self):
        """Converter should build correct root-level fields."""
        mock_result = MagicMock()
        mock_result.reflectivity = {"id": "test"}
        mock_result.sample = None
        mock_result.environment = None
        mock_result.warnings = []
        mock_result.errors = []
        mock_result.needs_review = {}

        converter = IsaacRecordConverter(validate_output=False)
        conversion = converter.convert(mock_result)

        assert conversion.record["isaac_record_version"] == ISAAC_VERSION
        assert conversion.record["record_type"] == "evidence"
        assert conversion.record["record_domain"] == "characterization"
        assert validate_ulid(conversion.record["record_id"])

    def test_converter_uses_provided_record_id(self):
        """Converter should use provided record_id if given."""
        mock_result = MagicMock()
        mock_result.reflectivity = None
        mock_result.sample = None
        mock_result.environment = None
        mock_result.warnings = []
        mock_result.errors = []
        mock_result.needs_review = {}

        converter = IsaacRecordConverter(validate_output=False)
        custom_id = "01JFH3Q8Z1Q9F0XG3V7N4K2M8C"
        conversion = converter.convert(mock_result, record_id=custom_id)

        assert conversion.record_id == custom_id
        assert conversion.record["record_id"] == custom_id


class TestConversionResult:
    """Tests for ConversionResult."""

    def test_conversion_result_properties(self):
        """ConversionResult should report warnings and errors correctly."""
        result = ConversionResult(
            record={"test": "data"},
            record_id="01JFH3Q8Z1Q9F0XG3V7N4K2M8C",
            warnings=["warning1"],
            errors=[],
        )

        assert result.has_warnings
        assert not result.has_errors
        assert result.is_valid

    def test_conversion_result_to_json(self):
        """ConversionResult should serialize to JSON."""
        result = ConversionResult(
            record={"isaac_record_version": "1.0", "record_id": "TEST"},
            record_id="TEST",
        )

        json_str = result.to_json()

        assert '"isaac_record_version": "1.0"' in json_str
        assert '"record_id": "TEST"' in json_str

    def test_conversion_result_to_json_compact(self):
        """ConversionResult should serialize to compact JSON."""
        result = ConversionResult(
            record={"isaac_record_version": "1.0", "record_id": "TEST"},
            record_id="TEST",
        )

        json_str = result.to_json(indent=None)

        # Compact JSON should not have newlines
        assert "\n" not in json_str

    def test_conversion_result_to_json_include_nulls(self):
        """ConversionResult should include nulls when specified."""
        result = ConversionResult(
            record={"field": "value", "null_field": None},
            record_id="TEST",
        )

        # Without include_nulls (default)
        json_without_nulls = result.to_json(include_nulls=False)
        assert "null_field" not in json_without_nulls

        # With include_nulls
        json_with_nulls = result.to_json(include_nulls=True)
        assert "null_field" in json_with_nulls
        assert "null" in json_with_nulls

    def test_conversion_result_removes_nested_nulls(self):
        """ConversionResult should remove nested nulls."""
        result = ConversionResult(
            record={
                "outer": {
                    "inner": "value",
                    "null_inner": None,
                },
                "list": [{"a": 1, "b": None}],
            },
            record_id="TEST",
        )

        json_str = result.to_json(include_nulls=False)

        assert "inner" in json_str
        assert "null_inner" not in json_str
        assert '"a": 1' in json_str or '"a":1' in json_str


class TestMapperBase:
    """Tests for abstract Mapper base class."""

    def test_mapper_abstract_methods(self):
        """Mapper should require implementation of abstract methods."""
        # Attempting to instantiate abstract class should fail
        with pytest.raises(TypeError):
            Mapper()

    def test_mapper_concrete_implementation(self):
        """Concrete mapper implementation should work."""

        class TestMapper(Mapper):
            @property
            def block_name(self) -> str:
                return "test_block"

            def map(self, context):
                return {"test": "value"}

        mapper = TestMapper()
        assert mapper.block_name == "test_block"
        assert mapper.is_required() is False  # Default

        mock_context = MagicMock()
        result = mapper.map(mock_context)
        assert result == {"test": "value"}
