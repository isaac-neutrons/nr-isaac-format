"""
Descriptors block mapper for ISAAC records.

Generates automated descriptors from measurement data for the
ISAAC descriptors block. Required when record_type is 'evidence'.
"""

from datetime import datetime, timezone
from typing import Any, Optional

from ..constants import DescriptorKind, DescriptorSource
from .base import Mapper, MapperContext


class DescriptorsMapper(Mapper):
    """
    Generates automated descriptors from reflectivity data.

    For record_type='evidence', the descriptors block is required
    and must contain at least one output with descriptors.

    Generated descriptors:
    - q_range_min: Minimum Q value (absolute)
    - q_range_max: Maximum Q value (absolute)
    - total_points: Number of data points (absolute)
    - measurement_geometry: Front/back reflection (categorical)

    ISAAC Schema:
    ```json
    "descriptors": {
        "policy": { "requires_at_least_one": true },
        "outputs": [{
            "label": "automated_extraction_2025-01-15",
            "generated_utc": "2025-01-15T12:00:00Z",
            "generated_by": { "agent": "nr-isaac-format", "version": "0.1.0" },
            "descriptors": [
                {"name": "q_range_min", "kind": "absolute", "source": "computed", "value": 0.01, "unit": "Å⁻¹", "uncertainty": {"sigma": 0.001}},
                ...
            ]
        }]
    }
    ```

    Descriptor kinds:
    - absolute: Direct measurement value
    - differential: Change/difference value
    - categorical: Classification label
    - similarity: Comparison metric
    - model: Model-derived parameter
    """

    @property
    def block_name(self) -> str:
        return "descriptors"

    def is_required(self) -> bool:
        # Required for evidence records
        return True

    def map(self, context: MapperContext) -> Optional[dict[str, Any]]:
        """
        Generate descriptors from measurement data and context.

        Uses typed measurement_data populated by MeasurementMapper when available,
        falling back to legacy metadata dict.
        """
        # Generate timestamp for this extraction
        generated_utc = context.created_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        date_label = context.created_utc.strftime("%Y-%m-%d")

        # Collect descriptors
        descriptors = []

        # Q-range descriptors - prefer typed measurement_data if populated, fall back to metadata
        mdata = context.measurement_data
        if mdata.q_min is not None or mdata.q_max is not None or mdata.n_points is not None:
            q_min = mdata.q_min
            q_max = mdata.q_max
            n_points = mdata.n_points
        else:
            q_min = context.metadata.get("q_min")
            q_max = context.metadata.get("q_max")
            n_points = context.metadata.get("n_points")

        if q_min is not None:
            descriptors.append({
                "name": "q_range_min",
                "kind": DescriptorKind.ABSOLUTE.value,
                "source": DescriptorSource.COMPUTED.value,
                "value": q_min,
                "unit": "Å⁻¹",
                "uncertainty": self._estimate_q_uncertainty(q_min, context),
            })

        if q_max is not None:
            descriptors.append({
                "name": "q_range_max",
                "kind": DescriptorKind.ABSOLUTE.value,
                "source": DescriptorSource.COMPUTED.value,
                "value": q_max,
                "unit": "Å⁻¹",
                "uncertainty": self._estimate_q_uncertainty(q_max, context),
            })

        if n_points is not None:
            descriptors.append({
                "name": "total_points",
                "kind": DescriptorKind.ABSOLUTE.value,
                "source": DescriptorSource.COMPUTED.value,
                "value": n_points,
                "unit": "count",
                "uncertainty": {"sigma": 0, "unit": "count"},
            })

        # Measurement geometry descriptor
        geometry = context.metadata.get("measurement_geometry")
        if geometry:
            descriptors.append({
                "name": "measurement_geometry",
                "kind": DescriptorKind.CATEGORICAL.value,
                "source": DescriptorSource.MODEL.value,
                "value": geometry,
                "uncertainty": {"confidence": 0.95},
            })
        else:
            # Flag missing geometry
            descriptors.append({
                "name": "measurement_geometry",
                "kind": DescriptorKind.CATEGORICAL.value,
                "source": DescriptorSource.UNKNOWN.value,
                "value": "undetermined",
                "uncertainty": {"confidence": 0.0},
            })
            context.add_warning("Measurement geometry could not be determined")

        # Add probe type descriptor
        if context.reflectivity:
            probe = context.reflectivity.get("probe")
            if probe:
                descriptors.append({
                    "name": "probe_type",
                    "kind": DescriptorKind.CATEGORICAL.value,
                    "source": DescriptorSource.METADATA.value,
                    "value": probe,
                    "uncertainty": {"confidence": 1.0},
                })

        # If no descriptors generated, add a placeholder
        if not descriptors:
            context.add_warning("No descriptors could be generated")
            descriptors.append({
                "name": "conversion_status",
                "kind": DescriptorKind.CATEGORICAL.value,
                "source": DescriptorSource.SYSTEM.value,
                "value": "minimal_data",
                "uncertainty": {"confidence": 1.0},
            })

        return {
            "policy": {
                "requires_at_least_one": True,
            },
            "outputs": [
                {
                    "label": f"automated_extraction_{date_label}",
                    "generated_utc": generated_utc,
                    "generated_by": {
                        "agent": "nr-isaac-format",
                        "version": "0.1.0",
                    },
                    "descriptors": descriptors,
                }
            ],
        }

    def _estimate_q_uncertainty(
        self, q_value: float, context: MapperContext
    ) -> dict[str, Any]:
        """
        Estimate uncertainty for a Q value.

        Uses dQ data if available, otherwise estimates from typical
        instrument resolution (~1% of Q).
        """
        # Try to get typical dQ from context
        # For now, use 1% relative uncertainty as typical for reflectometers
        sigma = abs(q_value) * 0.01

        return {
            "sigma": sigma,
            "unit": "Å⁻¹",
        }

    def validate(self, block: dict[str, Any], context: MapperContext) -> bool:
        """Validate descriptors block structure."""
        if "outputs" not in block:
            context.add_error("descriptors.outputs is required")
            return False

        outputs = block.get("outputs", [])
        if not outputs:
            context.add_error("descriptors.outputs must have at least one output")
            return False

        # Validate first output structure
        first_output = outputs[0]
        required_fields = ["label", "generated_utc", "generated_by", "descriptors"]
        for field in required_fields:
            if field not in first_output:
                context.add_error(f"outputs[0].{field} is required")
                return False

        # Validate descriptors array
        descriptors = first_output.get("descriptors", [])
        if not descriptors:
            context.add_error("outputs[0].descriptors must have at least one descriptor")
            return False

        # Validate each descriptor
        for i, desc in enumerate(descriptors):
            required_desc_fields = ["name", "kind", "source", "value", "uncertainty"]
            for field in required_desc_fields:
                if field not in desc:
                    context.add_error(f"descriptors[{i}].{field} is required")
                    return False

            # Validate kind enum
            valid_kinds = {k.value for k in DescriptorKind}
            if desc.get("kind") not in valid_kinds:
                context.add_error(
                    f"descriptors[{i}].kind must be one of {valid_kinds}"
                )
                return False

        return True
