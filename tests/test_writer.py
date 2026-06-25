"""Tests for the minimal IsaacWriter."""

import base64
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

from nr_isaac_format.writer import IsaacWriter, write_isaac_record


def _find_metadata_snapshot(record: dict) -> dict | None:
    """Return the metadata_snapshot asset from a record, or None."""
    for asset in record.get("assets", []) or []:
        if asset.get("content_role") == "metadata_snapshot":
            return asset
    return None


def _decode_snapshot(asset: dict) -> dict:
    """Decode a metadata_snapshot inline-data URI into its JSON payload."""
    uri = asset["uri"]
    prefix = "data:application/json;base64,"
    assert uri.startswith(prefix), uri
    return json.loads(base64.b64decode(uri[len(prefix):]).decode("utf-8"))


def create_mock_result(
    reflectivity: dict | None = None,
    sample: dict | None = None,
    environment: dict | None = None,
    reduced_file: str | None = None,
    reflectivity_model: dict | None = None,
):
    """Create a mock AssemblyResult for testing."""
    mock = MagicMock()
    mock.reflectivity = reflectivity
    mock.sample = sample
    mock.environment = environment
    mock.reduced_file = reduced_file
    mock.reflectivity_model = reflectivity_model
    mock.parquet_dir = None
    mock.model_file = None
    mock.warnings = []
    mock.errors = []
    return mock


