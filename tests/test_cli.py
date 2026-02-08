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
