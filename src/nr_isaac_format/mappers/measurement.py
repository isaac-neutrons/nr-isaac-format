"""
Measurement block mapper for ISAAC records.

Maps reflectivity data (Q, R, dR, dQ) from data-assembler
to the ISAAC measurement block with series/channels structure.
"""

import math
from typing import Any, Optional, Union

from ..constants import (
    DEFAULT_Q_UNIT,
    DEFAULT_R_UNIT,
    ChannelRole,
    QCStatus,
)
from .base import Mapper, MapperContext


class MeasurementMapper(Mapper):
    """
    Maps reflectivity measurement data to ISAAC measurement block.

    Source fields:
    - reflectivity.reflectivity.q -> independent_variables[0].values
    - reflectivity.reflectivity.r -> channels[0].values (primary_signal)
    - reflectivity.reflectivity.dr -> channels[1].values (quality_monitor)
    - reflectivity.reflectivity.dq -> channels[2].values (quality_monitor)
    - reflectivity.reflectivity.measurement_geometry -> processing metadata

    ISAAC Schema:
    ```json
    "measurement": {
        "processing": { "type": "reduced_reflectivity" },
        "series": [{
            "series_id": "reflectivity_profile",
            "independent_variables": [{
                "name": "q",
                "unit": "Å⁻¹",
                "values": [0.01, 0.02, ...]
            }],
            "channels": [
                {"name": "R", "unit": "dimensionless", "role": "primary_signal", "values": [...]},
                {"name": "dR", "unit": "dimensionless", "role": "quality_monitor", "values": [...]},
                {"name": "dQ", "unit": "Å⁻¹", "role": "quality_monitor", "values": [...]}
            ]
        }],
        "qc": { "status": "valid" }
    }
    ```

    Allowed channel roles:
    - primary_signal: Main measurement signal
    - measured_response: Response to stimulus
    - simulated_observable: Computed/simulated value
    - derived_signal: Calculated from other signals
    - auxiliary_signal: Supporting measurement
    - control_readback: Instrument control value
    - quality_monitor: Quality/uncertainty indicator
    """

    @property
    def block_name(self) -> str:
        return "measurement"

    def is_required(self) -> bool:
        # Measurement is optional in schema but essential for our use case
        return False

    def map(self, context: MapperContext) -> Optional[dict[str, Any]]:
        """
        Map reflectivity data to ISAAC measurement block.

        Returns None if no reflectivity data available.
        """
        if not context.reflectivity:
            context.add_warning("No reflectivity data for measurement mapping")
            return None

        refl_data = context.reflectivity.get("reflectivity", {})
        if not refl_data:
            context.add_warning("No reflectivity.reflectivity nested data")
            return None

        # Extract arrays
        q = refl_data.get("q", [])
        r = refl_data.get("r", [])
        dr = refl_data.get("dr", [])
        dq = refl_data.get("dq", [])

        if not q or not r:
            context.add_error("Missing q or r arrays in reflectivity data")
            return None

        # Build processing metadata
        processing = self._build_processing(refl_data, context)

        # Build series with independent variables and channels
        series = self._build_series(q, r, dr, dq, context)

        # Determine QC status based on data quality
        qc = self._build_qc(context)

        return {
            "processing": processing,
            "series": [series],
            "qc": qc,
        }

    def _build_processing(
        self, refl_data: dict[str, Any], context: MapperContext
    ) -> dict[str, Any]:
        """Build processing metadata."""
        processing: dict[str, Any] = {
            "type": "reduced_reflectivity",
        }

        # Add reduction version if available
        reduction_version = refl_data.get("reduction_version")
        if reduction_version:
            processing["software_version"] = reduction_version

        # Add measurement geometry info
        geometry = refl_data.get("measurement_geometry")
        if geometry:
            processing["geometry"] = geometry
            # Store in typed measurement_data for DescriptorsMapper
            context.measurement_data.measurement_geometry = geometry
            # Also keep in metadata for backwards compatibility
            context.metadata["measurement_geometry"] = geometry

        return processing

    def _build_series(
        self,
        q: list,
        r: list,
        dr: list,
        dq: list,
        context: MapperContext,
    ) -> dict[str, Any]:
        """Build a measurement series from reflectivity arrays."""
        # Independent variable: momentum transfer Q
        independent_variables = [
            {
                "name": "q",
                "unit": DEFAULT_Q_UNIT,
                "values": self._ensure_native_types(q),
            }
        ]

        # Channels: R (signal), dR (uncertainty), dQ (Q resolution)
        channels = [
            {
                "name": "R",
                "unit": DEFAULT_R_UNIT,
                "role": ChannelRole.PRIMARY_SIGNAL.value,
                "values": self._ensure_native_types(r),
            },
        ]

        # Add dR if available
        if dr and len(dr) == len(r):
            channels.append(
                {
                    "name": "dR",
                    "unit": DEFAULT_R_UNIT,
                    "role": ChannelRole.QUALITY_MONITOR.value,
                    "values": self._ensure_native_types(dr),
                }
            )
        elif dr:
            context.add_warning(f"dR length ({len(dr)}) doesn't match R length ({len(r)})")

        # Add dQ if available
        if dq and len(dq) == len(q):
            channels.append(
                {
                    "name": "dQ",
                    "unit": DEFAULT_Q_UNIT,
                    "role": ChannelRole.QUALITY_MONITOR.value,
                    "values": self._ensure_native_types(dq),
                }
            )
        elif dq:
            context.add_warning(f"dQ length ({len(dq)}) doesn't match Q length ({len(q)})")

        # Store data stats in typed measurement_data for DescriptorsMapper
        if q:
            q_min = float(min(q))
            q_max = float(max(q))
            n_points = len(q)
            # Use typed field
            context.measurement_data.q_min = q_min
            context.measurement_data.q_max = q_max
            context.measurement_data.n_points = n_points
            # Also keep in metadata for backwards compatibility
            context.metadata["q_min"] = q_min
            context.metadata["q_max"] = q_max
            context.metadata["n_points"] = n_points

        return {
            "series_id": "reflectivity_profile",
            "independent_variables": independent_variables,
            "channels": channels,
        }

    def _build_qc(self, context: MapperContext) -> dict[str, Any]:
        """
        Build QC block based on conversion warnings/errors.

        Status values:
        - valid: Data passed all checks
        - suspect: Data has warnings but usable
        - invalid: Data failed critical checks
        """
        # Check for errors or warnings from assembly
        assembly_warnings = context.result.warnings if context.result else []
        assembly_errors = context.result.errors if context.result else []

        if assembly_errors:
            return {
                "status": QCStatus.INVALID.value,
                "evidence": f"Assembly errors: {'; '.join(assembly_errors[:3])}",
            }
        elif assembly_warnings:
            return {
                "status": QCStatus.SUSPECT.value,
                "evidence": f"Assembly warnings: {'; '.join(assembly_warnings[:3])}",
            }
        else:
            return {
                "status": QCStatus.VALID.value,
                "evidence": "Data passed assembly validation.",
            }

    def _ensure_native_types(self, values: list) -> list:
        """
        Convert numpy types to native Python types for JSON serialization.

        Handles:
        - numpy scalars (via .item())
        - integers (preserved as int)
        - floats (preserved, NaN/Inf converted to None with warning)
        - other types (converted to float)
        """
        result = []
        for v in values:
            native_val = self._to_native_type(v)
            result.append(native_val)
        return result

    def _to_native_type(self, value: Any) -> Union[int, float, None]:
        """Convert a single value to native Python type."""
        # Handle numpy types first
        if hasattr(value, "item"):
            value = value.item()

        # Check for int (preserve integer type)
        if isinstance(value, int):
            return value

        # Convert to float and check for special values
        try:
            float_val = float(value)
            if math.isnan(float_val) or math.isinf(float_val):
                # NaN and Inf are not valid JSON, return None
                return None
            return float_val
        except (TypeError, ValueError):
            return None

    def validate(self, block: dict[str, Any], context: MapperContext) -> bool:
        """Validate measurement block structure."""
        if "series" not in block:
            context.add_error("measurement.series is required")
            return False

        if "qc" not in block:
            context.add_error("measurement.qc is required")
            return False

        series = block.get("series", [])
        if not series:
            context.add_error("measurement.series must have at least one series")
            return False

        # Validate first series structure
        first_series = series[0]
        if "series_id" not in first_series:
            context.add_error("series.series_id is required")
            return False

        if "independent_variables" not in first_series:
            context.add_error("series.independent_variables is required")
            return False

        if "channels" not in first_series:
            context.add_error("series.channels is required")
            return False

        # Validate channels have required fields
        for i, channel in enumerate(first_series.get("channels", [])):
            for field in ["name", "unit", "role"]:
                if field not in channel:
                    context.add_error(f"channels[{i}].{field} is required")
                    return False

        return True