class TestIsaacWriter:
    """Tests for IsaacWriter class."""

    def test_minimal_record(self):
        """Should create valid minimal ISAAC record."""
        result = create_mock_result()
        writer = IsaacWriter()
        record = writer.to_isaac(result)

        assert record["isaac_record_version"] == "1.05"
        assert record["record_type"] == "evidence"
        assert record["record_domain"] == "characterization"
        assert "record_id" in record
        assert len(record["record_id"]) == 26  # ULID length
        assert "timestamps" in record
        assert "created_utc" in record["timestamps"]

    def test_with_reflectivity_data(self):
        """Should map reflectivity data to measurement block."""
        result = create_mock_result(
            reflectivity={
                "facility": "SNS",
                "instrument_name": "REF_L",
                "run_start": datetime(2025, 1, 15, 10, 30, tzinfo=timezone.utc),
                "q": [0.01, 0.02, 0.03],
                "r": [0.95, 0.85, 0.70],
                "dr": [0.01, 0.01, 0.02],
                "dq": [0.001, 0.002, 0.003],
                "measurement_geometry": "front reflection",
            }
        )

        writer = IsaacWriter()
        record = writer.to_isaac(result)

        # Check source_type (rev2: top-level, replaces acquisition_source)
        assert record["source_type"] == "facility"
        assert "acquisition_source" not in record

        # Check measurement
        meas = record["measurement"]
        assert meas is not None
        series = meas["series"][0]
        assert series["series_id"] == "reflectivity_profile"
        assert series["independent_variables"][0]["name"] == "q"
        assert series["independent_variables"][0]["values"] == [0.01, 0.02, 0.03]

        channels = series["channels"]
        assert len(channels) == 3
        assert channels[0]["name"] == "R"
        assert channels[0]["role"] == "primary_signal"

        # Check descriptors
        desc = record["descriptors"]
        outputs = desc["outputs"][0]
        descriptors = outputs["descriptors"]
        names = [d["name"] for d in descriptors]
        assert "q_range_min" in names
        assert "q_range_max" in names
        assert "total_points" in names
        assert "measurement_geometry" in names
        # All descriptors must have uncertainty and valid source
        for d in descriptors:
            assert "uncertainty" in d
            assert d["source"] in ("auto", "manual", "imported")

    def test_with_sample_data(self):
        """Should map sample data when present."""
        result = create_mock_result(
            reflectivity={"facility": "SNS"},
            sample={
                "main_composition": "Fe/Si",
                "layers": [
                    {"material": "Fe", "thickness": 10.0},
                    {"material": "Si", "thickness": 500.0},
                ],
            },
        )

        writer = IsaacWriter()
        record = writer.to_isaac(result)

        assert "sample" in record
        assert record["sample"]["sample_form"] == "film"
        assert record["sample"]["material"]["name"] == "Fe/Si"
        assert record["sample"]["material"]["formula"] == "Fe/Si"
        # No provenance in enum for plain mock data → key omitted
        assert "provenance" not in record["sample"]["material"]
        # Schema rev3 has a self-contradictory geometry definition; the writer
        # omits the geometry block entirely until upstream is fixed.
        assert "geometry" not in record["sample"]

    def test_sample_provenance_mapping(self):
        """Should map known provenance strings to schema enum values."""
        result = create_mock_result(
            reflectivity={"facility": "SNS"},
            sample={
                "main_composition": "CuO",
                "provenance": "commercial",
                "layers": [],
            },
        )
        writer = IsaacWriter()
        record = writer.to_isaac(result)
        assert record["sample"]["material"]["provenance"] == "commercial"

    def test_sample_provenance_normalised(self):
        """Should normalise non-standard provenance to closest enum value."""
        result = create_mock_result(
            reflectivity={"facility": "SNS"},
            sample={
                "main_composition": "CuO",
                "provenance": "model_fitted",
                "layers": [],
            },
        )
        writer = IsaacWriter()
        record = writer.to_isaac(result)
        assert record["sample"]["material"]["provenance"] == "theoretical"

    def test_with_environment_data(self):
        """Should map environment data to context block (rev3 layout)."""
        result = create_mock_result(
            reflectivity={"facility": "SNS"},
            environment={
                "temperature": 298.0,
                "pressure": 101325.0,
                "ambient_medium": "D2O",
                "description": "in_situ",
            },
        )

        writer = IsaacWriter()
        record = writer.to_isaac(result)

        assert "context" in record
        ctx = record["context"]
        assert ctx["temperature_K"] == 298.0
        # rev3: pressure lives under thermodynamics
        assert ctx["thermodynamics"]["pressure_Pa"] == 101325.0
        assert ctx["environment"] == "in_situ"
        # rev3 forbids context.ambient_medium and context.description; they
        # are preserved in a metadata_snapshot asset instead.
        assert "ambient_medium" not in ctx
        assert "description" not in ctx
        snapshot = _find_metadata_snapshot(record)
        assert snapshot is not None
        payload = _decode_snapshot(snapshot)
        assert payload["ambient_medium"] == "D2O"

    def test_context_classifies_electrochemical(self):
        """Should classify electrochemical descriptions as operando and surface
        the free-text description on measurement.description."""
        result = create_mock_result(
            reflectivity={"facility": "SNS", "q": [0.01, 0.02], "r": [0.9, 0.8]},
            environment={
                "description": "Electrochemical cell, THF electrolyte, steady-state OCV",
            },
        )
        writer = IsaacWriter()
        record = writer.to_isaac(result)
        ctx = record["context"]
        assert ctx["environment"] == "operando"
        assert "description" not in ctx
        assert (
            record["measurement"]["series"][0]["notes"]
            == "Electrochemical cell, THF electrolyte, steady-state OCV"
        )
        # "OCV" → open-circuit control mode
        assert ctx["electrochemistry"] == {"control_mode": "open_circuit"}
        # No ambient_medium → no metadata_snapshot needed
        assert _find_metadata_snapshot(record) is None

    def test_context_defaults_required_fields(self):
        """Should default temperature_K and environment when not provided."""
        result = create_mock_result(
            reflectivity={"facility": "SNS"},
            environment={"ambient_medium": "air"},
        )

        writer = IsaacWriter()
        record = writer.to_isaac(result)

        ctx = record["context"]
        assert ctx["temperature_K"] == 295.0  # default
        assert ctx["environment"] == "ex_situ"  # default classification

    def test_system_includes_technique(self):
        """Should include required technique field in system block."""
        result = create_mock_result(
            reflectivity={
                "facility": "SNS",
                "instrument_name": "REF_L",
                "measurement_geometry": "front reflection",
            },
        )

        writer = IsaacWriter()
        record = writer.to_isaac(result)

        assert "system" in record
        assert record["system"]["technique"] == "neutron_reflectometry"
        assert record["system"]["domain"] == "experimental"

    def test_with_environment_description_no_env_record(self):
        """Should create context block from manifest environment_description."""
        result = create_mock_result(reflectivity={"facility": "SNS", "q": [0.01], "r": [0.9]})
        writer = IsaacWriter()
        record = writer.to_isaac(
            result, environment_description="Electrochemical cell, THF electrolyte"
        )

        assert "context" in record
        # Electrochemical → classified as operando
        assert record["context"]["environment"] == "operando"
        assert "description" not in record["context"]
        assert "temperature_K" in record["context"]  # required by schema
        assert (
            record["measurement"]["series"][0]["notes"] == "Electrochemical cell, THF electrolyte"
        )

    def test_environment_description_does_not_override_existing(self):
        """Should not override existing environment description."""
        result = create_mock_result(
            reflectivity={"facility": "SNS"},
            environment={"description": "in_situ"},
        )
        writer = IsaacWriter()
        record = writer.to_isaac(result, environment_description="From manifest")

        # Original description is "in_situ" which classifies directly
        assert record["context"]["environment"] == "in_situ"

    def test_context_description_from_manifest(self):
        """Should surface context_description on measurement.description."""
        result = create_mock_result(reflectivity={"facility": "SNS", "q": [0.01], "r": [0.9]})
        writer = IsaacWriter()
        record = writer.to_isaac(
            result,
            environment_description="operando",
            context_description="Electrochemical cell, THF electrolyte, steady-state OCV",
        )

        ctx = record["context"]
        assert ctx["environment"] == "operando"
        assert "description" not in ctx
        assert (
            record["measurement"]["series"][0]["notes"]
            == "Electrochemical cell, THF electrolyte, steady-state OCV"
        )
        assert ctx["electrochemistry"] == {"control_mode": "open_circuit"}

    def test_context_description_overrides_env_text(self):
        """Explicit context_description should take precedence over env description."""
        result = create_mock_result(
            reflectivity={"facility": "SNS", "q": [0.01], "r": [0.9]},
            environment={"description": "Electrochemical cell"},
        )
        writer = IsaacWriter()
        record = writer.to_isaac(
            result,
            context_description="Custom context note",
        )

        assert record["measurement"]["series"][0]["notes"] == "Custom context note"
        # Plain text with no potential → no electrochemistry block
        assert "electrochemistry" not in record["context"]

    def test_potential_setpoint_parsed(self):
        """A numeric applied potential → potentiostatic setpoint, default SHE."""
        result = create_mock_result(
            reflectivity={"facility": "SNS", "q": [0.01], "r": [0.9]},
        )
        writer = IsaacWriter()
        record = writer.to_isaac(
            result, context_description="Operando NR held at -1 V; back reflection."
        )
        ec = record["context"]["electrochemistry"]
        assert ec == {
            "control_mode": "potentiostatic",
            "potential_setpoint_V": -1.0,
            "potential_scale": "SHE",
        }
        # Applied potential implies operando even without the keyword
        assert record["context"]["environment"] == "operando"

    def test_potential_scale_detected(self):
        """An explicit reference scale overrides the SHE default."""
        result = create_mock_result(
            reflectivity={"facility": "SNS", "q": [0.01], "r": [0.9]},
        )
        writer = IsaacWriter()
        record = writer.to_isaac(result, context_description="Measured at +0.5 V vs RHE.")
        ec = record["context"]["electrochemistry"]
        assert ec["potential_setpoint_V"] == 0.5
        assert ec["potential_scale"] == "RHE"
        assert ec["control_mode"] == "potentiostatic"

    def test_ocv_takes_precedence_over_value(self):
        """OCV → open_circuit even when a measured value is quoted alongside."""
        result = create_mock_result(
            reflectivity={"facility": "SNS", "q": [0.01], "r": [0.9]},
        )
        writer = IsaacWriter()
        record = writer.to_isaac(result, context_description="At OCV (about 0.2 V vs RHE).")
        assert record["context"]["electrochemistry"] == {"control_mode": "open_circuit"}

    def test_explicit_environment_not_overridden_by_potential(self):
        """An explicit manifest environment (ex_situ) must survive even when the
        context mentions OCV (e.g. an in-air open-circuit measurement)."""
        result = create_mock_result(reflectivity={"facility": "SNS", "q": [0.01], "r": [0.9]})
        writer = IsaacWriter()
        record = writer.to_isaac(
            result,
            environment_description="ex_situ",
            context_description="Deposited Cu on Ti on Si, in air (OCV).",
        )
        assert record["context"]["environment"] == "ex_situ"
        assert record["context"]["electrochemistry"] == {"control_mode": "open_circuit"}

    def test_no_potential_no_electrochemistry(self):
        """A description with no potential must not emit an electrochemistry block."""
        result = create_mock_result(
            reflectivity={"facility": "SNS", "q": [0.01], "r": [0.9]},
            environment={"temperature": 298.0},
        )
        writer = IsaacWriter()
        record = writer.to_isaac(
            result, context_description="Si / 3 nm Ti / 50 nm Cu; DREAM joint fit, chi2=1.6."
        )
        assert "electrochemistry" not in record["context"]

    def test_description_fallback_documentation_asset(self):
        """With no measurement series, the description is preserved as a
        documentation asset rather than dropped."""
        result = create_mock_result(reflectivity={"facility": "SNS"})  # no q/r
        writer = IsaacWriter()
        record = writer.to_isaac(result, context_description="Back-reflection through Si substrate")

        assert "measurement" not in record
        docs = [a for a in record.get("assets", []) if a["content_role"] == "documentation"]
        assert len(docs) == 1
        prefix = "data:text/markdown;base64,"
        assert docs[0]["uri"].startswith(prefix)
        text = base64.b64decode(docs[0]["uri"][len(prefix):]).decode("utf-8")
        assert text == "Back-reflection through Si substrate"

    def test_raw_file_path_from_manifest(self):
        """Should include manifest raw_file_path in assets."""
        result = create_mock_result(
            reflectivity={"facility": "SNS", "q": [0.01], "r": [0.9]},
        )
        writer = IsaacWriter()
        record = writer.to_isaac(
            result,
            raw_file_path="/SNS/REF_L/IPTS-34347/nexus/REF_L_218386.nxs.h5",
        )

        assert "assets" in record
        raw_assets = [a for a in record["assets"] if a["content_role"] == "raw_data_pointer"]
        assert len(raw_assets) == 1
        assert raw_assets[0]["uri"] == "/SNS/REF_L/IPTS-34347/nexus/REF_L_218386.nxs.h5"

    def test_raw_file_path_overrides_refl_metadata(self):
        """Manifest raw_file_path should take precedence over refl metadata."""
        result = create_mock_result(
            reflectivity={
                "facility": "SNS",
                "raw_file_path": "/old/path.nxs.h5",
                "q": [0.01],
                "r": [0.9],
            },
        )
        writer = IsaacWriter()
        record = writer.to_isaac(
            result,
            raw_file_path="/new/manifest/path.nxs.h5",
        )

        raw_assets = [a for a in record["assets"] if a["content_role"] == "raw_data_pointer"]
        assert len(raw_assets) == 1
        assert raw_assets[0]["uri"] == "/new/manifest/path.nxs.h5"

    def test_write_to_file(self, tmp_path):
        """Should write ISAAC record to JSON file."""
        result = create_mock_result(
            reflectivity={
                "facility": "SNS",
                "q": [0.01],
                "r": [0.95],
            }
        )

        output_path = tmp_path / "output.json"
        writer = IsaacWriter()
        path = writer.write(result, output_path)

        assert path.exists()
        with open(path) as f:
            record = json.load(f)
        assert record["isaac_record_version"] == "1.05"

    def test_write_with_output_dir(self, tmp_path):
        """Should write to output_dir when no path specified."""
        result = create_mock_result()

        writer = IsaacWriter(output_dir=tmp_path)
        path = writer.write(result)

        assert path == tmp_path / "isaac_record.json"
        assert path.exists()


