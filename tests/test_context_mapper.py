"""Tests for ContextMapper."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from nr_isaac_format.mappers import ContextMapper, MapperContext


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
    """Create a ContextMapper instance."""
    return ContextMapper()


@pytest.fixture
def environment_data():
    """Environment record data with required fields."""
    return {
        "temperature_value_kelvin": 298.15,
        "ambient_medium": "air",
        "pressure_value_pa": 101325,
        "humidity_value_percent": 45.0,
        "magnetic_field_value_tesla": 0.0,
        "environment_description": "Room temperature measurement",
    }


@pytest.fixture
def reflectivity_data():
    """Reflectivity record with experiment info."""
    return {
        "experiment_identifier": "IPTS-12345",
        "experiment_title": "Polymer characterization",
        "sample_name": "PS-123",
        "sample_description": "Polystyrene thin film",
        "acquired_timestamp": "2024-01-15T10:30:00Z",
    }


class TestContextMapper:
    """Tests for ContextMapper."""

    def test_block_name(self, mapper):
        """Test block name is 'context'."""
        assert mapper.block_name == "context"

    def test_not_required(self, mapper):
        """Test context block is optional."""
        assert not mapper.is_required()

    def test_map_with_environment(self, mapper, environment_data):
        """Test mapping context with environment data."""
        context = create_mock_context(environment=environment_data)

        result = mapper.map(context)

        assert result is not None
        assert "environment" in result
        assert "temperature_K" in result

    def test_map_required_fields(self, mapper, environment_data):
        """Test required fields are mapped correctly."""
        context = create_mock_context(environment=environment_data)

        result = mapper.map(context)

        assert result["environment"] == "air"
        assert result["temperature_K"] == 298.15

    def test_map_experiment_info(self, mapper, reflectivity_data, environment_data):
        """Test experiment info is mapped from reflectivity."""
        context = create_mock_context(
            reflectivity=reflectivity_data,
            environment=environment_data,
        )

        result = mapper.map(context)

        assert "experiment_id" in result
        assert result["experiment_id"] == "IPTS-12345"
        assert result["experiment_title"] == "Polymer characterization"

    def test_map_notes(self, mapper, reflectivity_data, environment_data):
        """Test notes are built from descriptions."""
        context = create_mock_context(
            reflectivity=reflectivity_data,
            environment=environment_data,
        )

        result = mapper.map(context)

        assert "notes" in result
        assert "Polystyrene thin film" in result["notes"]
        assert "Room temperature" in result["notes"]

    def test_map_no_data(self, mapper):
        """Test returns None when no context data available."""
        context = create_mock_context()

        result = mapper.map(context)
        assert result is None

    def test_map_missing_temperature(self, mapper):
        """Test returns None when temperature is missing."""
        environment = {
            "ambient_medium": "air",
        }
        context = create_mock_context(environment=environment)

        result = mapper.map(context)
        # Should return None because temperature_K is required
        assert result is None

    def test_map_missing_environment(self, mapper):
        """Test returns None when environment string is missing."""
        environment = {
            "temperature_value_kelvin": 298.15,
        }
        context = create_mock_context(environment=environment)

        result = mapper.map(context)
        # Should return None because environment is required
        assert result is None

    def test_map_extra_conditions(self, mapper, environment_data):
        """Test extra conditions are included."""
        context = create_mock_context(environment=environment_data)

        result = mapper.map(context)

        assert result["pressure_Pa"] == 101325
        assert result["humidity_percent"] == 45.0

    def test_map_fallback_experiment_title(self, mapper, environment_data):
        """Test experiment title falls back to sample name."""
        reflectivity = {
            "sample_name": "Gold Film",
        }
        context = create_mock_context(
            reflectivity=reflectivity,
            environment=environment_data,
        )

        result = mapper.map(context)

        assert "Measurement of Gold Film" in result["experiment_title"]

    def test_validate_valid_block(self, mapper):
        """Test validation passes for valid block."""
        block = {
            "environment": "air",
            "temperature_K": 298.0,
        }
        context = create_mock_context()

        assert mapper.validate(block, context)
        assert not context.has_errors

    def test_validate_missing_environment(self, mapper):
        """Test validation fails when environment is missing."""
        block = {
            "temperature_K": 298.0,
        }
        context = create_mock_context()

        assert not mapper.validate(block, context)
        assert any("environment" in e for e in context.errors)

    def test_validate_missing_temperature(self, mapper):
        """Test validation fails when temperature_K is missing."""
        block = {
            "environment": "air",
        }
        context = create_mock_context()

        assert not mapper.validate(block, context)
        assert any("temperature_K" in e for e in context.errors)

    def test_validate_invalid_environment_type(self, mapper):
        """Test validation fails when environment is not a string."""
        block = {
            "environment": {"type": "air"},  # Should be string
            "temperature_K": 298.0,
        }
        context = create_mock_context()

        assert not mapper.validate(block, context)
        assert any("string" in e for e in context.errors)

    def test_validate_invalid_temperature_type(self, mapper):
        """Test validation fails when temperature is not numeric."""
        block = {
            "environment": "air",
            "temperature_K": "hot",  # Should be number
        }
        context = create_mock_context()

        assert not mapper.validate(block, context)
        assert any("number" in e for e in context.errors)
