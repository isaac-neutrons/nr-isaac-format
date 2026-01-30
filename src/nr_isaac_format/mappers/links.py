"""
Links block mapper for ISAAC records.

Maps record relationships to the ISAAC links array.
"""

from typing import Any, Optional

from ..constants import LinkType
from .base import Mapper, MapperContext


class LinksMapper(Mapper):
    """
    Maps record relationships to ISAAC links array.

    This is a minimal implementation for Phase 3 that creates basic
    links between records. Full link management would require a
    record registry/database to track related records.

    Source fields:
    - Inferred from data-assembler assembly relationships

    ISAAC Schema:
    ```json
    "links": [
        {
            "link_type": "derived_from",
            "target_record_id": "01HV9...",
            "description": "Derived from raw measurement"
        }
    ]
    ```

    Link types:
    - derived_from: This record was derived from target
    - part_of: This record is part of target collection
    - related_to: General relationship
    - supersedes: This record replaces target
    - cites: This record cites target
    """

    @property
    def block_name(self) -> str:
        return "links"

    def is_required(self) -> bool:
        return False  # Optional block

    def map(self, context: MapperContext) -> Optional[list[dict[str, Any]]]:
        """
        Map record relationships to links array.

        For now, this creates links based on available metadata.
        In a full implementation, this would look up related records
        in a registry.
        """
        links: list[dict[str, Any]] = []

        # Check for parent/source record references
        if context.reflectivity:
            refl = context.reflectivity

            # If there's a source/parent record ID
            parent_id = refl.get("parent_record_id")
            if parent_id:
                links.append(
                    {
                        "link_type": LinkType.DERIVED_FROM.value,
                        "target_record_id": parent_id,
                        "description": "Derived from source record",
                    }
                )

            # If this is part of a collection/series
            collection_id = refl.get("collection_id")
            if collection_id:
                links.append(
                    {
                        "link_type": LinkType.PART_OF.value,
                        "target_record_id": collection_id,
                        "description": "Part of measurement series",
                    }
                )

            # If there's a DOI reference
            doi = refl.get("doi")
            if doi:
                links.append(
                    {
                        "link_type": LinkType.CITES.value,
                        "target_record_id": doi,
                        "description": "Associated publication DOI",
                    }
                )

        # Check for related sample records
        if context.sample:
            sample = context.sample

            sample_id = sample.get("sample_record_id")
            if sample_id:
                links.append(
                    {
                        "link_type": LinkType.RELATED_TO.value,
                        "target_record_id": sample_id,
                        "description": "Related sample record",
                    }
                )

        return links if links else None

    def validate(self, block: list[dict[str, Any]], context: MapperContext) -> bool:
        """Validate links array structure."""
        if not isinstance(block, list):
            context.add_error("links must be an array")
            return False

        valid_types = {lt.value for lt in LinkType}

        for i, link in enumerate(block):
            # Required fields
            if "link_type" not in link:
                context.add_error(f"links[{i}].link_type is required")
                return False

            if link["link_type"] not in valid_types:
                context.add_warning(
                    f"links[{i}].link_type '{link['link_type']}' may not be recognized"
                )

            if "target_record_id" not in link:
                context.add_error(f"links[{i}].target_record_id is required")
                return False

        return True
