"""Tests for AssetsMapper."""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from nr_isaac_format.mappers import AssetsMapper, MapperContext


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
    """Create an AssetsMapper instance."""
    return AssetsMapper()


@pytest.fixture
def reflectivity_data():
    """Reflectivity record with file references."""
    return {
        "raw_file_path": "/data/raw/SNS/REF_L/12345.nxs",
        "reduced_file": "/data/reduced/REF_L_12345.ort",
        "reflectivity": {
            "source_file": "/data/processed/r_12345.h5",
        },
    }


class TestAssetsMapper:
    """Tests for AssetsMapper."""

    def test_block_name(self, mapper):
        """Test block name is 'assets'."""
        assert mapper.block_name == "assets"

    def test_not_required(self, mapper):
        """Test assets block is optional."""
        assert not mapper.is_required()

    def test_map_with_reflectivity_files(self, mapper, reflectivity_data):
        """Test mapping assets from reflectivity file references."""
        context = create_mock_context(reflectivity=reflectivity_data)

        result = mapper.map(context)

        assert result is not None
        assert isinstance(result, list)
        assert len(result) == 3  # raw, reduced, source

    def test_map_raw_file_asset(self, mapper, reflectivity_data):
        """Test raw file is mapped with correct role."""
        context = create_mock_context(reflectivity=reflectivity_data)

        result = mapper.map(context)

        raw_asset = next(a for a in result if a["content_role"] == "raw_data_pointer")
        assert raw_asset["uri"] == "file:///data/raw/SNS/REF_L/12345.nxs"
        assert raw_asset["format"] == "NeXus"
        assert "asset_id" in raw_asset
        assert "sha256" in raw_asset

    def test_map_reduced_file_asset(self, mapper, reflectivity_data):
        """Test reduced file is mapped with reduction_product role."""
        context = create_mock_context(reflectivity=reflectivity_data)

        result = mapper.map(context)

        processed_assets = [a for a in result if a["content_role"] == "reduction_product"]
        assert len(processed_assets) >= 1

        ort_asset = next(
            a for a in processed_assets if a["uri"].endswith(".ort")
        )
        assert ort_asset["format"] == "ORSO text reflectivity"
        assert "sha256" in ort_asset

    def test_map_infers_format_hdf5(self, mapper):
        """Test format inference for HDF5 files."""
        reflectivity = {
            "raw_file_path": "/data/file.hdf5",
        }
        context = create_mock_context(reflectivity=reflectivity)

        result = mapper.map(context)

        assert result[0]["format"] == "HDF5"

    def test_map_infers_format_parquet(self, mapper):
        """Test format inference for Parquet files."""
        reflectivity = {
            "raw_file_path": "/data/file.parquet",
        }
        context = create_mock_context(reflectivity=reflectivity)

        result = mapper.map(context)

        assert result[0]["format"] == "Parquet"

    def test_map_sample_file(self, mapper):
        """Test sample file is mapped as metadata_snapshot."""
        sample = {
            "sample_file": "/samples/sample_123.json",
        }
        context = create_mock_context(sample=sample)

        result = mapper.map(context)

        assert len(result) == 1
        assert result[0]["content_role"] == "metadata_snapshot"
        assert result[0]["format"] == "JSON"
        assert "sha256" in result[0]

    def test_map_environment_file(self, mapper):
        """Test environment file is mapped as metadata_snapshot."""
        environment = {
            "environment_file": "/env/env_config.xml",
        }
        context = create_mock_context(environment=environment)

        result = mapper.map(context)

        assert len(result) == 1
        assert result[0]["content_role"] == "metadata_snapshot"
        assert result[0]["format"] == "XML"
        assert "sha256" in result[0]

    def test_map_no_files(self, mapper):
        """Test returns None when no file references."""
        context = create_mock_context(
            reflectivity={},
            sample={},
            environment={},
        )

        result = mapper.map(context)
        assert result is None

    def test_map_generates_unique_asset_ids(self, mapper, reflectivity_data):
        """Test each asset gets a unique ID."""
        context = create_mock_context(reflectivity=reflectivity_data)

        result = mapper.map(context)

        asset_ids = [a["asset_id"] for a in result]
        assert len(asset_ids) == len(set(asset_ids))  # All unique

    def test_map_asset_id_contains_record_id(self, mapper, reflectivity_data):
        """Test asset IDs are based on record ID."""
        context = create_mock_context(reflectivity=reflectivity_data)

        result = mapper.map(context)

        for asset in result:
            assert asset["asset_id"].startswith(context.record_id)

    def test_validate_valid_block(self, mapper):
        """Test validation passes for valid assets array."""
        block = [
            {
                "asset_id": "01HV9Z0ABCDEF123456789XYZ-A001",
                "content_role": "raw_data_pointer",
                "uri": "file:///data/file.nxs",
                "sha256": "abc123def456",
            },
        ]
        context = create_mock_context()

        assert mapper.validate(block, context)

    def test_validate_missing_asset_id(self, mapper):
        """Test validation fails when asset_id is missing."""
        block = [
            {
                "content_role": "raw_data_pointer",
                "uri": "file:///data/file.nxs",
                "sha256": "abc123",
            },
        ]
        context = create_mock_context()

        assert not mapper.validate(block, context)
        assert any("asset_id" in e for e in context.errors)

    def test_validate_invalid_content_role(self, mapper):
        """Test validation fails for invalid content_role."""
        block = [
            {
                "asset_id": "01HV9Z0ABCDEF123456789XYZ-A001",
                "content_role": "unknown",
                "uri": "file:///data/file.nxs",
                "sha256": "abc123",
            },
        ]
        context = create_mock_context()

        assert not mapper.validate(block, context)
        assert any("content_role" in e for e in context.errors)

    def test_validate_missing_uri(self, mapper):
        """Test validation fails when uri is missing."""
        block = [
            {
                "asset_id": "01HV9Z0ABCDEF123456789XYZ-A001",
                "content_role": "raw_data_pointer",
                "sha256": "abc123",
            },
        ]
        context = create_mock_context()

        assert not mapper.validate(block, context)
        assert any("uri" in e for e in context.errors)

    def test_validate_missing_sha256(self, mapper):
        """Test validation fails when sha256 is missing."""
        block = [
            {
                "asset_id": "01HV9Z0ABCDEF123456789XYZ-A001",
                "content_role": "raw_data_pointer",
                "uri": "file:///data/file.nxs",
            },
        ]
        context = create_mock_context()

        assert not mapper.validate(block, context)
        assert any("sha256" in e for e in context.errors)

    def test_validate_not_array(self, mapper):
        """Test validation fails when block is not an array."""
        block = {"asset_id": "123", "path": "/file"}
        context = create_mock_context()

        assert not mapper.validate(block, context)
        assert any("array" in e for e in context.errors)
