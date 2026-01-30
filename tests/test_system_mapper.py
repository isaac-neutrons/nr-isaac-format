"""Tests for SystemMapper."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from nr_isaac_format.mappers import MapperContext, SystemMapper


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

    return MapperContext(
        result=mock_result,
        record_id="01HV9Z0ABCDEF123456789XYZ",
        created_utc=datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def mapper():
    """Create a SystemMapper instance."""
    return SystemMapper()


@pytest.fixture
def reflectivity_data():
    """Reflectivity record data with system info."""
    return {
        "facility": "SNS",
        "laboratory": "ORNL",
        "instrument_name": "REF_L",
        "probe": "neutrons",
        "technique": "reflectometry",
        "technique_description": "Specular neutron reflectometry",
        "is_simulated": False,
        "reflectivity": {
            "measurement_geometry": "front reflection",
            "reduction_version": "mr_reduction v2.0",
        },
    }


class TestSystemMapper:
    """Tests for SystemMapper."""

    def test_block_name(self, mapper):
        """Test block name is 'system'."""
        assert mapper.block_name == "system"

    def test_not_required(self, mapper):
        """Test system block is optional."""
        assert not mapper.is_required()

    def test_map_with_reflectivity(self, mapper, reflectivity_data):
        """Test mapping system data from reflectivity."""
        context = create_mock_context(reflectivity=reflectivity_data)

        result = mapper.map(context)

        assert result is not None
        assert result["domain"] == "experimental"

    def test_map_facility_block(self, mapper, reflectivity_data):
        """Test facility sub-block is built correctly."""
        context = create_mock_context(reflectivity=reflectivity_data)

        result = mapper.map(context)

        assert "facility" in result
        facility = result["facility"]
        assert facility["facility_name"] == "SNS"
        assert facility["organization"] == "ORNL"
        assert facility["beamline"] == "REF_L"

    def test_map_instrument_block(self, mapper, reflectivity_data):
        """Test instrument sub-block is built correctly."""
        context = create_mock_context(reflectivity=reflectivity_data)

        result = mapper.map(context)

        assert "instrument" in result
        instrument = result["instrument"]
        assert instrument["instrument_type"] == "beamline_endstation"
        assert instrument["instrument_name"] == "REF_L"
        assert instrument["vendor_or_project"] == "ORNL"

    def test_map_configuration_block(self, mapper, reflectivity_data):
        """Test configuration sub-block is built correctly."""
        context = create_mock_context(reflectivity=reflectivity_data)

        result = mapper.map(context)

        assert "configuration" in result
        config = result["configuration"]
        assert config["measurement_geometry"] == "front reflection"
        assert config["probe"] == "neutrons"
        assert config["technique"] == "reflectometry"

    def test_map_simulated_data(self, mapper):
        """Test domain is computational for simulated data."""
        reflectivity = {
            "facility": "Virtual",
            "instrument_name": "Simulation",
            "is_simulated": True,
            "probe": "neutrons",
        }
        context = create_mock_context(reflectivity=reflectivity)

        result = mapper.map(context)

        assert result["domain"] == "computational"

    def test_map_no_reflectivity(self, mapper):
        """Test returns None when no reflectivity data."""
        context = create_mock_context()

        result = mapper.map(context)
        assert result is None

    def test_validate_valid_block(self, mapper):
        """Test validation passes for valid block."""
        block = {
            "domain": "experimental",
            "facility": {"facility_name": "SNS"},
            "configuration": {"probe": "neutrons"},
        }
        context = create_mock_context()

        assert mapper.validate(block, context)
        assert not context.has_errors

    def test_validate_missing_domain(self, mapper):
        """Test validation fails when domain is missing."""
        block = {
            "configuration": {"probe": "neutrons"},
        }
        context = create_mock_context()

        assert not mapper.validate(block, context)
        assert context.has_errors
        assert any("domain" in e for e in context.errors)

    def test_validate_invalid_domain(self, mapper):
        """Test validation fails for invalid domain value."""
        block = {
            "domain": "unknown",
            "configuration": {},
        }
        context = create_mock_context()

        assert not mapper.validate(block, context)
        assert context.has_errors

    def test_validate_nested_config(self, mapper):
        """Test validation fails for nested config objects."""
        block = {
            "domain": "experimental",
            "configuration": {
                "probe": "neutrons",
                "nested": {"not": "allowed"},
            },
        }
        context = create_mock_context()

        assert not mapper.validate(block, context)
        assert any("nested object" in e for e in context.errors)
