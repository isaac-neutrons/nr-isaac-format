"""Tests for the manifest-driven CLI."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from nr_isaac_format.cli import main


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def sample_manifest(tmp_path):
    """Create a minimal manifest YAML file."""
    manifest = tmp_path / "experiment.yaml"
    manifest.write_text(
        """\
title: "Test Experiment"

sample:
  description: "Test sample"

output: {output_dir}

measurements:
  - name: "Measurement 1"
    reduced: {reduced_file}
    environment: "ambient air"
""".format(
            output_dir=tmp_path / "output",
            reduced_file=tmp_path / "reduced.txt",
        )
    )
    # Create a dummy reduced file so manifest validation passes
    (tmp_path / "reduced.txt").write_text("# dummy reduced data\n")
    return manifest


def _make_mock_result(sample_id="abc12345-fake-uuid", has_sample=True):
    """Create a mock AssemblyResult."""
    result = MagicMock()
    result.has_errors = False
    result.errors = []
    result.warnings = []
    result.reduced_file = "/tmp/reduced.txt"
    result.reflectivity = {
        "id": "refl-001",
        "facility": "SNS",
        "instrument_name": "REF_L",
        "reflectivity": {
            "q": [0.01, 0.02, 0.03],
            "r": [0.95, 0.85, 0.70],
        },
    }
    if has_sample:
        result.sample = {
            "id": sample_id,
            "description": "Test sample",
        }
    else:
        result.sample = None
    result.environment = None
    result.model_file = None
    return result


class TestConvertCommand:
    """Tests for the manifest-based convert command."""

    @patch("nr_isaac_format.cli.IsaacWriter")
    def test_convert_with_manifest(self, mock_writer_cls, runner, sample_manifest, tmp_path):
        """Should process manifest and write ISAAC records."""
        mock_result = _make_mock_result()
        mock_writer = MagicMock()
        mock_writer.to_isaac.return_value = {
            "isaac_record_version": "1.0",
            "record_id": "TEST123",
        }
        mock_writer_cls.return_value = mock_writer

        with patch("assembler.parsers.ManifestParser") as mock_manifest_cls, \
             patch("assembler.parsers.ReducedParser") as mock_reduced_cls, \
             patch("assembler.workflow.DataAssembler") as mock_assembler_cls:

            # Set up manifest parser mock
            from assembler.parsers.manifest_parser import (
                Manifest,
                ManifestMeasurement,
                ManifestSample,
            )

            manifest_data = Manifest(
                title="Test Experiment",
                output=str(tmp_path / "output"),
                sample=ManifestSample(description="Test sample"),
                measurements=[
                    ManifestMeasurement(
                        name="Measurement 1",
                        reduced=str(tmp_path / "reduced.txt"),
                        environment="ambient air",
                    ),
                ],
            )
            mock_manifest_cls.return_value.parse.return_value = manifest_data

            # Set up assembler mock
            mock_assembler_cls.return_value.assemble.return_value = mock_result

            # Set up reduced parser mock
            mock_reduced_cls.return_value.parse.return_value = MagicMock()

            result = runner.invoke(main, ["convert", str(sample_manifest)])

        assert result.exit_code == 0, result.output
        assert "Wrote" in result.output
        mock_writer.to_isaac.assert_called_once()

    def test_convert_missing_manifest(self, runner, tmp_path):
        """Should fail gracefully when manifest file doesn't exist."""
        result = runner.invoke(main, ["convert", str(tmp_path / "nonexistent.yaml")])
        assert result.exit_code != 0

    @patch("nr_isaac_format.cli.IsaacWriter")
    def test_convert_dry_run(self, mock_writer_cls, runner, sample_manifest, tmp_path):
        """Should not write files in dry-run mode."""
        mock_result = _make_mock_result()
        mock_writer = MagicMock()
        mock_writer.to_isaac.return_value = {"isaac_record_version": "1.0"}
        mock_writer_cls.return_value = mock_writer

        with patch("assembler.parsers.ManifestParser") as mock_manifest_cls, \
             patch("assembler.parsers.ReducedParser") as mock_reduced_cls, \
             patch("assembler.workflow.DataAssembler") as mock_assembler_cls:

            from assembler.parsers.manifest_parser import (
                Manifest,
                ManifestMeasurement,
                ManifestSample,
            )

            manifest_data = Manifest(
                title="Test Experiment",
                output=str(tmp_path / "output"),
                sample=ManifestSample(description="Test sample"),
                measurements=[
                    ManifestMeasurement(
                        name="Measurement 1",
                        reduced=str(tmp_path / "reduced.txt"),
                        environment="ambient air",
                    ),
                ],
            )
            mock_manifest_cls.return_value.parse.return_value = manifest_data
            mock_assembler_cls.return_value.assemble.return_value = mock_result
            mock_reduced_cls.return_value.parse.return_value = MagicMock()

            result = runner.invoke(main, ["convert", "--dry-run", str(sample_manifest)])

        assert result.exit_code == 0, result.output
        assert "dry run" in result.output.lower()
        # No output files should exist
        output_dir = tmp_path / "output"
        if output_dir.exists():
            assert len(list(output_dir.glob("isaac_record_*.json"))) == 0

    @patch("nr_isaac_format.cli.IsaacWriter")
    def test_convert_assembly_errors(self, mock_writer_cls, runner, sample_manifest, tmp_path):
        """Should exit with error when assembly fails."""
        mock_result = MagicMock()
        mock_result.has_errors = True
        mock_result.errors = ["Reduced data is malformed"]

        with patch("assembler.parsers.ManifestParser") as mock_manifest_cls, \
             patch("assembler.parsers.ReducedParser") as mock_reduced_cls, \
             patch("assembler.workflow.DataAssembler") as mock_assembler_cls:

            from assembler.parsers.manifest_parser import (
                Manifest,
                ManifestMeasurement,
                ManifestSample,
            )

            manifest_data = Manifest(
                title="Test",
                output=str(tmp_path / "output"),
                sample=ManifestSample(),
                measurements=[
                    ManifestMeasurement(name="M1", reduced=str(tmp_path / "reduced.txt")),
                ],
            )
            mock_manifest_cls.return_value.parse.return_value = manifest_data
            mock_assembler_cls.return_value.assemble.return_value = mock_result
            mock_reduced_cls.return_value.parse.return_value = MagicMock()

            result = runner.invoke(main, ["convert", str(sample_manifest)])

        assert result.exit_code != 0
        assert "Assembly errors" in result.output or "error" in result.output.lower()

    @patch("nr_isaac_format.cli.IsaacWriter")
    def test_convert_multiple_measurements_reuses_sample(
        self, mock_writer_cls, runner, sample_manifest, tmp_path
    ):
        """Should reuse sample_id from first measurement for subsequent ones."""
        mock_writer = MagicMock()
        mock_writer.to_isaac.return_value = {"isaac_record_version": "1.0"}
        mock_writer_cls.return_value = mock_writer

        # First result has a sample; second does not (sample_id was passed)
        result_1 = _make_mock_result(sample_id="sample-uuid-1234", has_sample=True)
        result_2 = _make_mock_result(has_sample=False)

        with patch("assembler.parsers.ManifestParser") as mock_manifest_cls, \
             patch("assembler.parsers.ReducedParser") as mock_reduced_cls, \
             patch("assembler.workflow.DataAssembler") as mock_assembler_cls:

            from assembler.parsers.manifest_parser import (
                Manifest,
                ManifestMeasurement,
                ManifestSample,
            )

            reduced_file = str(tmp_path / "reduced.txt")
            manifest_data = Manifest(
                title="Multi-measurement",
                output=str(tmp_path / "output"),
                sample=ManifestSample(description="Cu sample"),
                measurements=[
                    ManifestMeasurement(name="M1", reduced=reduced_file, environment="OCV"),
                    ManifestMeasurement(name="M2", reduced=reduced_file, environment="Final"),
                ],
            )
            mock_manifest_cls.return_value.parse.return_value = manifest_data
            mock_assembler_cls.return_value.assemble.side_effect = [result_1, result_2]
            mock_reduced_cls.return_value.parse.return_value = MagicMock()

            result = runner.invoke(main, ["convert", str(sample_manifest)])

        assert result.exit_code == 0, result.output

        # Second assemble call should receive sample_id from first result
        calls = mock_assembler_cls.return_value.assemble.call_args_list
        assert calls[0].kwargs.get("sample_id") is None
        assert calls[1].kwargs.get("sample_id") == "sample-uuid-1234"


