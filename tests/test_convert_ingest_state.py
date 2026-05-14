"""Tests for ``nr-isaac-format convert-ingest``'s --state-in / --state-out flags.

The convert-ingest command needs an ingest_dir containing parquet output
from ``data-assembler ingest``. Building that fixture is expensive, so
these tests stub ``_load_assembly_from_ingest`` and ``IsaacWriter.to_isaac``
and focus on the state plumbing.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from assembler.state import empty_state, load_state, save_state, update_stage
from nr_isaac_format.cli import main


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def ingest_dir(tmp_path):
    d = tmp_path / "assembled"
    d.mkdir()
    # Touch a few parquet placeholders so the existence check inside the
    # CLI's `--exists` validator passes; the actual content is stubbed.
    (d / "reflectivity").mkdir()
    (d / "reflectivity" / "x.parquet").write_bytes(b"")
    return d


def _stub_load_and_writer(ingest_dir):
    """Build the mock stack for _load_assembly_from_ingest + IsaacWriter."""
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


def test_state_in_supplies_ingest_dir(runner, tmp_path, ingest_dir):
    wstate = empty_state()
    wstate["paths"]["output_directory"] = str(tmp_path)
    # Hint via metadata.ingest_dir (most direct):
    update_stage(wstate, "assembly", metadata={"ingest_dir": str(ingest_dir)})
    state_path = tmp_path / "state.json"
    save_state(wstate, str(state_path))

    fake_result, fake_writer = _stub_load_and_writer(ingest_dir)
    with patch("nr_isaac_format.cli._load_assembly_from_ingest", return_value=fake_result), \
         patch("nr_isaac_format.cli.IsaacWriter", return_value=fake_writer):
        result = runner.invoke(main, ["convert-ingest", "--state-in", str(state_path)])
    assert result.exit_code == 0, result.output
    # The isaac_record file lands in the ingest_dir by default
    assert (ingest_dir / "isaac_record_218386.json").is_file()


def test_state_in_paths_output_dir_fallback(runner, tmp_path):
    """If only paths.output_directory is set, ingest_dir = <od>/assembled."""
    asm = tmp_path / "assembled"
    asm.mkdir()
    (asm / "reflectivity").mkdir()
    (asm / "reflectivity" / "x.parquet").write_bytes(b"")

    wstate = empty_state()
    wstate["paths"]["output_directory"] = str(tmp_path)
    state_path = tmp_path / "state.json"
    save_state(wstate, str(state_path))

    fake_result, fake_writer = _stub_load_and_writer(asm)
    with patch("nr_isaac_format.cli._load_assembly_from_ingest", return_value=fake_result), \
         patch("nr_isaac_format.cli.IsaacWriter", return_value=fake_writer):
        result = runner.invoke(main, ["convert-ingest", "--state-in", str(state_path)])
    assert result.exit_code == 0, result.output


def test_state_out_records_success(runner, tmp_path, ingest_dir):
    state_out = tmp_path / "out.json"
    fake_result, fake_writer = _stub_load_and_writer(ingest_dir)
    with patch("nr_isaac_format.cli._load_assembly_from_ingest", return_value=fake_result), \
         patch("nr_isaac_format.cli.IsaacWriter", return_value=fake_writer):
        result = runner.invoke(
            main,
            [
                "convert-ingest",
                str(ingest_dir),
                "--state-out", str(state_out),
            ],
        )
    assert result.exit_code == 0, result.output

    s = load_state(str(state_out))
    assert s["schema_version"] == "1"
    assert s["assembly"]["success"] is True
    assert s["assembly"]["isaac_record"].endswith("isaac_record_218386.json")
    assert s["assembly"]["metadata"]["isaac_status"] == "converted"


def test_state_out_records_failure_on_load_error(runner, tmp_path, ingest_dir):
    """Errors in _load_assembly_from_ingest are recorded in state-out."""
    state_out = tmp_path / "out.json"
    with patch(
        "nr_isaac_format.cli._load_assembly_from_ingest",
        side_effect=RuntimeError("boom"),
    ):
        result = runner.invoke(
            main,
            [
                "convert-ingest",
                str(ingest_dir),
                "--state-out", str(state_out),
            ],
        )
    assert result.exit_code != 0
    s = load_state(str(state_out))
    assert s["assembly"]["success"] is False
    assert s["errors"][0]["stage"] == "assembly"


def test_cli_ingest_dir_overrides_state_in(runner, tmp_path, ingest_dir):
    """An explicit INGEST_DIR positional wins over state-in."""
    other = tmp_path / "other"
    other.mkdir()  # exists but not a real ingest dir

    wstate = empty_state()
    update_stage(wstate, "assembly", metadata={"ingest_dir": str(other)})
    state_path = tmp_path / "state.json"
    save_state(wstate, str(state_path))

    fake_result, fake_writer = _stub_load_and_writer(ingest_dir)
    with patch("nr_isaac_format.cli._load_assembly_from_ingest", return_value=fake_result), \
         patch("nr_isaac_format.cli.IsaacWriter", return_value=fake_writer):
        result = runner.invoke(
            main,
            ["convert-ingest", str(ingest_dir), "--state-in", str(state_path)],
        )
    assert result.exit_code == 0, result.output
    # Output landed in ingest_dir (CLI value), not in "other" (state value).
    assert (ingest_dir / "isaac_record_218386.json").is_file()
    assert not (other / "isaac_record_218386.json").exists()
