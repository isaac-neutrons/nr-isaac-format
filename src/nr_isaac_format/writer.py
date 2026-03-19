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

from assembler.workflow import AssemblyResult
from ulid import ULID

__all__ = ["IsaacWriter", "write_isaac_record"]

# Schema revision this writer targets. Bump when updating for a new schema.
SCHEMA_REVISION = "v1-ornl-rev2"


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

    def to_isaac(
        self,
        result: AssemblyResult,
        environment_description: str | None = None,
        context_description: str | None = None,
        raw_file_path: str | None = None,
        sample_name: str | None = None,
        sample_formula: str | None = None,
        record_id: str | None = None,
    ) -> dict[str, Any]:
        """
        Convert AssemblyResult to ISAAC AI-Ready Record format.

        Args:
            result: Assembled data from data-assembler
            environment_description: Optional environment/enum value from manifest
            context_description: Optional free-text context description from manifest
            raw_file_path: Optional path to raw NeXus file from manifest
            sample_name: Sample name from manifest ``sample.description``
            sample_formula: Sample formula from manifest ``sample.material``
            record_id: Optional record ID to reuse (preserves identity across updates)

        Returns:
            ISAAC record as a dictionary
        """
        now = datetime.now(timezone.utc)
        refl = result.reflectivity or {}
        refl_data = refl.get("reflectivity", {})

        record = {
            "isaac_record_version": "1.0",
            "record_id": record_id or str(ULID()).upper(),
            "record_type": "evidence",
            "record_domain": "characterization",
            "source_type": "facility",
            "timestamps": self._map_timestamps(refl, now),
            "measurement": self._map_measurement(refl_data),
            "descriptors": self._map_descriptors(refl_data, now),
        }

        # Optional blocks
        if result.sample:
            sample_block = self._map_sample(
                result.sample, sample_name=sample_name, sample_formula=sample_formula,
            )
            if sample_block:
                record["sample"] = sample_block
        elif sample_name or sample_formula:
            record["sample"] = {
                "sample_form": "film",
                "material": {
                    "name": sample_name or sample_formula,
                    "formula": sample_formula or sample_name,
                },
            }

        # Build context from environment record and/or manifest description
        env = result.environment or {}
        if environment_description and not env.get("description"):
            env["description"] = environment_description
        if env:
            context_block = self._map_context(env, context_description=context_description)
            if context_block:
                record["context"] = context_block

        if refl:
            system_block = self._map_system(refl)
            if system_block:
                record["system"] = system_block

            assets_block = self._map_assets(refl, result, raw_file_path=raw_file_path)
            if assets_block:
                record["assets"] = assets_block

        return record

    def write(
        self,
        result: AssemblyResult,
        output_path: str | Path | None = None,
        environment_description: str | None = None,
        context_description: str | None = None,
        raw_file_path: str | None = None,
        sample_name: str | None = None,
        sample_formula: str | None = None,
        record_id: str | None = None,
    ) -> Path:
        """
        Write AssemblyResult as ISAAC record to JSON file.

        Args:
            result: Assembled data from data-assembler
            output_path: Output file path. If None, uses output_dir/isaac_record.json
            environment_description: Optional environment/enum value from manifest
            context_description: Optional free-text context from manifest
            raw_file_path: Optional path to raw NeXus file from manifest
            sample_name: Sample name from manifest ``sample.description``
            sample_formula: Sample formula from manifest ``sample.material``
            record_id: Optional record ID to reuse (preserves identity across updates)

        Returns:
            Path to written file
        """
        record = self.to_isaac(
            result,
            environment_description=environment_description,
            context_description=context_description,
            raw_file_path=raw_file_path,
            sample_name=sample_name,
            sample_formula=sample_formula,
            record_id=record_id,
        )

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
                {
                    "name": "dR",
                    "unit": "dimensionless",
                    "role": "quality_monitor",
                    "values": list(dr),
                }
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
            descriptors.extend(
                [
                    {
                        "name": "q_range_min",
                        "kind": "absolute",
                        "source": "auto",
                        "value": min(q),
                        "unit": "Å⁻¹",
                        "uncertainty": {"type": "none"},
                    },
                    {
                        "name": "q_range_max",
                        "kind": "absolute",
                        "source": "auto",
                        "value": max(q),
                        "unit": "Å⁻¹",
                        "uncertainty": {"type": "none"},
                    },
                    {
                        "name": "total_points",
                        "kind": "absolute",
                        "source": "auto",
                        "value": len(q),
                        "unit": "count",
                        "uncertainty": {"type": "none"},
                    },
                ]
            )

        geometry = refl_data.get("measurement_geometry")
        if geometry:
            descriptors.append(
                {
                    "name": "measurement_geometry",
                    "kind": "categorical",
                    "source": "auto",
                    "value": geometry,
                    "uncertainty": {"type": "none"},
                }
            )

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

    def _map_sample(
        self,
        sample: dict,
        sample_name: str | None = None,
        sample_formula: str | None = None,
    ) -> dict[str, Any] | None:
        """Map sample record to ISAAC sample block."""
        if not sample:
            return None

        result: dict[str, Any] = {"sample_form": "film"}

        composition = sample.get("main_composition")
        # Use manifest sample info when assembler composition is missing or unknown
        if (not composition or composition == "Unknown") and (sample_name or sample_formula):
            result["material"] = {
                "name": sample_name or sample_formula,
                "formula": sample_formula or sample_name,
            }
        elif composition:
            raw_provenance = sample.get("provenance", "")
            provenance = self._normalise_provenance(raw_provenance)
            result["material"] = {
                "name": composition,
                "formula": sample.get("formula", composition),
            }
            if provenance:
                result["material"]["provenance"] = provenance

        layers = sample.get("layers", [])
        if layers:
            result["geometry"] = {
                "layer_count": len(layers),
                "total_thickness_nm": sum(layer.get("thickness", 0) for layer in layers),
            }

        return result

    # Valid provenance values per ISAAC v1 ornl-rev1 schema
    _PROVENANCE_ENUM = frozenset(
        {
            "commercial",
            "synthesized",
            "theoretical",
            "literature",
            "natural",
        }
    )
    _PROVENANCE_MAP: dict[str, str] = {
        "model_fitted": "theoretical",
        "model": "theoretical",
        "fitted": "theoretical",
        "simulation": "theoretical",
        "computed": "theoretical",
        "purchased": "commercial",
        "bought": "commercial",
        "grown": "synthesized",
        "deposited": "synthesized",
        "fabricated": "synthesized",
    }

    @classmethod
    def _normalise_provenance(cls, raw: str) -> str:
        """Map a free-text provenance string to the schema enum, or omit."""
        low = raw.strip().lower()
        if low in cls._PROVENANCE_ENUM:
            return low
        return cls._PROVENANCE_MAP.get(low, "")

    def _map_system(self, refl: dict) -> dict[str, Any] | None:
        """Map instrument configuration to ISAAC system block."""
        facility = refl.get("facility")
        instrument = refl.get("instrument_name")

        if not facility and not instrument:
            return None

        result: dict[str, Any] = {
            "domain": "experimental",
            "technique": "neutron_reflectometry",
            "instrument": {
                "instrument_type": "beamline_endstation",
                "instrument_name": instrument or "unknown",
            },
            "facility": {
                "facility_name": facility or "unknown",
                "beamline": instrument,
            },
        }

        return result

    # Valid environment enum values per ISAAC v1 ornl-rev1 schema
    _ENVIRONMENT_ENUM = frozenset(
        {
            "operando",
            "in_situ",
            "ex_situ",
            "in_silico",
        }
    )
    _ENVIRONMENT_MAP: dict[str, str] = {
        "in situ": "in_situ",
        "ex situ": "ex_situ",
        "in silico": "in_silico",
    }

    @classmethod
    def _classify_environment(cls, description: str) -> str:
        """Best-effort classification of a free-text environment description.

        Returns one of the schema enum values.  Defaults to ``"ex_situ"``
        when no keyword match is found.
        """
        low = description.strip().lower()
        if low in cls._ENVIRONMENT_ENUM:
            return low
        if low in cls._ENVIRONMENT_MAP:
            return cls._ENVIRONMENT_MAP[low]
        # Keyword heuristics
        if "electrochemical" in low or "operando" in low or "under bias" in low:
            return "operando"
        if "in situ" in low or "in_situ" in low:
            return "in_situ"
        if "in silico" in low or "simulat" in low:
            return "in_silico"
        return "ex_situ"

    def _map_context(
        self, env: dict, context_description: str | None = None
    ) -> dict[str, Any] | None:
        """Map environment record to ISAAC context block."""
        if not env:
            return None

        description = env.get("description", "not specified")
        environment_enum = self._classify_environment(description)

        result: dict[str, Any] = {
            "environment": environment_enum,
            "temperature_K": env.get("temperature")
            if env.get("temperature") is not None
            else 295.0,
        }

        # Use explicit context_description from manifest if provided,
        # otherwise fall back to the environment description text.
        desc = context_description or description
        if desc and desc != environment_enum:
            result["description"] = desc

        if env.get("pressure"):
            result["pressure_Pa"] = env["pressure"]

        if env.get("ambient_medium"):
            result["ambient_medium"] = env["ambient_medium"]

        return result

    def _map_assets(
        self, refl: dict, result: AssemblyResult, raw_file_path: str | None = None
    ) -> list[dict[str, Any]] | None:
        """Map file references to ISAAC assets block."""
        assets = []

        # Prefer manifest raw path, fall back to reflectivity metadata
        raw_file = raw_file_path or refl.get("raw_file_path")
        if raw_file:
            assets.append(
                {
                    "asset_id": "raw_nexus_file",
                    "content_role": "raw_data_pointer",
                    "uri": str(raw_file),
                    "sha256": self._file_sha256(raw_file),
                }
            )

        if result.reduced_file:
            assets.append(
                {
                    "asset_id": "reduced_data",
                    "content_role": "reduction_product",
                    "uri": str(result.reduced_file),
                    "sha256": self._file_sha256(result.reduced_file),
                }
            )

        return assets if assets else None

    @staticmethod
    def _file_sha256(file_path: str | Path) -> str:
        """Compute SHA-256 hex digest of a file, or return empty string if inaccessible."""
        import hashlib

        path = Path(file_path)
        if not path.is_file():
            return ""
        try:
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    h.update(chunk)
            return h.hexdigest()
        except OSError:
            return ""


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
