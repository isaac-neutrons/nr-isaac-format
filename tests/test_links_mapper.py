"""Tests for LinksMapper."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from nr_isaac_format.mappers import LinksMapper, MapperContext


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
    """Create a LinksMapper instance."""
    return LinksMapper()


class TestLinksMapper:
    """Tests for LinksMapper."""

    def test_block_name(self, mapper):
        """Test block name is 'links'."""
        assert mapper.block_name == "links"

    def test_not_required(self, mapper):
        """Test links block is optional."""
        assert not mapper.is_required()

    def test_map_parent_record(self, mapper):
        """Test parent record ID creates derived_from link."""
        reflectivity = {
            "parent_record_id": "01HV8Z0PARENT123456789XYZ",
        }
        context = create_mock_context(reflectivity=reflectivity)

        result = mapper.map(context)

        assert result is not None
        assert len(result) == 1
        link = result[0]
        assert link["link_type"] == "derived_from"
        assert link["target_record_id"] == "01HV8Z0PARENT123456789XYZ"

    def test_map_collection(self, mapper):
        """Test collection ID creates part_of link."""
        reflectivity = {
            "collection_id": "COLLECTION-2024-001",
        }
        context = create_mock_context(reflectivity=reflectivity)

        result = mapper.map(context)

        assert len(result) == 1
        assert result[0]["link_type"] == "part_of"
        assert result[0]["target_record_id"] == "COLLECTION-2024-001"

    def test_map_doi(self, mapper):
        """Test DOI creates cites link."""
        reflectivity = {
            "doi": "10.1234/example.doi",
        }
        context = create_mock_context(reflectivity=reflectivity)

        result = mapper.map(context)

        assert len(result) == 1
        assert result[0]["link_type"] == "cites"
        assert result[0]["target_record_id"] == "10.1234/example.doi"

    def test_map_sample_record(self, mapper):
        """Test sample record ID creates related_to link."""
        sample = {
            "sample_record_id": "01HV8Z0SAMPLE123456789XYZ",
        }
        context = create_mock_context(sample=sample)

        result = mapper.map(context)

        assert len(result) == 1
        assert result[0]["link_type"] == "related_to"
        assert result[0]["target_record_id"] == "01HV8Z0SAMPLE123456789XYZ"

    def test_map_multiple_links(self, mapper):
        """Test multiple link types from single record."""
        reflectivity = {
            "parent_record_id": "01HV8Z0PARENT123456789XYZ",
            "collection_id": "COLLECTION-2024",
            "doi": "10.1234/paper",
        }
        context = create_mock_context(reflectivity=reflectivity)

        result = mapper.map(context)

        assert len(result) == 3
        link_types = {link["link_type"] for link in result}
        assert link_types == {"derived_from", "part_of", "cites"}

    def test_map_no_links(self, mapper):
        """Test returns None when no link data available."""
        context = create_mock_context(
            reflectivity={},
            sample={},
            environment={},
        )

        result = mapper.map(context)
        assert result is None

    def test_map_all_none(self, mapper):
        """Test returns None when all records are None."""
        context = create_mock_context()

        result = mapper.map(context)
        assert result is None

    def test_validate_valid_block(self, mapper):
        """Test validation passes for valid links array."""
        block = [
            {
                "link_type": "derived_from",
                "target_record_id": "01HV8Z0PARENT123456789XYZ",
                "description": "Parent record",
            },
        ]
        context = create_mock_context()

        assert mapper.validate(block, context)
        assert not context.has_errors

    def test_validate_missing_link_type(self, mapper):
        """Test validation fails when link_type is missing."""
        block = [
            {
                "target_record_id": "01HV8Z0PARENT123456789XYZ",
            },
        ]
        context = create_mock_context()

        assert not mapper.validate(block, context)
        assert any("link_type" in e for e in context.errors)

    def test_validate_missing_target(self, mapper):
        """Test validation fails when target_record_id is missing."""
        block = [
            {
                "link_type": "derived_from",
            },
        ]
        context = create_mock_context()

        assert not mapper.validate(block, context)
        assert any("target_record_id" in e for e in context.errors)

    def test_validate_not_array(self, mapper):
        """Test validation fails when block is not an array."""
        block = {"link_type": "derived_from", "target": "123"}
        context = create_mock_context()

        assert not mapper.validate(block, context)
        assert any("array" in e for e in context.errors)

    def test_validate_unknown_link_type_warning(self, mapper):
        """Test unknown link type generates warning (not error)."""
        block = [
            {
                "link_type": "custom_relationship",
                "target_record_id": "123",
            },
        ]
        context = create_mock_context()

        # Should still validate (warning, not error)
        assert mapper.validate(block, context)
        assert context.has_warnings
        assert any("may not be recognized" in w for w in context.warnings)