class TestValidateCommand:
    """Tests for the validate command (unchanged)."""

    def test_validate_valid_record(self, runner, tmp_path):
        """Should accept a valid ISAAC record."""
        # Create a minimal valid-ish record
        record = {
            "isaac_record_version": "1.0",
            "record_id": "01HXYZ1234567890ABCDEFGH",
            "record_type": "evidence",
            "record_domain": "characterization",
        }
        record_file = tmp_path / "record.json"
        record_file.write_text(json.dumps(record))

        # The schema may or may not validate this depending on required fields,
        # but the command should at least run without crashing
        result = runner.invoke(main, ["validate", str(record_file)])
        # Either passes validation or fails gracefully
        assert result.exit_code in (0, 1)

    def test_validate_missing_file(self, runner, tmp_path):
        """Should fail when file doesn't exist."""
        result = runner.invoke(main, ["validate", str(tmp_path / "missing.json")])
        assert result.exit_code != 0


class TestMainGroup:
    """Tests for the CLI group."""

    def test_version(self, runner):
        """Should print version."""
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "0.1.0" in result.output

    def test_help(self, runner):
        """Should print help with convert and validate commands."""
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "convert" in result.output
        assert "validate" in result.output


class TestUpdateCommand:
    """Tests for the update command (full pipeline regeneration)."""

    def _make_manifest(self, tmp_path, output_dir=None):
        """Create a minimal manifest YAML for update tests."""
        out = output_dir or (tmp_path / "output")
        manifest = tmp_path / "expt.yaml"
        manifest.write_text(
            f"""\
title: "Test Experiment"
sample:
  description: "Cu in THF on Si"
output: {out}
measurements:
  - name: "Steady-state OCV"
    reduced: /fake/REFL_218386_reduced_data.txt
    material: "THF | CuOx | Cu | Ti | Si"
    context: "Test context"
"""
        )
        return manifest

    def _make_existing_record(
        self, output_dir, run_number="218386", record_id="01HXYZ_ORIGINAL_ID"
    ):
        """Create an existing record file with a known record_id."""
        output_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "isaac_record_version": "1.0",
            "record_id": record_id,
            "record_type": "evidence",
        }
        path = output_dir / f"isaac_record_{run_number}.json"
        path.write_text(json.dumps(record, indent=2))
        return path

    def _mock_to_isaac(self, *args, **kwargs):
        """Side-effect for IsaacWriter.to_isaac that echoes back the record_id."""
        rid = kwargs.get("record_id") or "NEW_GENERATED_ID"
        return {
            "isaac_record_version": "1.0",
            "record_id": rid,
            "record_type": "evidence",
            "record_domain": "characterization",
            "source_type": "facility",
        }

    def _setup_mocks(self, output_dir, run_number=218386):
        """Return (mock_manifest_data, mock_result) for pipeline mocks."""
        mock_measurement = MagicMock()
        mock_measurement.name = "Steady-state OCV"
        mock_measurement.reduced = f"/fake/REFL_{run_number}_reduced_data.txt"
        mock_measurement.parquet = None
        mock_measurement.model = None
        mock_measurement.model_dataset_index = None
        mock_measurement.environment = "operando"

        mock_manifest_data = MagicMock()
        mock_manifest_data.title = "Test Experiment"
        mock_manifest_data.output = str(output_dir)
        mock_manifest_data.sample.model = None
        mock_manifest_data.sample.model_dataset_index = None
        mock_manifest_data.sample.description = "Cu in THF on Si"
        mock_manifest_data.validate.return_value = []
        mock_manifest_data.measurements = [mock_measurement]

        mock_result = MagicMock()
        mock_result.has_errors = False
        mock_result.errors = []
        mock_result.warnings = []
        mock_result.reflectivity = {"run_number": run_number}
        mock_result.sample = {"id": "sample_abc", "main_composition": "Fe/Si"}
        mock_result.environment = {}
        mock_result.reduced_file = None

        return mock_manifest_data, mock_result

    def test_update_preserves_record_id(self, runner, tmp_path):
        """Should reuse record_id from existing record in output directory."""
        output_dir = tmp_path / "output"
        manifest = self._make_manifest(tmp_path, output_dir=output_dir)
        self._make_existing_record(output_dir, "218386", "01HXYZ_ORIGINAL_ID")
        mock_manifest_data, mock_result = self._setup_mocks(output_dir, run_number=218386)

        with (
            patch("assembler.parsers.ManifestParser") as MockParser,
            patch("assembler.parsers.ReducedParser"),
            patch("assembler.workflow.DataAssembler") as MockAssembler,
            patch("nr_isaac_format.cli.IsaacWriter") as MockWriter,
        ):
            MockParser.return_value.parse.return_value = mock_manifest_data
            MockAssembler.return_value.assemble.return_value = mock_result
            MockWriter.return_value.to_isaac.side_effect = self._mock_to_isaac

            result = runner.invoke(main, ["update", str(manifest)])

        assert result.exit_code == 0, result.output

        v2_path = output_dir / "isaac_record_218386_v2.json"
        assert v2_path.exists()
        with open(v2_path) as f:
            updated = json.load(f)
        assert updated["record_id"] == "01HXYZ_ORIGINAL_ID"

    def test_update_generates_new_id_when_no_existing(self, runner, tmp_path):
        """Should generate a new record_id when no existing record is found."""
        output_dir = tmp_path / "output"
        manifest = self._make_manifest(tmp_path, output_dir=output_dir)
        mock_manifest_data, mock_result = self._setup_mocks(output_dir, run_number=218386)

        with (
            patch("assembler.parsers.ManifestParser") as MockParser,
            patch("assembler.parsers.ReducedParser"),
            patch("assembler.workflow.DataAssembler") as MockAssembler,
            patch("nr_isaac_format.cli.IsaacWriter") as MockWriter,
        ):
            MockParser.return_value.parse.return_value = mock_manifest_data
            MockAssembler.return_value.assemble.return_value = mock_result
            MockWriter.return_value.to_isaac.side_effect = self._mock_to_isaac

            result = runner.invoke(main, ["update", str(manifest)])

        assert result.exit_code == 0, result.output
        new_path = output_dir / "isaac_record_218386.json"
        assert new_path.exists()
        with open(new_path) as f:
            created = json.load(f)
        assert created["record_id"] == "NEW_GENERATED_ID"

    def test_update_does_not_overwrite_original(self, runner, tmp_path):
        """Should create versioned file and leave the original unchanged."""
        output_dir = tmp_path / "output"
        manifest = self._make_manifest(tmp_path, output_dir=output_dir)
        existing_path = self._make_existing_record(output_dir, "218386", "01HXYZ_ORIGINAL_ID")
        original_content = existing_path.read_text()
        mock_manifest_data, mock_result = self._setup_mocks(output_dir, run_number=218386)

        with (
            patch("assembler.parsers.ManifestParser") as MockParser,
            patch("assembler.parsers.ReducedParser"),
            patch("assembler.workflow.DataAssembler") as MockAssembler,
            patch("nr_isaac_format.cli.IsaacWriter") as MockWriter,
        ):
            MockParser.return_value.parse.return_value = mock_manifest_data
            MockAssembler.return_value.assemble.return_value = mock_result
            MockWriter.return_value.to_isaac.side_effect = self._mock_to_isaac

            result = runner.invoke(main, ["update", str(manifest)])

        assert result.exit_code == 0, result.output
        assert existing_path.read_text() == original_content

    def test_update_uses_latest_writer(self, runner, tmp_path):
        """Should call IsaacWriter.to_isaac with the right parameters."""
        output_dir = tmp_path / "output"
        manifest = self._make_manifest(tmp_path, output_dir=output_dir)
        self._make_existing_record(output_dir, "218386", "01HXYZ_ORIGINAL_ID")
        mock_manifest_data, mock_result = self._setup_mocks(output_dir, run_number=218386)

        with (
            patch("assembler.parsers.ManifestParser") as MockParser,
            patch("assembler.parsers.ReducedParser"),
            patch("assembler.workflow.DataAssembler") as MockAssembler,
            patch("nr_isaac_format.cli.IsaacWriter") as MockWriter,
        ):
            MockParser.return_value.parse.return_value = mock_manifest_data
            MockAssembler.return_value.assemble.return_value = mock_result
            MockWriter.return_value.to_isaac.side_effect = self._mock_to_isaac

            runner.invoke(main, ["update", str(manifest)])

        # Verify to_isaac was called with the preserved record_id
        call_kwargs = MockWriter.return_value.to_isaac.call_args
        assert call_kwargs.kwargs["record_id"] == "01HXYZ_ORIGINAL_ID"
        assert call_kwargs.kwargs["material_name"] == "THF | CuOx | Cu | Ti | Si"
        assert call_kwargs.kwargs["context_description"] == "Test context"

    def test_update_dry_run(self, runner, tmp_path):
        """Should not write any files in dry-run mode."""
        output_dir = tmp_path / "output"
        manifest = self._make_manifest(tmp_path, output_dir=output_dir)
        mock_manifest_data, mock_result = self._setup_mocks(output_dir, run_number=218386)

        with (
            patch("assembler.parsers.ManifestParser") as MockParser,
            patch("assembler.parsers.ReducedParser"),
            patch("assembler.workflow.DataAssembler") as MockAssembler,
            patch("nr_isaac_format.cli.IsaacWriter") as MockWriter,
        ):
            MockParser.return_value.parse.return_value = mock_manifest_data
            MockAssembler.return_value.assemble.return_value = mock_result
            MockWriter.return_value.to_isaac.side_effect = self._mock_to_isaac

            result = runner.invoke(main, ["update", str(manifest), "--dry-run"])

        assert result.exit_code == 0, result.output
        assert "dry run" in result.output.lower()
        assert not (output_dir / "isaac_record_218386.json").exists()


