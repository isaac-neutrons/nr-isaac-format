"""
ISAAC AI-Ready Record Writer

Minimal writer following the data-assembler pattern.
Converts AssemblyResult to ISAAC AI-Ready Scientific Record v1.0 format.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ulid import ULID

from assembler.workflow import AssemblyResult

__all__ = ["IsaacWriter", "write_isaac_record"]


class IsaacWriter:
    """Writer for ISAAC AI-Ready Record v1.0 format."""

    def __init__(self, output_dir: str | Path | None = None):
        """
        Initialize the writer.

        Args:
            output_dir: Directory for output files. If None, write() requires explicit path.
        """
        self.output_dir = Path(output_dir) if output_dir else None
        if self.output_dir:
            self.output_dir.mkdir(parents=True, exist_ok=True)

    def to_isaac(self, result: AssemblyResult) -> dict[str, Any]:
        """
        Convert AssemblyResult to ISAAC AI-Ready Record format.

        Args:
            result: Assembled data from data-assembler

        Returns:
            ISAAC record as a dictionary
        """
        now = datetime.now(timezone.utc)
        refl = result.reflectivity or {}
        refl_data = refl.get("reflectivity", {})

        record = {
            "isaac_record_version": "1.0",
            "record_id": str(ULID()).upper(),
            "record_type": "evidence",
            "record_domain": "characterization",
            "timestamps": self._map_timestamps(refl, now),
            "acquisition_source": self._map_acquisition_source(refl),
            "measurement": self._map_measurement(refl_data),
            "descriptors": self._map_descriptors(refl_data, now),
        }

        # Optional blocks
        if result.sample:
            sample_block = self._map_sample(result.sample)
            if sample_block:
                record["sample"] = sample_block

        if result.environment:
            context_block = self._map_context(result.environment)
            if context_block:
                record["context"] = context_block

        if refl:
            system_block = self._map_system(refl)
            if system_block:
                record["system"] = system_block

            assets_block = self._map_assets(refl, result)
            if assets_block:
                record["assets"] = assets_block

        return record

    def write(self, result: AssemblyResult, output_path: str | Path | None = None) -> Path:
        """
        Write AssemblyResult as ISAAC record to JSON file.

        Args:
            result: Assembled data from data-assembler
            output_path: Output file path. If None, uses output_dir/isaac_record.json

        Returns:
            Path to written file
        """
        record = self.to_isaac(result)

        if output_path:
            path = Path(output_path)
        elif self.output_dir:
            path = self.output_dir / "isaac_record.json"
        else:
            raise ValueError("No output path specified and no output_dir configured")

        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(record, f, indent=2, default=str)

        return path

    # -------------------------------------------------------------------------
    # Block mappers - simple dict transformations
    # -------------------------------------------------------------------------

    def _map_timestamps(self, refl: dict, now: datetime) -> dict[str, Any]:
        """Map timestamps from reflectivity record."""
        ts = {"created_utc": now.isoformat().replace("+00:00", "Z")}

        run_start = refl.get("run_start")
        if run_start:
            if isinstance(run_start, datetime):
                ts["acquired_start_utc"] = run_start.isoformat().replace("+00:00", "Z")
            elif isinstance(run_start, str):
                ts["acquired_start_utc"] = run_start

        return ts

    def _map_acquisition_source(self, refl: dict) -> dict[str, Any]:
        """Map facility/instrument info to acquisition_source block."""
        return {
            "source_type": "facility",
            "facility": {
                "site": refl.get("facility", "unknown"),
                "beamline": refl.get("instrument_name", "unknown"),
                "endstation": "reflectometer",
            },
        }

    def _map_measurement(self, refl_data: dict) -> dict[str, Any] | None:
        """Map Q/R/dR/dQ arrays to measurement series/channels."""
        q = refl_data.get("q", [])
        r = refl_data.get("r", [])

        if not q or not r:
            return None

        channels = [
            {"name": "R", "unit": "dimensionless", "role": "primary_signal", "values": list(r)},
        ]

        dr = refl_data.get("dr", [])
        if dr:
            channels.append(
                {"name": "dR", "unit": "dimensionless", "role": "quality_monitor", "values": list(dr)}
            )

        dq = refl_data.get("dq", [])
        if dq:
            channels.append(
                {"name": "dQ", "unit": "Å⁻¹", "role": "quality_monitor", "values": list(dq)}
            )

        return {
            "series": [
                {
                    "series_id": "reflectivity_profile",
                    "independent_variables": [{"name": "q", "unit": "Å⁻¹", "values": list(q)}],
                    "channels": channels,
                }
            ],
            "qc": {"status": "valid"},
        }

    def _map_descriptors(self, refl_data: dict, now: datetime) -> dict[str, Any]:
        """Extract automated descriptors from measurement data."""
        q = refl_data.get("q", [])

        descriptors = []
        if q:
            descriptors.extend([
                {
                    "name": "q_range_min",
                    "kind": "absolute",
                    "source": "computed",
                    "value": min(q),
                    "unit": "Å⁻¹",
                },
                {
                    "name": "q_range_max",
                    "kind": "absolute",
                    "source": "computed",
                    "value": max(q),
                    "unit": "Å⁻¹",
                },
                {
                    "name": "total_points",
                    "kind": "absolute",
                    "source": "computed",
                    "value": len(q),
                    "unit": "count",
                },
            ])

        geometry = refl_data.get("measurement_geometry")
        if geometry:
            descriptors.append({
                "name": "measurement_geometry",
                "kind": "categorical",
                "source": "metadata",
                "value": geometry,
            })

        return {
            "policy": {"requires_at_least_one": True},
            "outputs": [
                {
                    "label": f"automated_extraction_{now.strftime('%Y-%m-%d')}",
                    "generated_utc": now.isoformat().replace("+00:00", "Z"),
                    "generated_by": {"agent": "nr-isaac-format", "version": "0.1.0"},
                    "descriptors": descriptors,
                }
            ],
        }

    def _map_sample(self, sample: dict) -> dict[str, Any] | None:
        """Map sample record to ISAAC sample block."""
        if not sample:
            return None

        result = {"sample_form": "thin_film"}

        if sample.get("main_composition"):
            result["material"] = {
                "name": sample["main_composition"],
                "provenance": "model_fitted",
            }

        layers = sample.get("layers", [])
        if layers:
            result["geometry"] = {
                "layer_count": len(layers),
                "total_thickness_nm": sum(layer.get("thickness", 0) for layer in layers),
            }

        return result

    def _map_system(self, refl: dict) -> dict[str, Any] | None:
        """Map instrument configuration to ISAAC system block."""
        facility = refl.get("facility")
        instrument = refl.get("instrument_name")

        if not facility and not instrument:
            return None

        return {
            "domain": "experimental",
            "instrument": {
                "instrument_type": "beamline_endstation",
                "instrument_name": instrument or "unknown",
            },
            "facility": {
                "facility_name": facility or "unknown",
                "beamline": instrument,
            },
        }

    def _map_context(self, env: dict) -> dict[str, Any] | None:
        """Map environment record to ISAAC context block."""
        if not env:
            return None

        result = {}

        if env.get("temperature"):
            result["temperature_K"] = env["temperature"]

        if env.get("pressure"):
            result["pressure_Pa"] = env["pressure"]

        if env.get("ambient_medium"):
            result["ambient_medium"] = env["ambient_medium"]

        if env.get("description"):
            result["environment"] = env["description"]

        return result if result else None

    def _map_assets(self, refl: dict, result: AssemblyResult) -> list[dict[str, Any]] | None:
        """Map file references to ISAAC assets block."""
        assets = []

        raw_file = refl.get("raw_file_path")
        if raw_file:
            assets.append({
                "asset_id": "raw_nexus_file",
                "content_role": "raw_data_pointer",
                "uri": str(raw_file),
            })

        if result.reduced_file:
            assets.append({
                "asset_id": "reduced_data",
                "content_role": "reduction_product",
                "uri": str(result.reduced_file),
            })

        return assets if assets else None


def write_isaac_record(result: AssemblyResult, output_path: str | Path) -> Path:
    """
    Convenience function to write an AssemblyResult as ISAAC record.

    Args:
        result: Assembled data from data-assembler
        output_path: Output file path

    Returns:
        Path to written file
    """
    writer = IsaacWriter()
    return writer.write(result, output_path)