class TestConvenienceFunction:
    """Tests for write_isaac_record convenience function."""

    def test_write_isaac_record(self, tmp_path):
        """Should write record using convenience function."""
        result = create_mock_result(
            reflectivity={"facility": "SNS", "q": [0.01], "r": [0.9]}
        )

        output_path = tmp_path / "record.json"
        path = write_isaac_record(result, output_path)

        assert path.exists()
        with open(path) as f:
            record = json.load(f)
        assert "record_id" in record


class TestSampleFromManifest:
    """Tests for sample_name / sample_formula override from manifest."""

    def test_creates_sample_when_no_assembler_sample(self):
        """Should create sample block from manifest fields when result.sample is None."""
        result = create_mock_result(reflectivity={"facility": "SNS"})
        writer = IsaacWriter()
        record = writer.to_isaac(
            result, sample_name="Cu in THF on Si", sample_formula="THF | CuOx | Cu | Ti | Si"
        )

        assert "sample" in record
        assert record["sample"]["sample_form"] == "film"
        assert record["sample"]["material"]["name"] == "Cu in THF on Si"
        assert record["sample"]["material"]["formula"] == "THF | CuOx | Cu | Ti | Si"

    def test_overrides_unknown_composition(self):
        """Should replace 'Unknown' composition with manifest fields."""
        result = create_mock_result(
            reflectivity={"facility": "SNS"},
            sample={"main_composition": "Unknown", "layers": []},
        )
        writer = IsaacWriter()
        record = writer.to_isaac(
            result, sample_name="Cu in THF on Si", sample_formula="THF | CuOx | Cu | Ti | Si"
        )

        assert record["sample"]["material"]["name"] == "Cu in THF on Si"
        assert record["sample"]["material"]["formula"] == "THF | CuOx | Cu | Ti | Si"

    def test_does_not_override_valid_composition(self):
        """Should NOT override an existing valid material from the assembler."""
        result = create_mock_result(
            reflectivity={"facility": "SNS"},
            sample={"main_composition": "Fe/Si", "layers": []},
        )
        writer = IsaacWriter()
        record = writer.to_isaac(
            result, sample_name="Cu in THF on Si", sample_formula="THF | CuOx | Cu | Ti | Si"
        )

        # Assembler composition wins for material.name ...
        assert record["sample"]["material"]["name"] == "Fe/Si"
        # ... but the manifest sample.description is still surfaced readably.
        assert record["sample"]["material"]["notes"] == "Cu in THF on Si"

    def test_sample_description_when_no_assembler_sample(self):
        """sample_name populates sample.material.notes in the synthesized block."""
        result = create_mock_result(reflectivity={"facility": "SNS"})
        writer = IsaacWriter()
        record = writer.to_isaac(result, sample_name="air / CuOx / 50 nm Cu / 3 nm Ti on Si")

        assert record["sample"]["material"]["notes"] == "air / CuOx / 50 nm Cu / 3 nm Ti on Si"

    def test_no_manifest_fields_no_sample(self):
        """Should not create sample block when no manifest sample fields and no assembler sample."""
        result = create_mock_result(reflectivity={"facility": "SNS"})
        writer = IsaacWriter()
        record = writer.to_isaac(result, sample_name=None, sample_formula=None)

        assert "sample" not in record

    def test_name_only_uses_name_for_both(self):
        """When only sample_name is given, use it for both name and formula."""
        result = create_mock_result(reflectivity={"facility": "SNS"})
        writer = IsaacWriter()
        record = writer.to_isaac(result, sample_name="Cu in THF on Si")

        assert record["sample"]["material"]["name"] == "Cu in THF on Si"
        assert record["sample"]["material"]["formula"] == "Cu in THF on Si"

    def test_formula_only_uses_formula_for_both(self):
        """When only sample_formula is given, use it for both name and formula."""
        result = create_mock_result(reflectivity={"facility": "SNS"})
        writer = IsaacWriter()
        record = writer.to_isaac(result, sample_formula="THF | CuOx | Cu | Ti | Si")

        assert record["sample"]["material"]["name"] == "THF | CuOx | Cu | Ti | Si"
        assert record["sample"]["material"]["formula"] == "THF | CuOx | Cu | Ti | Si"


