"""Guard the shared ``ndip-tool-result/1`` wire contract.

``result_manifest.py`` is vendored byte-identically across analyzer/nr-analyzer,
data-assembler, and nr-isaac-format. We pin the *wire contract* here rather than
asserting byte-identity against the installed ``assembler`` copy: that copy is
whatever data-assembler git ref is pinned, so byte-equality depends on deploy
ordering (it only holds once data-assembler ships the same canonical body and
this repo's pin moves to that commit). The contract test is what guarantees
cross-tool compatibility regardless of that ordering.
"""

from nr_isaac_format import result_manifest as rm


def test_schema_constant():
    assert rm.SCHEMA == "ndip-tool-result/1"


def test_valid_status_vocabulary():
    assert rm.VALID_STATUS == {"ok", "failed", "skipped", "dry-run", "needs-reprocessing"}


def test_build_manifest_shape_and_none_dropping():
    m = rm.build_manifest(
        "nr-isaac-format",
        "ok",
        params={"ingest_dir": "/in", "raw": None},
        artifacts={"isaac_record": "rec.json", "missing": None},
        info={"isaac_status": "converted"},
        exit_code=0,
    )
    assert set(m) >= {
        "tool", "tool_version", "schema", "status", "exit_code",
        "params", "artifacts", "info",
    }
    assert m["tool"] == "nr-isaac-format" and m["schema"] == "ndip-tool-result/1"
    assert isinstance(m["tool_version"], str)
    assert m["params"] == {"ingest_dir": "/in"}
    assert m["artifacts"] == {"isaac_record": "rec.json"}
    assert "messages" not in m
