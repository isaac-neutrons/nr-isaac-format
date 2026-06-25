"""
ISAAC AI-Ready Record Writer

Minimal writer following the data-assembler pattern.
Converts AssemblyResult to ISAAC AI-Ready Scientific Record (schema
revision ``v1-ornl-rev4``) format.
"""

from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from assembler.workflow import AssemblyResult
from ulid import ULID

__all__ = ["IsaacWriter", "write_isaac_record"]


def _b64(text: str) -> str:
    """Return base64-encoded UTF-8 ``text`` (used for inline data URIs)."""
    return base64.b64encode(text.encode("utf-8")).decode("ascii")

# Schema revision this writer targets. Bump when updating for a new schema.
SCHEMA_REVISION = "v1-ornl-rev4"


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
            context_description: Optional free-text measurement description from
                manifest ``context``; surfaced as ``measurement.series[].notes``
            raw_file_path: Optional path to raw NeXus file from manifest
            sample_name: Sample name from manifest ``sample.description``
            sample_formula: Sample formula from manifest ``sample.material``
            record_id: Optional record ID to reuse (preserves identity across updates)

        Returns:
            ISAAC record as a dictionary
        """
        now = datetime.now(timezone.utc)
        refl = result.reflectivity or {}

        # Resolve the environment record, augmenting it with the manifest's
        # environment text when the assembler did not supply one.
        env = result.environment or {}
        if environment_description and not env.get("description"):
            env["description"] = environment_description

        # Pick the best free-text description of the measurement, preferring the
        # explicit manifest ``context`` over any free-text environment note.
        measurement_description = self._select_measurement_description(context_description, env)

        record = {
            "isaac_record_version": "1.05",
            "record_id": record_id or str(ULID()).upper(),
            "record_type": "evidence",
            "record_domain": "characterization",
            "source_type": "facility",
            "timestamps": self._map_timestamps(refl, now),
            "descriptors": self._map_descriptors(
                refl, now, getattr(result, "reflectivity_model", None)
            ),
        }

        # The free-text description rides on measurement.series[].notes, where it
        # is directly readable (rev4 closes the top-level, context, and
        # measurement blocks, so there is no other inline home).
        measurement_block = self._map_measurement(refl, description=measurement_description)
        description_placed = False
        if measurement_block is not None:
            record["measurement"] = measurement_block
            description_placed = bool(measurement_description)

        # Optional sample block
        if result.sample:
            sample_block = self._map_sample(
                result.sample,
                sample_name=sample_name,
                sample_formula=sample_formula,
            )
            if sample_block:
                record["sample"] = sample_block
        elif sample_name or sample_formula:
            material: dict[str, Any] = {
                "name": sample_name or sample_formula,
                "formula": sample_formula or sample_name,
            }
            if sample_name:
                material["notes"] = sample_name
            record["sample"] = {"sample_form": "film", "material": material}

        # Context block (rev3/rev4: typed fields only). Applied-potential info
        # (OCV, "-1 V", …) is parsed from the free-text description into the
        # typed context.electrochemistry block, defaulting to the SHE scale.
        electrochemistry = self._parse_electrochemistry(measurement_description)
        if env or electrochemistry:
            context_block = self._map_context(
                env, description=measurement_description, electrochemistry=electrochemistry
            )
            if context_block:
                record["context"] = context_block

        if refl:
            system_block = self._map_system(refl)
            if system_block:
                record["system"] = system_block

            assets_block = self._map_assets(refl, result, raw_file_path=raw_file_path)
        else:
            assets_block = None

        extra_assets: list[dict[str, Any]] = []

        # ``ambient_medium`` has no typed home in the rev3/rev4 context block; keep it
        # in a metadata_snapshot asset so the data is preserved.
        snapshot_asset = self._build_metadata_snapshot_asset(env)
        if snapshot_asset:
            extra_assets.append(snapshot_asset)

        # Fallback: with no measurement block (e.g. no reduced series) there is
        # nowhere inline for the description, so preserve it as a documentation
        # asset rather than dropping it.
        if measurement_description and not description_placed:
            extra_assets.append(self._build_description_asset(measurement_description))

        if extra_assets:
            assets_block = (assets_block or []) + extra_assets

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

    def _map_measurement(
        self, refl_data: dict, description: str | None = None
    ) -> dict[str, Any] | None:
        """Map Q/R/dR/dQ arrays to a measurement block.

        When ``description`` is given it is emitted as ``measurement.series[].notes``
        — a free-text, human/AI-readable summary of how the measurement was made.
        (Schema rev4 closes the ``measurement`` block but adds a ``notes`` string
        to each series.)
        """
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

        series_item: dict[str, Any] = {
            "series_id": "reflectivity_profile",
            "independent_variables": [{"name": "q", "unit": "Å⁻¹", "values": list(q)}],
            "channels": channels,
        }
        if description:
            series_item["notes"] = description

        return {"series": [series_item], "qc": {"status": "valid"}}

    def _map_descriptors(
        self, refl_data: dict, now: datetime, reflectivity_model: dict | None = None
    ) -> dict[str, Any]:
        """Extract automated descriptors from measurement data.

        Emits one ``outputs`` group of data-range descriptors generated by this
        tool, and — when a fitted ``reflectivity_model`` is present — a second
        group of model-derived descriptors (per-layer thickness/SLD/roughness
        with their fitted σ, plus χ²) attributed to the fitting software.
        """
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
                        "uncertainty": self._no_uncertainty(),
                    },
                    {
                        "name": "q_range_max",
                        "kind": "absolute",
                        "source": "auto",
                        "value": max(q),
                        "unit": "Å⁻¹",
                        "uncertainty": self._no_uncertainty(),
                    },
                    {
                        "name": "total_points",
                        "kind": "absolute",
                        "source": "auto",
                        "value": len(q),
                        "unit": "count",
                        "uncertainty": self._no_uncertainty(),
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
                    "uncertainty": self._no_uncertainty(),
                }
            )

        # rev4 dropped descriptors.policy (block is now closed); outputs only.
        outputs = [
            {
                "label": f"automated_extraction_{now.strftime('%Y-%m-%d')}",
                "generated_utc": now.isoformat().replace("+00:00", "Z"),
                "generated_by": {"agent": "nr-isaac-format", "version": "0.1.0"},
                "descriptors": descriptors,
            }
        ]

        fit_output = self._map_fit_descriptors(reflectivity_model, now)
        if fit_output:
            outputs.append(fit_output)

        return {"outputs": outputs}

    def _map_fit_descriptors(
        self, model: dict | None, now: datetime
    ) -> dict[str, Any] | None:
        """Build a model-derived descriptor output from a fitted reflectivity model.

        Each fitted layer contributes thickness / SLD / roughness descriptors
        (``kind: "model"``) carrying the fitted σ as ``uncertainty.sigma``, plus a
        reduced-χ² descriptor when present. Attributed to the fitting software so
        it is distinct from this tool's automated extraction.
        """
        if not model:
            return None

        descriptors: list[dict[str, Any]] = []
        for layer in model.get("layers") or []:
            base = self._sanitize_descriptor_name(
                layer.get("name") or f"layer_{layer.get('layer_number', '')}"
            )
            thickness = layer.get("thickness")
            # Ambient/substrate layers are semi-infinite (thickness 0); skip those.
            if thickness:
                descriptors.append(
                    self._model_descriptor(
                        f"{base}_thickness", thickness, "Å", layer.get("thickness_std")
                    )
                )
            if layer.get("sld") is not None:
                descriptors.append(
                    self._model_descriptor(
                        f"{base}_sld", layer["sld"], "1e-6 Å⁻²", layer.get("sld_std")
                    )
                )
            if layer.get("interface") is not None:
                descriptors.append(
                    self._model_descriptor(
                        f"{base}_roughness", layer["interface"], "Å", layer.get("interface_std")
                    )
                )

        chi_squared = model.get("chi_squared")
        if chi_squared is not None:
            descriptors.append(
                self._model_descriptor("reduced_chi_squared", chi_squared, "dimensionless", None)
            )

        if not descriptors:
            return None

        generated_by: dict[str, Any] = {"agent": model.get("software") or "refl1d"}
        if model.get("software_version"):
            generated_by["version"] = model["software_version"]

        output: dict[str, Any] = {
            "label": "reflectivity_model_fit",
            "generated_utc": now.isoformat().replace("+00:00", "Z"),
            "generated_by": generated_by,
            "descriptors": descriptors,
        }
        return output

    @staticmethod
    def _model_descriptor(
        name: str, value: Any, unit: str, sigma: float | None
    ) -> dict[str, Any]:
        """A ``kind: "model"`` descriptor imported from a fit, σ keyed on sigma."""
        return {
            "name": name,
            "kind": "model",
            "source": "imported",
            "value": value,
            "unit": unit,
            "uncertainty": {"sigma": sigma},
        }

    @staticmethod
    def _sanitize_descriptor_name(raw: str) -> str:
        """Coerce a layer name into a schema-valid descriptor name stem.

        rev4 requires ``^[A-Za-z][A-Za-z0-9_]*(\\.[A-Za-z0-9_]+)*$``; layer names
        like "copper oxide" must become "copper_oxide".
        """
        stem = re.sub(r"[^0-9A-Za-z]+", "_", (raw or "").strip()).strip("_")
        if not stem:
            return "layer"
        if stem[0].isdigit():
            stem = f"layer_{stem}"
        return stem

    @staticmethod
    def _no_uncertainty() -> dict[str, Any]:
        """Uncertainty object for an auto-extracted value with no reported sigma.

        Schema rev4 models uncertainty as ``{sigma, unit, basis, ...}``. Our
        measured uncertainties are standard deviations, so we key on ``sigma``;
        ``None`` denotes no reported value. (rev4 removed the old
        ``{"type": "none"}`` shape.)
        """
        return {"sigma": None}

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

        # The manifest ``sample.description`` (passed through as ``sample_name``)
        # is a free-text description of the sample stack. Schema rev4 closes the
        # ``sample`` block, so surface it on ``sample.material.notes``.
        if sample_name and "material" in result:
            result["material"]["notes"] = sample_name

        # ``sample.geometry`` in schema rev3/rev4 is defined with a contradictory
        # ``{"type": "object", "enum": [<string keys>]}`` shape that no concrete
        # object can satisfy.  Until the schema is corrected upstream we omit
        # the geometry block; layer details remain available on the assembler
        # result for downstream tooling.
        return result

    # Valid provenance values per ISAAC v1-ornl-rev4 schema
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

    # Valid environment enum values per ISAAC v1-ornl-rev4 schema
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

    def _select_measurement_description(
        self, context_description: str | None, env: dict
    ) -> str | None:
        """Choose the free-text description to attach to the measurement.

        Prefers the explicit manifest ``context`` text, falling back to a
        free-text environment note (but not a bare environment enum keyword
        such as ``"in_situ"``, which carries no descriptive content).
        """
        if context_description:
            return context_description
        env_desc = (env or {}).get("description")
        if env_desc and env_desc != self._classify_environment(env_desc):
            return env_desc
        return None

    def _map_context(
        self,
        env: dict,
        description: str | None = None,
        electrochemistry: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Map environment record to ISAAC context block.

        Schema rev3/rev4 forbid free-form context keys (additionalProperties:
        false). Only ``environment``, ``temperature_K`` and the typed
        ``thermodynamics`` / ``electrochemistry`` blocks are emitted here. The
        free-text description is surfaced on ``measurement.series[].notes`` and
        ``ambient_medium`` via :meth:`_build_metadata_snapshot_asset`.
        """
        env = env or {}

        env_desc = env.get("description")
        if env_desc:
            environment_enum = self._classify_environment(env_desc)
            # A bare enum keyword (e.g. from the manifest ``environment:`` field)
            # is an explicit, authoritative declaration; free text is only a hint.
            explicit = (
                env_desc == environment_enum
                or env_desc.strip().lower() in self._ENVIRONMENT_MAP
            )
        else:
            environment_enum = self._classify_environment(description or "not specified")
            explicit = False

        # An *applied* potential implies an operating (operando) measurement, but
        # only when the environment was inferred — never override an explicit
        # declaration. Open-circuit (OCV) is not "operating", so it never bumps.
        if (
            electrochemistry
            and electrochemistry.get("control_mode") != "open_circuit"
            and not explicit
            and environment_enum == "ex_situ"
        ):
            environment_enum = "operando"

        result: dict[str, Any] = {
            "environment": environment_enum,
            "temperature_K": env.get("temperature")
            if env.get("temperature") is not None
            else 295.0,
        }

        if env.get("pressure"):
            result["thermodynamics"] = {"pressure_Pa": env["pressure"]}

        if electrochemistry:
            result["electrochemistry"] = electrochemistry

        return result

    # --- Electrochemistry parsing -------------------------------------------

    # Numeric applied potential, e.g. "-1 V", "+0.5 V", "0 V", "1.23V"
    # (ASCII or unicode-minus sign accepted).
    _POTENTIAL_VALUE_RE = re.compile(r"([+\-−]?\d+(?:\.\d+)?)\s*V\b")
    # Open-circuit conditions.
    _OCV_RE = re.compile(r"\bOCV\b|\bOCP\b|open[\s-]?circuit", re.IGNORECASE)
    # Reference-scale tokens. Acronyms are case-sensitive so the English word
    # "she" can never be mistaken for the SHE scale; slash-notation electrodes
    # are matched case-insensitively. Checked in order; first match wins.
    _POTENTIAL_SCALE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
        (re.compile(r"\bRHE\b"), "RHE"),
        (re.compile(r"\bSHE\b"), "SHE"),
        (re.compile(r"\bNHE\b"), "SHE"),  # NHE ≈ SHE
        (re.compile(r"\bSCE\b"), "SCE"),
        (re.compile(r"Ag\s*/\s*AgCl", re.IGNORECASE), "Ag/AgCl"),
        (re.compile(r"Hg\s*/\s*HgSO4", re.IGNORECASE), "Hg/HgSO4"),
        (re.compile(r"Hg\s*/\s*HgO", re.IGNORECASE), "Hg/HgO"),
    )

    def _parse_electrochemistry(self, text: str | None) -> dict[str, Any] | None:
        """Extract applied-potential info from a free-text description.

        Recognises open-circuit (OCV/OCP) and numeric potentials (e.g. ``-1 V``).
        Numeric potentials default to the SHE scale unless the text names another
        (RHE, Ag/AgCl, SCE, Hg/HgO, Hg/HgSO4). Returns an ``electrochemistry``
        block, or ``None`` when no potential is mentioned.
        """
        if not text:
            return None

        # OCV/OCP takes precedence: the cell is at open circuit regardless of any
        # measured value quoted alongside it.
        if self._OCV_RE.search(text):
            return {"control_mode": "open_circuit"}

        match = self._POTENTIAL_VALUE_RE.search(text)
        if not match:
            return None

        value = float(match.group(1).replace("−", "-"))
        scale = "SHE"  # default convention unless the text names another scale
        for pattern, name in self._POTENTIAL_SCALE_PATTERNS:
            if pattern.search(text):
                scale = name
                break

        return {
            "control_mode": "potentiostatic",
            "potential_setpoint_V": value,
            "potential_scale": scale,
        }

    def _build_metadata_snapshot_asset(self, env: dict) -> dict[str, Any] | None:
        """Build a ``metadata_snapshot`` asset preserving context fields
        that schema rev3/rev4 disallow under ``context``.

        Currently this captures only ``ambient_medium`` (free-text
        descriptions now ride on ``measurement.series[].notes``). Returns
        ``None`` when there is nothing to preserve.
        """
        env = env or {}
        ambient_medium = env.get("ambient_medium")
        if not ambient_medium:
            return None

        inline = json.dumps({"ambient_medium": ambient_medium}, sort_keys=True)
        import hashlib

        sha = hashlib.sha256(inline.encode("utf-8")).hexdigest()

        return {
            "asset_id": "context_metadata_snapshot",
            "content_role": "metadata_snapshot",
            "media_type": "application/json",
            "uri": "data:application/json;base64," + _b64(inline),
            "sha256": sha,
        }

    def _build_description_asset(self, text: str) -> dict[str, Any]:
        """Build a ``documentation`` asset carrying a free-text description.

        Used only as a fallback when there is no measurement block to host
        the description on ``measurement.series[].notes``, so it is not lost.
        """
        import hashlib

        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return {
            "asset_id": "measurement_description",
            "content_role": "documentation",
            "media_type": "text/markdown",
            "uri": "data:text/markdown;base64," + _b64(text),
            "sha256": sha,
        }

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