class TestFitDescriptors:
    """Fitted reflectivity_model → model-derived descriptors (kind: model)."""

    def _result_with_model(self, chi_squared=None):
        return create_mock_result(
            reflectivity={"facility": "SNS", "q": [0.01, 0.02], "r": [0.9, 0.8]},
            reflectivity_model={
                "software": "refl1d",
                "software_version": "1.0.1",
                "chi_squared": chi_squared,
                "layers": [
                    # ambient: thickness 0 (semi-infinite) but a real interface roughness
                    {"layer_number": 1, "name": "air", "thickness": 0.0,
                     "interface": 12.1, "interface_std": None, "sld": 0.0, "sld_std": None},
                    {"layer_number": 2, "name": "copper oxide", "thickness": 24.8,
                     "thickness_std": 1.5, "interface": 12.9, "interface_std": 2.1,
                     "sld": 4.55, "sld_std": 0.07},
                    {"layer_number": 3, "name": "Cu", "thickness": 371.3,
                     "thickness_std": 4.76, "interface": 5.6, "interface_std": 1.2,
                     "sld": 6.565, "sld_std": 0.0073},
                ],
            },
        )

    def _fit_output(self, record):
        outs = [o for o in record["descriptors"]["outputs"] if o["label"] == "reflectivity_model_fit"]
        return outs[0] if outs else None

    def test_fitted_layers_become_model_descriptors(self):
        record = IsaacWriter().to_isaac(self._result_with_model())
        out = self._fit_output(record)
        assert out is not None
        assert out["generated_by"] == {"agent": "refl1d", "version": "1.0.1"}
        by_name = {d["name"]: d for d in out["descriptors"]}

        # ambient thickness (0) skipped, but its roughness + sld are kept
        assert "air_thickness" not in by_name
        assert "air_roughness" in by_name

        # spaces sanitized; fitted value + σ carried; kind/source are model/imported
        cu_t = by_name["copper_oxide_thickness"]
        assert cu_t["value"] == 24.8
        assert cu_t["kind"] == "model"
        assert cu_t["source"] == "imported"
        assert cu_t["uncertainty"] == {"sigma": 1.5}
        assert by_name["Cu_thickness"]["value"] == 371.3
        assert by_name["Cu_thickness"]["uncertainty"] == {"sigma": 4.76}
        assert by_name["Cu_sld"]["unit"] == "1e-6 Å⁻²"
        # σ absent → sigma None, not dropped
        assert by_name["air_roughness"]["uncertainty"] == {"sigma": None}

    def test_chi_squared_descriptor_when_present(self):
        record = IsaacWriter().to_isaac(self._result_with_model(chi_squared=1.143))
        out = self._fit_output(record)
        names = {d["name"] for d in out["descriptors"]}
        assert "reduced_chi_squared" in names
        chi = next(d for d in out["descriptors"] if d["name"] == "reduced_chi_squared")
        assert chi["value"] == 1.143

    def test_no_model_no_fit_output(self):
        record = IsaacWriter().to_isaac(
            create_mock_result(reflectivity={"facility": "SNS", "q": [0.01], "r": [0.9]})
        )
        assert self._fit_output(record) is None
        # the automated-extraction output is still present
        assert record["descriptors"]["outputs"][0]["label"].startswith("automated_extraction")


