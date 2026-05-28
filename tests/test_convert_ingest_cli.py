"""Tests for ``nr-isaac-format convert-ingest``.

The command is schema-agnostic: it takes an ingest directory plus explicit
options and emits a neutral ``ndip-tool-result/1`` manifest via ``--result-out``.
Building a real ingest dir is expensive, so these tests stub
``_load_assembly_from_ingest`` and ``IsaacWriter`` and focus on the CLI surface
and the manifest output.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from nr_isaac_format.cli import main


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def ingest_dir(tmp_path):
    d = tmp_path / "assembled"
    d.mkdir()
    (d / "reflectivity").mkdir()
    (d / "reflectivity" / "x.parquet").write_bytes(b"")
    return d


def _stub_load_and_writer(ingest_dir):
    fake_result = MagicMock()
    fake_result.reflectivity = {"run_number": 218386, "run_title": "Test run", "q": [0.01, 0.02]}
    fake_result.sample = {"id": "sample-uuid", "description": "Cu/Ti"}
    fake_result.environment = None
    fake_result.reduced_file = None

    fake_writer = MagicMock()
    fake_writer.to_isaac.return_value = {"id": "isaac-record", "sample": "Cu/Ti"}
    return fake_result, fake_writer


def test_no_args_errors(runner):
    result = runner.invoke(main, ["convert-ingest"])
    assert result.exit_code != 0


def test_has_no_state_options(runner):
    result = runner.invoke(main, ["convert-ingest", "--help"])
    assert "--state-in" not in result.output
    assert "--state-out" not in result.output
    assert "--result-out" in result.output


def test_result_out_records_success(runner, tmp_path, ingest_dir):
    result_out = tmp_path / "result.json"
    nexus = "/archive/REF_L_218386.nxs.h5"
    fake_result, fake_writer = _stub_load_and_writer(ingest_dir)
    with patch("nr_isaac_format.cli._load_assembly_from_ingest", return_value=fake_result), \
         patch("nr_isaac_format.cli.IsaacWriter", return_value=fake_writer):
        result = runner.invoke(
            main,
            [
                "convert-ingest",
                str(ingest_dir),
                "--raw", nexus,
                "--result-out", str(result_out),
            ],
        )
    assert result.exit_code == 0, result.output

    m = json.loads(result_out.read_text())
    assert m["tool"] == "nr-isaac-format"
    assert m["schema"] == "ndip-tool-result/1"
    assert m["status"] == "ok"
    assert m["artifacts"]["isaac_record"].endswith("isaac_record_218386.json")
    assert m["info"]["isaac_status"] == "converted"
    assert m["params"]["ingest_dir"] == str(ingest_dir.resolve())
    assert m["params"]["nexus_input"] == nexus


def test_result_out_records_failure_on_load_error(runner, tmp_path, ingest_dir):
    """Errors in _load_assembly_from_ingest produce a failed manifest."""
    result_out = tmp_path / "result.json"
    with patch(
        "nr_isaac_format.cli._load_assembly_from_ingest",
        side_effect=RuntimeError("boom"),
    ):
        result = runner.invoke(
            main,
            [
                "convert-ingest",
                str(ingest_dir),
                "--result-out", str(result_out),
            ],
        )
    assert result.exit_code != 0
    m = json.loads(result_out.read_text())
    assert m["status"] == "failed"
    assert m["messages"][0]["level"] == "error"


def test_default_output_lands_in_ingest_dir(runner, tmp_path, ingest_dir):
    """With no --output, the isaac record is written into the ingest dir."""
    fake_result, fake_writer = _stub_load_and_writer(ingest_dir)
    with patch("nr_isaac_format.cli._load_assembly_from_ingest", return_value=fake_result), \
         patch("nr_isaac_format.cli.IsaacWriter", return_value=fake_writer):
        result = runner.invoke(main, ["convert-ingest", str(ingest_dir)])
    assert result.exit_code == 0, result.output
    assert (ingest_dir / "isaac_record_218386.json").is_file()