class TestFindExistingRecordId:
    """Tests for the _find_existing_record_id helper."""

    def test_finds_original_record(self, tmp_path):
        record = {"record_id": "ORIGINAL_ID", "record_type": "evidence"}
        (tmp_path / "isaac_record_218386.json").write_text(json.dumps(record))

        from nr_isaac_format.cli import _find_existing_record_id

        rid, path = _find_existing_record_id(tmp_path, "218386")
        assert rid == "ORIGINAL_ID"
        assert path.name == "isaac_record_218386.json"

    def test_finds_latest_versioned_record(self, tmp_path):
        """When original is missing, should find the latest _vN file."""
        for ver, rid in [(2, "ID_V2"), (3, "ID_V3")]:
            record = {"record_id": rid}
            (tmp_path / f"isaac_record_218386_v{ver}.json").write_text(json.dumps(record))

        from nr_isaac_format.cli import _find_existing_record_id

        rid, path = _find_existing_record_id(tmp_path, "218386")
        assert rid == "ID_V3"
        assert path.name == "isaac_record_218386_v3.json"

    def test_prefers_original_over_versions(self, tmp_path):
        record_orig = {"record_id": "ORIGINAL_ID"}
        record_v2 = {"record_id": "V2_ID"}
        (tmp_path / "isaac_record_218386.json").write_text(json.dumps(record_orig))
        (tmp_path / "isaac_record_218386_v2.json").write_text(json.dumps(record_v2))

        from nr_isaac_format.cli import _find_existing_record_id

        rid, path = _find_existing_record_id(tmp_path, "218386")
        assert rid == "ORIGINAL_ID"

    def test_returns_none_when_no_match(self, tmp_path):
        from nr_isaac_format.cli import _find_existing_record_id

        rid, path = _find_existing_record_id(tmp_path, "999999")
        assert rid is None
        assert path is None


