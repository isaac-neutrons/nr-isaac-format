"""
Context block mapper for ISAAC records.

Maps experimental conditions and environment data from data-assembler
to the ISAAC context block.
"""

from typing import Any, Optional

from .base import Mapper, MapperContext


class ContextMapper(Mapper):
    """
    Maps context/conditions data from data-assembler to ISAAC context block.

    Source fields:
    - environment.temperature_value_kelvin -> context.temperature_K
    - environment.ambient_medium -> context.environment
    - reflectivity.experiment_identifier -> context.experiment_id

    ISAAC Schema:
    ```json
    "context": {
        "environment": "air",
        "temperature_K": 298.0,
        "experiment_id": "IPTS-12345",
        "experiment_title": "Sample characterization",
        "notes": "Additional experimental notes"
    }
    ```

    Required fields: environment (string), temperature_K (number)
    Additional properties are allowed.
    """

    @property
    def block_name(self) -> str:
        return "context"

    def is_required(self) -> bool:
        return False  # Optional block

    def map(self, context: MapperContext) -> Optional[dict[str, Any]]:
        """
        Map context data from environment and reflectivity records.

        Returns None if no relevant context data available or if
        required fields (environment, temperature_K) cannot be provided.
        """
        result: dict[str, Any] = {}

        # Get environment (string) - required
        env_str = self._get_environment_string(context)
        if env_str:
            result["environment"] = env_str

        # Get temperature_K (number) - required
        temp = self._get_temperature(context)
        if temp is not None:
            result["temperature_K"] = temp

        # If we don't have both required fields, return None
        if "environment" not in result or "temperature_K" not in result:
            return None

        # Add optional fields
        experiment = self._build_experiment(context)
        if experiment:
            result.update(experiment)

        notes = self._build_notes(context)
        if notes:
            result["notes"] = notes

        # Add additional environment conditions as extra properties
        extra = self._build_extra_conditions(context)
        if extra:
            result.update(extra)

        return result

    def _get_environment_string(self, context: MapperContext) -> Optional[str]:
        """Get the environment as a string (required by schema)."""
        if context.environment:
            ambient = context.environment.get("ambient_medium")
            if ambient:
                return str(ambient)

            # Try environment description as fallback
            desc = context.environment.get("environment_description")
            if desc:
                return str(desc)

        return None

    def _get_temperature(self, context: MapperContext) -> Optional[float]:
        """Get temperature in Kelvin."""
        if context.environment:
            temp = context.environment.get("temperature_value_kelvin")
            if temp is not None:
                return float(temp)
        return None

    def _build_experiment(self, context: MapperContext) -> Optional[dict[str, Any]]:
        """Build experiment-related fields from reflectivity record."""
        if not context.reflectivity:
            return None

        refl = context.reflectivity
        experiment: dict[str, Any] = {}

        # Experiment ID (proposal number)
        exp_id = refl.get("experiment_identifier")
        if exp_id:
            experiment["experiment_id"] = exp_id
        else:
            data_source = refl.get("data_source_id")
            if data_source:
                experiment["experiment_id"] = data_source

        # Experiment title
        title = refl.get("experiment_title")
        if title:
            experiment["experiment_title"] = title
        else:
            sample_name = refl.get("sample_name")
            if sample_name:
                experiment["experiment_title"] = f"Measurement of {sample_name}"

        # Experiment date
        acquired = refl.get("acquired_timestamp")
        if acquired:
            experiment["experiment_date"] = acquired

        return experiment if experiment else None

    def _build_notes(self, context: MapperContext) -> Optional[str]:
        """Build notes from various description fields."""
        notes_parts: list[str] = []

        if context.reflectivity:
            refl = context.reflectivity

            comment = refl.get("sample_description")
            if comment:
                notes_parts.append(f"Sample: {comment}")

            technique_desc = refl.get("technique_description")
            if technique_desc:
                notes_parts.append(f"Technique: {technique_desc}")

        if context.environment:
            env = context.environment

            env_comment = env.get("environment_description")
            if env_comment:
                notes_parts.append(f"Environment: {env_comment}")

        return "; ".join(notes_parts) if notes_parts else None

    def _build_extra_conditions(self, context: MapperContext) -> Optional[dict[str, Any]]:
        """Build additional condition fields (not required by schema)."""
        if not context.environment:
            return None

        env = context.environment
        extra: dict[str, Any] = {}

        # Magnetic field
        mag_field = env.get("magnetic_field_value_tesla")
        if mag_field is not None:
            extra["magnetic_field_T"] = float(mag_field)

        # Electric field
        elec_field = env.get("electric_field_value_v_per_m")
        if elec_field is not None:
            extra["electric_field_V_per_m"] = float(elec_field)

        # Pressure
        pressure = env.get("pressure_value_pa")
        if pressure is not None:
            extra["pressure_Pa"] = float(pressure)

        # Humidity
        humidity = env.get("humidity_value_percent")
        if humidity is not None:
            extra["humidity_percent"] = float(humidity)

        # pH
        ph = env.get("ph_value")
        if ph is not None:
            extra["pH"] = float(ph)

        return extra if extra else None

    def validate(self, block: dict[str, Any], context: MapperContext) -> bool:
        """Validate context block structure."""
        # Required fields per schema
        if "environment" not in block:
            context.add_error("context.environment is required")
            return False

        if not isinstance(block["environment"], str):
            context.add_error("context.environment must be a string")
            return False

        if "temperature_K" not in block:
            context.add_error("context.temperature_K is required")
            return False

        if not isinstance(block["temperature_K"], (int, float)):
            context.add_error("context.temperature_K must be a number")
            return False

        return True
