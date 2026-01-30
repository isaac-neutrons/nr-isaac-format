"""
Acquisition source block mapper for ISAAC records.

Maps facility and source information from data-assembler
to the ISAAC acquisition_source block.
"""

from typing import Any, Optional

from ..constants import DEFAULT_ENDSTATION, SourceType
from .base import Mapper, MapperContext


class AcquisitionSourceMapper(Mapper):
    """
    Maps acquisition source from data-assembler to ISAAC acquisition_source block.

    Source fields:
    - reflectivity.facility -> facility.site
    - reflectivity.instrument_name -> facility.beamline
    - reflectivity.laboratory -> facility.organization (metadata)

    ISAAC Schema:
    ```json
    "acquisition_source": {
        "source_type": "facility",  // required
        "facility": {
            "site": "SNS",
            "beamline": "REF_L",
            "endstation": "reflectometer"
        }
    }
    ```
    """

    @property
    def block_name(self) -> str:
        return "acquisition_source"

    def is_required(self) -> bool:
        return True

    def map(self, context: MapperContext) -> Optional[dict[str, Any]]:
        """
        Map acquisition source from reflectivity record.

        Neutron reflectometry data typically comes from facilities,
        so source_type defaults to 'facility'.
        """
        # Default to facility for neutron reflectometry
        result: dict[str, Any] = {
            "source_type": SourceType.FACILITY.value,
        }

        if context.reflectivity:
            facility_info = self._build_facility_block(context)
            if facility_info:
                result["facility"] = facility_info
        else:
            context.add_warning("No reflectivity data for acquisition_source mapping")

        return result

    def _build_facility_block(self, context: MapperContext) -> dict[str, Any]:
        """Build the facility sub-block from reflectivity data."""
        refl = context.reflectivity
        facility: dict[str, Any] = {}

        # Map facility name to site
        facility_name = refl.get("facility")
        if facility_name:
            facility["site"] = facility_name
        else:
            facility["site"] = "Unknown"
            context.add_warning("Facility name not found, using 'Unknown'")

        # Map instrument name to beamline
        instrument = refl.get("instrument_name")
        if instrument:
            facility["beamline"] = instrument
        else:
            context.add_warning("Instrument name not found for beamline")

        # Endstation is typically 'reflectometer' for neutron reflectometry
        facility["endstation"] = DEFAULT_ENDSTATION

        # Store organization in context metadata for potential use elsewhere
        laboratory = refl.get("laboratory")
        if laboratory:
            context.metadata["organization"] = laboratory

        return facility

    def validate(self, block: dict[str, Any], context: MapperContext) -> bool:
        """Validate acquisition_source has required source_type."""
        if "source_type" not in block:
            context.add_error("acquisition_source.source_type is required")
            return False

        valid_types = {st.value for st in SourceType}
        if block["source_type"] not in valid_types:
            context.add_error(f"acquisition_source.source_type must be one of {valid_types}")
            return False

        return True