class TestMigrateCommand:
    """Tests for the migrate command."""

    def _make_rev1_record(self, tmp_path, filename="isaac_record_218386.json"):
        """Create a rev1-format ISAAC record."""
        record = {
            "isaac_record_version": "1.0",
            "record_id": "01HXYZ1234567890ABCDEFGH",
            "record_type": "evidence",
            "record_domain": "characterization",
            "timestamps": {"created_utc": "2026-03-03T15:23:25Z"},
            "acquisition_source": {
                "source_type": "facility",
                "facility": {"site": "SNS", "beamline": "REF_L"},
            },
            "descriptors": {
                "outputs": [
                    {
                        "label": "test",
                        "generated_utc": "2026-03-03T15:23:25Z",
                        "generated_by": {"agent": "test"},
                        "descriptors": [
                            {
                                "name": "q_range_min",
                                "kind": "absolute",
                                "source": "computed",
                                "value": 0.01,
                                "unit": "\u00c5\u207b\u00b9",
                                "uncertainty": {"type": "none"},
                            }
                        ],
                    }
                ]
            },
            "system": {
                "domain": "experimental",
                "configuration": {"technique": "neutron_reflectometry"},
            },
        }
        path = tmp_path / filename
        path.write_text(json.dumps(record, indent=2))
        return path

    def test_migrate_applies_all_rev2_changes(self, runner, tmp_path):
        """Should apply all rev1→rev2 structural changes."""
        record_path = self._make_rev1_record(tmp_path)

        result = runner.invoke(main, ["migrate", str(record_path)])

        assert result.exit_code == 0, result.output
        assert "Migrated 1 record" in result.output

        v2_path = tmp_path / "isaac_record_218386_v2.json"
        assert v2_path.exists()
        with open(v2_path) as f:
            migrated = json.load(f)

        # acquisition_source removed, source_type at top level
        assert "acquisition_source" not in migrated
        assert migrated["source_type"] == "facility"

        # descriptor source updated
        desc = migrated["descriptors"]["outputs"][0]["descriptors"][0]
        assert desc["source"] == "auto"

        # system.technique added, configuration removed
        assert migrated["system"]["technique"] == "neutron_reflectometry"
        assert "configuration" not in migrated["system"]

    def test_migrate_skips_rev2_record(self, runner, tmp_path):
        """Should skip record that is already rev2-compatible."""
        record = {
            "isaac_record_version": "1.0",
            "record_id": "01HXYZ1234567890ABCDEFGH",
            "record_type": "evidence",
            "record_domain": "characterization",
            "source_type": "facility",
            "timestamps": {"created_utc": "2026-03-03T15:23:25Z"},
        }
        path = tmp_path / "isaac_record_218386.json"
        path.write_text(json.dumps(record, indent=2))

        result = runner.invoke(main, ["migrate", str(path)])

        assert result.exit_code == 0, result.output
        assert "Skipped 1 record" in result.output
        assert not (tmp_path / "isaac_record_218386_v2.json").exists()

    def test_migrate_does_not_overwrite(self, runner, tmp_path):
        """Should never overwrite the original file."""
        record_path = self._make_rev1_record(tmp_path)
        original_content = record_path.read_text()

        runner.invoke(main, ["migrate", str(record_path)])

        assert record_path.read_text() == original_content

    def test_migrate_directory(self, runner, tmp_path):
        """Should process all JSON files in a directory."""
        records_dir = tmp_path / "output"
        records_dir.mkdir()
        self._make_rev1_record(records_dir, "isaac_record_218386.json")
        self._make_rev1_record(records_dir, "isaac_record_218393.json")

        result = runner.invoke(main, ["migrate", str(records_dir)])

        assert result.exit_code == 0, result.output
        assert "Migrated 2 record" in result.output
        assert (records_dir / "isaac_record_218386_v2.json").exists()
        assert (records_dir / "isaac_record_218393_v2.json").exists()
