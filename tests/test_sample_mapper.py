"""Tests for SampleMapper."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from nr_isaac_format.mappers import MapperContext, SampleMapper


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
    """Create a SampleMapper instance."""
    return SampleMapper()


@pytest.fixture
def sample_data():
    """Sample record data with layers."""
    return {
        "layers": [
            {
                "material": "Silicon",
                "formula": "Si",
                "thickness": 0,  # Substrate has "infinite" thickness
            },
            {
                "material": "Silicon Dioxide",
                "formula": "SiO2",
                "thickness": 15.0,
            },
            {
                "material": "Gold",
                "formula": "Au",
                "thickness": 100.0,
            },
        ],
        "main_composition": "Au on SiO2/Si",
        "description": "Gold thin film on silicon substrate",
    }


class TestSampleMapper:
    """Tests for SampleMapper."""

    def test_block_name(self, mapper):
        """Test block name is 'sample'."""
        assert mapper.block_name == "sample"

    def test_not_required(self, mapper):
        """Test sample block is optional."""
        assert not mapper.is_required()

    def test_map_with_sample_data(self, mapper, sample_data):
        """Test mapping sample with layers."""
        context = create_mock_context(sample=sample_data)

        result = mapper.map(context)

        assert result is not None
        assert "sample_description" in result
        assert result["sample_description"] == "Gold thin film on silicon substrate"

    def test_map_builds_material(self, mapper, sample_data):
        """Test that material block is built from composition."""
        context = create_mock_context(sample=sample_data)

        result = mapper.map(context)

        assert "material" in result
        material = result["material"]
        assert material["name"] == "Au on SiO2/Si"
        assert material["formula"] == "Au on SiO2/Si"

    def test_map_builds_composition(self, mapper, sample_data):
        """Test that composition includes layer info."""
        context = create_mock_context(sample=sample_data)

        result = mapper.map(context)

        assert "composition" in result
        # Composition tracks thickness fractions by material

    def test_map_builds_geometry(self, mapper, sample_data):
        """Test that geometry is built from layers."""
        context = create_mock_context(sample=sample_data)

        result = mapper.map(context)

        assert "geometry" in result
        geometry = result["geometry"]
        assert "layer_count" in geometry

    def test_map_sample_form(self, mapper, sample_data):
        """Test sample form is set to thin_film."""
        context = create_mock_context(sample=sample_data)

        result = mapper.map(context)

        assert result["sample_form"] == "thin_film"

    def test_map_no_sample_data(self, mapper):
        """Test returns None when no sample data."""
        context = create_mock_context()

        result = mapper.map(context)
        assert result is None

    def test_map_empty_sample(self, mapper):
        """Test returns None when sample has no useful data."""
        context = create_mock_context(sample={})

        result = mapper.map(context)
        assert result is None

    def test_validate_valid_block(self, mapper):
        """Test validation passes for valid block."""
        block = {
            "sample_form": "thin_film",
            "sample_description": "Test sample",
            "material": {"name": "Gold", "formula": "Au"},
        }
        context = create_mock_context()

        assert mapper.validate(block, context)
        assert not context.has_errors

    def test_map_single_layer(self, mapper):
        """Test mapping with single layer."""
        sample = {
            "layers": [
                {
                    "material": "Polymer",
                    "formula": "C8H8",
                    "thickness": 500.0,
                }
            ],
            "main_composition": "Polymer",
        }
        context = create_mock_context(sample=sample)

        result = mapper.map(context)

        assert result is not None
        assert result["geometry"]["layer_count"] == 1

    def test_map_from_reflectivity_fallback(self, mapper):
        """Test sample info can come from reflectivity as fallback."""
        reflectivity = {
            "sample_name": "Test Sample",
            "sample_description": "Description from reflectivity",
        }
        context = create_mock_context(reflectivity=reflectivity)

        result = mapper.map(context)

        assert result is not None
        assert result["sample_description"] == "Description from reflectivity"

    def test_validate_missing_sample_form(self, mapper):
        """Test validation fails when sample_form is missing."""
        block = {
            "material": {"material_name": "Gold"},
        }
        context = create_mock_context()

        assert not mapper.validate(block, context)
        assert any("sample_form" in e for e in context.errors)
