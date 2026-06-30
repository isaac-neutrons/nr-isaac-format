"""Tests for ``nr-isaac-format convert-ingest``.

The command is schema-agnostic: it takes an ingest directory plus explicit
options and emits a neutral ``ndip-tool-result/1`` manifest via ``--result-out``.
Building a real ingest dir is expensive, so these tests stub
``_load_assembly_from_ingest`` and ``IsaacWriter`` and focus on the CLI surface
and the manifest output.
"""

from __future__ import annotations

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
    with patch("nr_isaac_format.cli._load_states_from_ingest", return_value=[fake_result]), \
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
        "nr_isaac_format.cli._load_states_from_ingest",
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
    with patch("nr_isaac_format.cli._load_states_from_ingest", return_value=[fake_result]), \
         patch("nr_isaac_format.cli.IsaacWriter", return_value=fake_writer):
        result = runner.invoke(main, ["convert-ingest", str(ingest_dir)])
    assert result.exit_code == 0, result.output
    assert (ingest_dir / "isaac_record_218386.json").is_file()


def _write_json_ingest(tmp_path, runs, *, sample_id="S", sample_ids=None, env_ids=None):
    """Build a real per-run JSON ingest dir (one reflectivity.json per run).

    ``sample_ids`` (dict run→sample_id) overrides the single shared ``sample_id``
    to model distinct physical samples across states; one sample record is
    written per distinct id (the ``sample/<id>.json`` multi-state layout).
    """
    ingest = tmp_path / "assembled"
    jdir = ingest / "json"
    env_ids = env_ids or {r: "E" for r in runs}
    sids = sample_ids or {r: sample_id for r in runs}
    for i, run in enumerate(runs):
        rd = jdir / run
        rd.mkdir(parents=True)
        (rd / "reflectivity.json").write_text(
            json.dumps(
                {
                    "id": f"refl-{run}",
                    "run_number": run,
                    "facility": "SNS",
                    "instrument_name": "REF_L",
                    "run_title": f"state-{run}",
                    "q": [0.01 * (i + 1), 0.02 * (i + 1), 0.03 * (i + 1)],
                    "r": [0.9, 0.8, 0.7],
                    "dr": [0.01, 0.01, 0.01],
                    "dq": [0.001, 0.001, 0.001],
                    "sample_id": sids[run],
                    "environment_id": env_ids[run],
                }
            )
        )
    distinct_sids = sorted(set(sids.values()))
    if len(distinct_sids) <= 1:
        only = distinct_sids[0] if distinct_sids else sample_id
        (jdir / "sample.json").write_text(
            json.dumps({"id": only, "description": "Cu", "main_composition": "Cu", "formula": "Cu"})
        )
    else:
        sdir = jdir / "sample"
        sdir.mkdir()
        for sid in distinct_sids:
            (sdir / f"{sid}.json").write_text(
                json.dumps(
                    {"id": sid, "description": f"sample {sid}", "main_composition": "Cu", "formula": "Cu"}
                )
            )
    # One environment record per distinct env id (multi-state layout).
    distinct_envs = sorted(set(env_ids.values()))
    if len(distinct_envs) <= 1:
        (jdir / "environment.json").write_text(
            json.dumps({"id": distinct_envs[0] if distinct_envs else "E", "description": "ambient"})
        )
    else:
        edir = jdir / "environment"
        edir.mkdir()
        for eid in distinct_envs:
            (edir / f"{eid}.json").write_text(json.dumps({"id": eid, "description": f"cond {eid}"}))
    return ingest


def test_multi_run_ingest_emits_multiple_series(runner, tmp_path):
    """A per-run ingest dir (one state, 3 angles) → one record with 3 series."""
    ingest = _write_json_ingest(tmp_path, ["230536", "230537", "230538"])
    out = tmp_path / "rec.json"

    result = runner.invoke(main, ["convert-ingest", str(ingest), "-o", str(out)])
    assert result.exit_code == 0, result.output

    rec = json.loads(out.read_text())
    series = rec["measurement"]["series"]
    assert len(series) == 3
    assert {s["series_id"] for s in series} == {"run_230536", "run_230537", "run_230538"}
    # aggregate descriptors span all three angles
    descs = {
        d["name"]: d["value"]
        for o in rec["descriptors"]["outputs"]
        for d in o["descriptors"]
    }
    assert descs["total_points"] == 9  # 3 points × 3 runs
    assert "3 run(s) → 3 series" in result.output


