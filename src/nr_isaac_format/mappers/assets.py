"""
Assets block mapper for ISAAC records.

Maps file references from data-assembler to the ISAAC assets array.
"""

import hashlib
import logging
from pathlib import Path
from typing import Any, Optional

from ..constants import ContentRole
from .base import Mapper, MapperContext

logger = logging.getLogger(__name__)

# Set of valid content roles from enum
VALID_CONTENT_ROLES = {role.value for role in ContentRole}


class AssetsMapper(Mapper):
    """
    Maps file references from data-assembler to ISAAC assets array.

    Source fields:
    - reflectivity.raw_file_path -> assets[].uri (content_role: raw_data_pointer)
    - reflectivity.reduced_file -> assets[].uri (content_role: reduction_product)
    - sample.sample_file -> assets[].uri (content_role: metadata_snapshot)

    ISAAC Schema:
    ```json
    "assets": [
        {
            "asset_id": "01HV9...",
            "content_role": "raw_data_pointer",
            "uri": "file:///path/to/raw/file.nxs",
            "sha256": "abc123...",
            "format": "NeXus",
            "description": "Raw measurement data"
        }
    ]
    ```

    Content roles (ISAAC schema enum):
    - raw_data_pointer: Original measurement files
    - reduction_product: Reduced/processed data
    - processing_recipe: Processing configuration/scripts
    - input_structure: Input structure definitions
    - metadata_snapshot: Sample or configuration metadata
    - supplementary_image: Supporting images
    - other: Other files
    """

    @property
    def block_name(self) -> str:
        return "assets"

    def is_required(self) -> bool:
        return False  # Optional block

    def map(self, context: MapperContext) -> Optional[list[dict[str, Any]]]:
        """
        Map file references to assets array.

        Returns None if no file references available.
        """
        assets: list[dict[str, Any]] = []
        asset_counter = 0

        # Process reflectivity file references
        if context.reflectivity:
            refl = context.reflectivity

            # Raw data file
            raw_file = refl.get("raw_file_path")
            if raw_file:
                asset_counter += 1
                assets.append(
                    self._build_asset(
                        path=raw_file,
                        content_role=ContentRole.RAW_DATA_POINTER.value,
                        asset_num=asset_counter,
                        record_id=context.record_id,
                        description="Raw measurement data file",
                        context=context,
                    )
                )

            # Reduced/processed file
            reduced_file = refl.get("reduced_file")
            if reduced_file:
                asset_counter += 1
                assets.append(
                    self._build_asset(
                        path=reduced_file,
                        content_role=ContentRole.REDUCTION_PRODUCT.value,
                        asset_num=asset_counter,
                        record_id=context.record_id,
                        description="Reduced reflectivity data",
                        context=context,
                    )
                )

            # Check for additional data files in nested reflectivity
            refl_data = refl.get("reflectivity", {})
            source_file = refl_data.get("source_file")
            if source_file and source_file not in [raw_file, reduced_file]:
                asset_counter += 1
                assets.append(
                    self._build_asset(
                        path=source_file,
                        content_role=ContentRole.REDUCTION_PRODUCT.value,
                        asset_num=asset_counter,
                        record_id=context.record_id,
                        description="Reflectivity data source file",
                        context=context,
                    )
                )

        # Process sample file references
        if context.sample:
            sample = context.sample

            sample_file = sample.get("sample_file")
            if sample_file:
                asset_counter += 1
                assets.append(
                    self._build_asset(
                        path=sample_file,
                        content_role=ContentRole.METADATA_SNAPSHOT.value,
                        asset_num=asset_counter,
                        record_id=context.record_id,
                        description="Sample definition file",
                        context=context,
                    )
                )

        # Process environment file references
        if context.environment:
            env = context.environment

            env_file = env.get("environment_file")
            if env_file:
                asset_counter += 1
                assets.append(
                    self._build_asset(
                        path=env_file,
                        content_role=ContentRole.METADATA_SNAPSHOT.value,
                        asset_num=asset_counter,
                        record_id=context.record_id,
                        description="Environment configuration file",
                        context=context,
                    )
                )

        return assets if assets else None

    def _build_asset(
        self,
        path: str,
        content_role: str,
        asset_num: int,
        record_id: str,
        description: str,
        context: MapperContext,
    ) -> dict[str, Any]:
        """Build a single asset entry."""
        # Generate asset ID based on record ID
        # Use a simple scheme: record_id + sequential suffix
        asset_id = f"{record_id}-A{asset_num:03d}"

        # Convert path to URI (file:// scheme)
        uri = self._path_to_uri(path)

        # Compute SHA-256 hash (use placeholder if file doesn't exist)
        sha256 = self._compute_sha256(path)

        asset: dict[str, Any] = {
            "asset_id": asset_id,
            "content_role": content_role,
            "uri": uri,
            "sha256": sha256,
        }

        # Infer format from file extension
        file_format = self._infer_format(path)
        if file_format:
            asset["format"] = file_format

        # Add description
        asset["description"] = description

        return asset

    def _path_to_uri(self, path: str) -> str:
        """Convert a file path to a file:// URI."""
        # If already a URI, return as-is
        if path.startswith(("file://", "http://", "https://", "s3://")):
            return path

        # Convert to absolute path and then to URI
        p = Path(path)
        if p.is_absolute():
            return f"file://{path}"
        else:
            return f"file://{p.absolute()}"

    def _compute_sha256(self, path: str) -> str:
        """
        Compute SHA-256 hash of file, or return a placeholder if unavailable.

        When the file is unavailable, returns a hash prefixed with zeros
        (000000...) followed by a hash of the path. This is clearly
        distinguishable from real file hashes and allows data provenance
        tracking while signaling that verification is not possible.
        """
        # Handle URIs - extract path component
        file_path = path
        if path.startswith("file://"):
            file_path = path[7:]  # Remove file:// prefix

        p = Path(file_path)
        if p.exists() and p.is_file():
            try:
                sha256_hash = hashlib.sha256()
                with open(p, "rb") as f:
                    for chunk in iter(lambda: f.read(8192), b""):
                        sha256_hash.update(chunk)
                return sha256_hash.hexdigest()
            except (OSError, IOError) as e:
                logger.warning("Failed to compute SHA-256 for %s: %s", path, e)

        # File doesn't exist or error occurred - return placeholder hash
        # Prefix with zeros to make it clearly identifiable as placeholder
        logger.warning("Cannot compute SHA-256: file not found: %s", path)
        path_hash = hashlib.sha256(path.encode()).hexdigest()
        # Use leading zeros as marker: 000000 + last 58 chars of path hash
        return "000000" + path_hash[6:]

    def _infer_format(self, path: str) -> Optional[str]:
        """Infer file format from extension."""
        import os

        ext = os.path.splitext(path.lower())[1]

        format_map = {
            ".nxs": "NeXus",
            ".nx": "NeXus",
            ".hdf5": "HDF5",
            ".hdf": "HDF5",
            ".h5": "HDF5",
            ".ort": "ORSO text reflectivity",
            ".orb": "ORSO binary reflectivity",
            ".txt": "text",
            ".csv": "CSV",
            ".json": "JSON",
            ".xml": "XML",
            ".dat": "data",
            ".parquet": "Parquet",
        }

        return format_map.get(ext)

    def validate(self, block: list[dict[str, Any]], context: MapperContext) -> bool:
        """Validate assets array structure."""
        if not isinstance(block, list):
            context.add_error("assets must be an array")
            return False

        for i, asset in enumerate(block):
            # Required fields
            if "asset_id" not in asset:
                context.add_error(f"assets[{i}].asset_id is required")
                return False

            if "content_role" not in asset:
                context.add_error(f"assets[{i}].content_role is required")
                return False

            if asset["content_role"] not in VALID_CONTENT_ROLES:
                context.add_error(f"assets[{i}].content_role must be one of {VALID_CONTENT_ROLES}")
                return False

            if "uri" not in asset:
                context.add_error(f"assets[{i}].uri is required")
                return False

            if "sha256" not in asset:
                context.add_error(f"assets[{i}].sha256 is required")
                return False

        return True
