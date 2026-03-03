"""Tests for the push and health CLI commands."""

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
def record_file(tmp_path: Path) -> Path:
    """Write a minimal ISAAC record JSON file and return its path."""
    record = {
        "isaac_record_version": "1.0",
        "record_id": "01TESTRECORD00000000000000",
        "record_type": "evidence",
        "record_domain": "characterization",
        "timestamps": {"created_utc": "2025-01-01T00:00:00Z"},
        "acquisition_source": {"source_type": "facility"},
    }
    f = tmp_path / "isaac_record_test.json"
    f.write_text(json.dumps(record))
    return f


@pytest.fixture
def record_dir(tmp_path: Path) -> Path:
    """Create a directory with two record JSON files."""
    for i in range(2):
        record = {
            "isaac_record_version": "1.0",
            "record_id": f"01TESTRECORD0000000000000{i}",
            "record_type": "evidence",
            "record_domain": "characterization",
            "timestamps": {"created_utc": "2025-01-01T00:00:00Z"},
            "acquisition_source": {"source_type": "facility"},
        }
        (tmp_path / f"isaac_record_{i}.json").write_text(json.dumps(record))
    return tmp_path


# ---------------------------------------------------------------------------
# push command
# ---------------------------------------------------------------------------

class TestPushCommand:
    """Tests for ``nr-isaac-format push``."""

    @patch.dict("os.environ", {"ISAAC_URL": "https://api.test", "ISAAC_KEY": "tok123"})
    @patch("nr_isaac_format.client.IsaacClient")
    def test_push_single_file(self, mock_client_cls, runner, record_file):
        mock_client = MagicMock()
        mock_client.create.return_value = {"success": True, "record_id": "REC1"}
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = runner.invoke(main, ["push", str(record_file)])
        assert result.exit_code == 0, result.output
        assert "created" in result.output
        assert "REC1" in result.output
        mock_client.create.assert_called_once()

    @patch.dict("os.environ", {"ISAAC_URL": "https://api.test", "ISAAC_KEY": "tok123"})
    @patch("nr_isaac_format.client.IsaacClient")
    def test_push_directory(self, mock_client_cls, runner, record_dir):
        mock_client = MagicMock()
        mock_client.create.return_value = {"success": True, "record_id": "REC"}
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = runner.invoke(main, ["push", str(record_dir)])
        assert result.exit_code == 0, result.output
        assert mock_client.create.call_count == 2

    @patch.dict("os.environ", {"ISAAC_URL": "https://api.test", "ISAAC_KEY": "tok123"})
    @patch("nr_isaac_format.client.IsaacClient")
    def test_push_validate_only(self, mock_client_cls, runner, record_file):
        mock_client = MagicMock()
        mock_client.validate.return_value = {
            "valid": True,
            "schema_valid": True,
            "vocabulary_valid": True,
            "schema_errors": [],
            "vocabulary_errors": [],
            "errors": [],
        }
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = runner.invoke(main, ["push", str(record_file), "--validate-only"])
        assert result.exit_code == 0, result.output
        assert "valid" in result.output
        mock_client.validate.assert_called_once()
        mock_client.create.assert_not_called()

    @patch.dict("os.environ", {"ISAAC_URL": "https://api.test", "ISAAC_KEY": "tok123"})
    @patch("nr_isaac_format.client.IsaacClient")
    def test_push_validation_failure(self, mock_client_cls, runner, record_file):
        from nr_isaac_format.client import IsaacValidationError

        mock_client = MagicMock()
        mock_client.create.side_effect = IsaacValidationError(
            "Record validation failed",
            {
                "success": False,
                "schema_errors": ["missing field 'timestamps'"],
                "vocabulary_errors": [],
            },
        )
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = runner.invoke(main, ["push", str(record_file)])
        assert result.exit_code != 0
        assert "failed" in result.output

    @patch.dict("os.environ", {"ISAAC_URL": "https://api.test", "ISAAC_KEY": "tok123"})
    @patch("nr_isaac_format.client.IsaacClient")
    def test_push_auth_error_aborts(self, mock_client_cls, runner, record_file):
        from nr_isaac_format.client import IsaacAuthError

        mock_client = MagicMock()
        mock_client.create.side_effect = IsaacAuthError(401, "Unauthorized")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = runner.invoke(main, ["push", str(record_file)])
        assert result.exit_code != 0
        assert "Authentication error" in result.output

    @patch("nr_isaac_format.cli.load_dotenv")
    @patch.dict("os.environ", {}, clear=True)
    def test_push_missing_token(self, _mock_dotenv, runner, record_file):
        """Should fail if ISAAC_KEY is not set and --token not given."""
        result = runner.invoke(main, ["push", str(record_file)])
        assert result.exit_code != 0
        assert "ISAAC_URL" in result.output or "ISAAC_KEY" in result.output

    @patch("nr_isaac_format.cli.load_dotenv")
    @patch.dict("os.environ", {"ISAAC_URL": "https://api.test"}, clear=True)
    def test_push_missing_key_only(self, _mock_dotenv, runner, record_file):
        result = runner.invoke(main, ["push", str(record_file)])
        assert result.exit_code != 0
        assert "ISAAC_KEY" in result.output

    @patch.dict("os.environ", {"ISAAC_URL": "https://api.test", "ISAAC_KEY": "tok123"})
    def test_push_no_json_files(self, runner, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        result = runner.invoke(main, ["push", str(empty_dir)])
        assert result.exit_code != 0
        assert "No JSON files" in result.output

    @patch.dict("os.environ", {"ISAAC_URL": "https://api.test", "ISAAC_KEY": "tok123"})
    @patch("nr_isaac_format.client.IsaacClient")
    def test_push_with_cli_token_override(self, mock_client_cls, runner, record_file):
        mock_client = MagicMock()
        mock_client.create.return_value = {"success": True, "record_id": "REC1"}
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = runner.invoke(
            main, ["push", str(record_file), "--token", "override-tok"]
        )
        assert result.exit_code == 0, result.output
        # The client should have been created with the override token
        mock_client_cls.assert_called_once_with("https://api.test", "override-tok")


# ---------------------------------------------------------------------------
# health command
# ---------------------------------------------------------------------------

class TestHealthCommand:
    """Tests for ``nr-isaac-format health``."""

    @patch.dict("os.environ", {"ISAAC_URL": "https://api.test", "ISAAC_KEY": "tok123"})
    @patch("nr_isaac_format.client.IsaacClient")
    def test_healthy(self, mock_client_cls, runner):
        mock_client = MagicMock()
        mock_client.health.return_value = {"status": "healthy"}
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = runner.invoke(main, ["health"])
        assert result.exit_code == 0
        assert "healthy" in result.output

    @patch.dict("os.environ", {"ISAAC_URL": "https://api.test", "ISAAC_KEY": "tok123"})
    @patch("nr_isaac_format.client.IsaacClient")
    def test_api_error(self, mock_client_cls, runner):
        from nr_isaac_format.client import IsaacAPIError

        mock_client = MagicMock()
        mock_client.health.side_effect = IsaacAPIError(500, "Internal Server Error")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = runner.invoke(main, ["health"])
        assert result.exit_code != 0
        assert "API error" in result.output


# ---------------------------------------------------------------------------
# fetch-schema command
# ---------------------------------------------------------------------------

class TestFetchSchemaCommand:
    """Tests for ``nr-isaac-format fetch-schema``."""

    @patch.dict("os.environ", {"ISAAC_URL": "https://api.test", "ISAAC_KEY": "tok123"})
    @patch("nr_isaac_format.client.IsaacClient")
    def test_fetch_schema_first_revision(self, mock_client_cls, runner, tmp_path):
        """First fetch should create rev 1."""
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "ISAAC AI-Ready Scientific Record v1.0",
            "type": "object",
        }
        mock_client = MagicMock()
        mock_client.get_schema.return_value = schema
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()

        with patch("nr_isaac_format.cli.Path") as mock_path_cls:
            # Make Path(__file__).parent / "schema" point to our tmp dir
            mock_path_cls.return_value.parent.__truediv__ = MagicMock(return_value=schema_dir)
            # But keep Path(p) working for _collect_json_files etc.
            # We patch at a lower level instead:
            pass

        # Use monkeypatch approach instead — patch the schema_dir directly
        with patch("nr_isaac_format.cli.Path.__new__") as _:
            pass  # too complex; let's use a simpler approach

        # Simpler: patch __file__ location so schema_dir resolves to tmp
        import nr_isaac_format.cli as cli_module

        original_file = cli_module.__file__
        try:
            # Point __file__ so Path(__file__).parent / "schema" == tmp schema_dir
            cli_module.__file__ = str(tmp_path / "cli.py")
            result = runner.invoke(main, ["fetch-schema"])
        finally:
            cli_module.__file__ = original_file

        assert result.exit_code == 0, result.output
        assert "rev 1" in result.output

        saved = schema_dir / "isaac_record_v1-ornl-rev1.json"
        assert saved.exists()
        content = json.loads(saved.read_text())
        assert content["title"] == "ISAAC AI-Ready Scientific Record v1.0"

    @patch.dict("os.environ", {"ISAAC_URL": "https://api.test", "ISAAC_KEY": "tok123"})
    @patch("nr_isaac_format.client.IsaacClient")
    def test_fetch_schema_increments_revision(self, mock_client_cls, runner, tmp_path):
        """Should increment revision when content differs."""
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "ISAAC AI-Ready Scientific Record v1.0",
            "type": "object",
            "new_field": True,
        }
        mock_client = MagicMock()
        mock_client.get_schema.return_value = schema
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()
        # Pre-create rev 1 with different content
        (schema_dir / "isaac_record_v1-ornl-rev1.json").write_text(
            json.dumps({"title": "old"}, indent=2) + "\n"
        )

        import nr_isaac_format.cli as cli_module

        original_file = cli_module.__file__
        try:
            cli_module.__file__ = str(tmp_path / "cli.py")
            result = runner.invoke(main, ["fetch-schema"])
        finally:
            cli_module.__file__ = original_file

        assert result.exit_code == 0, result.output
        assert "rev 2" in result.output
        assert (schema_dir / "isaac_record_v1-ornl-rev2.json").exists()

    @patch.dict("os.environ", {"ISAAC_URL": "https://api.test", "ISAAC_KEY": "tok123"})
    @patch("nr_isaac_format.client.IsaacClient")
    def test_fetch_schema_skips_if_unchanged(self, mock_client_cls, runner, tmp_path):
        """Should not create a new file if content is identical to latest rev."""
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "ISAAC AI-Ready Scientific Record v1.0",
            "type": "object",
        }
        mock_client = MagicMock()
        mock_client.get_schema.return_value = schema
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()
        # Pre-create rev 1 with identical content
        (schema_dir / "isaac_record_v1-ornl-rev1.json").write_text(
            json.dumps(schema, indent=2) + "\n"
        )

        import nr_isaac_format.cli as cli_module

        original_file = cli_module.__file__
        try:
            cli_module.__file__ = str(tmp_path / "cli.py")
            result = runner.invoke(main, ["fetch-schema"])
        finally:
            cli_module.__file__ = original_file

        assert result.exit_code == 0, result.output
        assert "unchanged" in result.output.lower()
        # rev 2 should NOT exist
        assert not (schema_dir / "isaac_record_v1-ornl-rev2.json").exists()

    @patch.dict("os.environ", {"ISAAC_URL": "https://api.test", "ISAAC_KEY": "tok123"})
    @patch("nr_isaac_format.client.IsaacClient")
    def test_fetch_schema_with_explicit_version_field(self, mock_client_cls, runner, tmp_path):
        """Schema with a top-level 'version' field should use that."""
        schema = {
            "version": "2.0",
            "title": "Something",
            "type": "object",
        }
        mock_client = MagicMock()
        mock_client.get_schema.return_value = schema
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        schema_dir = tmp_path / "schema"
        schema_dir.mkdir()

        import nr_isaac_format.cli as cli_module

        original_file = cli_module.__file__
        try:
            cli_module.__file__ = str(tmp_path / "cli.py")
            result = runner.invoke(main, ["fetch-schema"])
        finally:
            cli_module.__file__ = original_file

        assert result.exit_code == 0, result.output
        assert (schema_dir / "isaac_record_v2-ornl-rev1.json").exists()