def test_multi_state_splits_into_per_state_records(runner, tmp_path):
    """Runs spanning several states → one record per (sample_id, environment_id)."""
    ingest = _write_json_ingest(
        tmp_path,
        ["1", "2", "3", "4"],
        env_ids={"1": "E_D2O", "2": "E_D2O", "3": "E_H2O", "4": "E_H2O"},
    )
    out = tmp_path / "out"
    result = runner.invoke(main, ["convert-ingest", str(ingest), "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert "States: 2" in result.output

    # First-seen run of each state names its record; each state keeps its 2 angles.
    rec_d2o = json.loads((out / "isaac_record_1.json").read_text())
    rec_h2o = json.loads((out / "isaac_record_3.json").read_text())
    assert {s["series_id"] for s in rec_d2o["measurement"]["series"]} == {"run_1", "run_2"}
    assert {s["series_id"] for s in rec_h2o["measurement"]["series"]} == {"run_3", "run_4"}


def test_multi_state_same_sample_links_records(runner, tmp_path):
    """Two states of ONE physical sample (shared sample_id) → reciprocal
    same_sample_as links between their records, and a shared sample.sample_id."""
    ingest = _write_json_ingest(
        tmp_path,
        ["1", "2", "3", "4"],
        sample_id="S",  # all states share the one physical sample
        env_ids={"1": "E_D2O", "2": "E_D2O", "3": "E_H2O", "4": "E_H2O"},
    )
    out = tmp_path / "out"
    result = runner.invoke(main, ["convert-ingest", str(ingest), "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert "same_sample_as" in result.output

    rec_d2o = json.loads((out / "isaac_record_1.json").read_text())
    rec_h2o = json.loads((out / "isaac_record_3.json").read_text())
    # Both records carry the same physical-sample identity.
    assert rec_d2o["sample"]["sample_id"] == "S"
    assert rec_h2o["sample"]["sample_id"] == "S"
    # Each links to the other (reciprocal), with the same_sample_id basis.
    d2o_links = rec_d2o["links"]
    h2o_links = rec_h2o["links"]
    assert len(d2o_links) == 1 and len(h2o_links) == 1
    assert d2o_links[0]["rel"] == "same_sample_as"
    assert d2o_links[0]["basis"] == "same_sample_id"
    assert d2o_links[0]["target"] == rec_h2o["record_id"]
    assert h2o_links[0]["target"] == rec_d2o["record_id"]


def test_distinct_sample_states_are_not_linked(runner, tmp_path):
    """distinct_sample co-refinement (a sample per state) → distinct
    sample.sample_id per record and NO same_sample_as links."""
    ingest = _write_json_ingest(
        tmp_path,
        ["1", "2", "3", "4"],
        sample_ids={"1": "S_A", "2": "S_A", "3": "S_B", "4": "S_B"},
        env_ids={"1": "E_D2O", "2": "E_D2O", "3": "E_H2O", "4": "E_H2O"},
    )
    out = tmp_path / "out"
    result = runner.invoke(main, ["convert-ingest", str(ingest), "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert "same_sample_as" not in result.output

    rec_a = json.loads((out / "isaac_record_1.json").read_text())
    rec_b = json.loads((out / "isaac_record_3.json").read_text())
    assert rec_a["sample"]["sample_id"] == "S_A"
    assert rec_b["sample"]["sample_id"] == "S_B"
    assert not rec_a.get("links")
    assert not rec_b.get("links")


def test_convert_ingest_records_validate_against_schema(runner, tmp_path):
    """The emitted multi-state records (with sample_id + links) are schema-valid."""
    import jsonschema

    from nr_isaac_format.cli import _find_latest_schema

    schema_dir = Path(__file__).resolve().parents[1] / "src" / "nr_isaac_format" / "schema"
    schema = json.loads(_find_latest_schema(schema_dir).read_text())

    ingest = _write_json_ingest(
        tmp_path,
        ["1", "2", "3", "4"],
        sample_id="S",
        env_ids={"1": "E_D2O", "2": "E_D2O", "3": "E_H2O", "4": "E_H2O"},
    )
    out = tmp_path / "out"
    result = runner.invoke(main, ["convert-ingest", str(ingest), "-o", str(out)])
    assert result.exit_code == 0, result.output

    for rec_file in sorted(out.glob("isaac_record_*.json")):
        jsonschema.validate(json.loads(rec_file.read_text()), schema)


def test_multi_state_explicit_json_file_errors(runner, tmp_path):
    """A .json -o with multiple states is rejected (can't write N records to one file)."""
    ingest = _write_json_ingest(tmp_path, ["1", "2"], env_ids={"1": "E_a", "2": "E_b"})
    result = runner.invoke(main, ["convert-ingest", str(ingest), "-o", str(tmp_path / "x.json")])
    assert result.exit_code != 0
    assert "states found" in result.output