class TestSchemaValidation:
    """Guard: writer output must validate against the latest bundled schema."""

    def test_output_validates_against_latest_bundled_schema(self):
        from pathlib import Path

        import jsonschema

        from nr_isaac_format.cli import _find_latest_schema

        schema_dir = Path(__file__).resolve().parents[1] / "src/nr_isaac_format/schema"
        schema = json.loads(_find_latest_schema(schema_dir).read_text())

        result = create_mock_result(
            reflectivity={
                "facility": "SNS",
                "instrument_name": "REF_L",
                "q": [0.01, 0.02, 0.03],
                "r": [0.9, 0.8, 0.7],
                "dr": [0.01, 0.01, 0.02],
                "dq": [0.001, 0.002, 0.003],
                "measurement_geometry": "back reflection",
            },
            sample={"main_composition": "Cu", "provenance": "commercial", "layers": []},
            environment={"temperature": 298.0, "ambient_medium": "D2O"},
            reflectivity_model={
                "software": "refl1d",
                "software_version": "1.0.1",
                "chi_squared": 1.143,
                "layers": [
                    {"layer_number": 1, "name": "copper oxide", "thickness": 24.8,
                     "thickness_std": 1.5, "interface": 12.9, "interface_std": 2.1,
                     "sld": 4.55, "sld_std": 0.07},
                ],
            },
        )
        writer = IsaacWriter()
        record = writer.to_isaac(
            result,
            context_description="Operando NR through Si at -1 V vs RHE; DREAM joint fit.",
            sample_name="air / CuOx / 50 nm Cu / 3 nm Ti on Si",
        )

        jsonschema.validate(record, schema)  # raises on any rev4 violation
        # fitted-model descriptors are present and schema-valid
        fit = [o for o in record["descriptors"]["outputs"] if o["label"] == "reflectivity_model_fit"]
        assert fit and any(d["name"] == "reduced_chi_squared" for d in fit[0]["descriptors"])

        # Spot-check the rev4 homes for the free-text descriptions and fixes.
        assert record["measurement"]["series"][0]["notes"].startswith("Operando")
        assert record["sample"]["material"]["notes"].startswith("air /")
        first_unc = record["descriptors"]["outputs"][0]["descriptors"][0]["uncertainty"]
        assert first_unc == {"sigma": None}
        assert "policy" not in record["descriptors"]
        # Parsed applied potential lands in the typed electrochemistry block.
        assert record["context"]["electrochemistry"] == {
            "control_mode": "potentiostatic",
            "potential_setpoint_V": -1.0,
            "potential_scale": "RHE",
        }
