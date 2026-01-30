"""
System block mapper for ISAAC records.

Maps instrument and configuration information from data-assembler
to the ISAAC system block.
"""

from typing import Any, Optional

from ..constants import InstrumentType, SystemDomain
from .base import Mapper, MapperContext


class SystemMapper(Mapper):
    """
    Maps system/instrument data from data-assembler to ISAAC system block.

    Source fields:
    - reflectivity.facility -> system.facility.facility_name
    - reflectivity.laboratory -> system.facility.organization
    - reflectivity.instrument_name -> system.instrument, system.facility.beamline
    - reflectivity.probe -> system.configuration
    - reflectivity.reflectivity.measurement_geometry -> system.configuration

    ISAAC Schema:
    ```json
    "system": {
        "domain": "experimental",
        "facility": {
            "facility_name": "SNS",
            "organization": "ORNL",
            "beamline": "REF_L"
        },
        "instrument": {
            "instrument_type": "beamline_endstation",
            "instrument_name": "REF_L",
            "vendor_or_project": "ORNL"
        },
        "configuration": {
            "measurement_geometry": "front reflection",
            "probe": "neutrons"
        }
    }
    ```

    Domain values:
    - experimental: Real measurement
    - computational: Simulation
    """

    @property
    def block_name(self) -> str:
        return "system"

    def is_required(self) -> bool:
        return False  # Optional block

    def map(self, context: MapperContext) -> Optional[dict[str, Any]]:
        """
        Map system data from reflectivity record.

        Returns None if insufficient data available.
        """
        if not context.reflectivity:
            return None

        refl = context.reflectivity

        # Determine domain (experimental vs computational)
        is_simulated = refl.get("is_simulated", False)
        domain = (
            SystemDomain.COMPUTATIONAL.value if is_simulated else SystemDomain.EXPERIMENTAL.value
        )

        result: dict[str, Any] = {
            "domain": domain,
        }

        # Build facility block
        facility = self._build_facility(refl, context)
        if facility:
            result["facility"] = facility

        # Build instrument block
        instrument = self._build_instrument(refl, context)
        if instrument:
            result["instrument"] = instrument

        # Build configuration block (required by schema)
        configuration = self._build_configuration(refl, context)
        result["configuration"] = configuration

        return result

    def _build_facility(
        self, refl: dict[str, Any], context: MapperContext
    ) -> Optional[dict[str, Any]]:
        """Build the facility sub-block."""
        facility: dict[str, Any] = {}

        # Facility name
        facility_name = refl.get("facility")
        if facility_name:
            facility["facility_name"] = facility_name

        # Organization (laboratory)
        organization = refl.get("laboratory")
        if organization:
            facility["organization"] = organization
        elif context.metadata.get("organization"):
            # May have been stored by AcquisitionSourceMapper
            facility["organization"] = context.metadata["organization"]

        # Beamline (instrument name)
        instrument_name = refl.get("instrument_name")
        if instrument_name:
            facility["beamline"] = instrument_name

        return facility if facility else None

    def _build_instrument(
        self, refl: dict[str, Any], context: MapperContext
    ) -> Optional[dict[str, Any]]:
        """Build the instrument sub-block."""
        instrument: dict[str, Any] = {}

        # Instrument type - for beamlines, use beamline_endstation
        instrument["instrument_type"] = InstrumentType.BEAMLINE_ENDSTATION.value

        # Instrument name
        instrument_name = refl.get("instrument_name")
        if instrument_name:
            instrument["instrument_name"] = instrument_name
        else:
            return None  # Can't build without name

        # Vendor/project - use laboratory if available
        laboratory = refl.get("laboratory")
        if laboratory:
            instrument["vendor_or_project"] = laboratory

        return instrument

    def _build_configuration(self, refl: dict[str, Any], context: MapperContext) -> dict[str, Any]:
        """
        Build the configuration sub-block.

        Configuration must be a flat object with string/number/boolean values only.
        """
        config: dict[str, Any] = {}

        # Measurement geometry from reflectivity nested data
        refl_data = refl.get("reflectivity", {})
        geometry = refl_data.get("measurement_geometry")
        if geometry:
            config["measurement_geometry"] = geometry

        # Probe type
        probe = refl.get("probe")
        if probe:
            config["probe"] = probe

        # Technique
        technique = refl.get("technique")
        if technique:
            config["technique"] = technique

        # Technique description
        technique_desc = refl.get("technique_description")
        if technique_desc:
            config["technique_description"] = technique_desc

        # Reduction version
        reduction_version = refl_data.get("reduction_version")
        if reduction_version:
            config["reduction_software"] = reduction_version

        return config

    def validate(self, block: dict[str, Any], context: MapperContext) -> bool:
        """Validate system block has required fields."""
        if "domain" not in block:
            context.add_error("system.domain is required")
            return False

        valid_domains = {d.value for d in SystemDomain}
        if block["domain"] not in valid_domains:
            context.add_error(f"system.domain must be one of {valid_domains}")
            return False

        if "configuration" not in block:
            context.add_error("system.configuration is required")
            return False

        # Configuration must be flat (no nested objects)
        config = block["configuration"]
        for key, value in config.items():
            if isinstance(value, dict):
                context.add_error(f"system.configuration.{key} cannot be a nested object")
                return False

        return True
