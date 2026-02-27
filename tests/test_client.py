"""Tests for the ISAAC Portal API client."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from nr_isaac_format.client import (
    IsaacAPIError,
    IsaacAuthError,
    IsaacClient,
    IsaacValidationError,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(
    status_code: int = 200,
    json_body: dict[str, Any] | list[Any] | None = None,
    text: str = "",
) -> httpx.Response:
    """Build a minimal httpx.Response for testing."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text or (str(json_body) if json_body else "")
    resp.json.return_value = json_body if json_body is not None else {}
    return resp


# ---------------------------------------------------------------------------
# IsaacClient.health
# ---------------------------------------------------------------------------

class TestHealth:
    def test_healthy(self):
        client = IsaacClient("https://example.com/api", "tok")
        client._client = MagicMock()
        client._client.get.return_value = _mock_response(200, {"status": "healthy"})

        result = client.health()
        assert result == {"status": "healthy"}
        client._client.get.assert_called_once_with("https://example.com/api/health")

    def test_server_error(self):
        client = IsaacClient("https://example.com/api", "tok")
        client._client = MagicMock()
        client._client.get.return_value = _mock_response(500, {"detail": "boom"})

        with pytest.raises(IsaacAPIError) as exc_info:
            client.health()
        assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# IsaacClient.validate
# ---------------------------------------------------------------------------

class TestValidate:
    def test_valid_record(self):
        client = IsaacClient("https://example.com/api", "tok")
        client._client = MagicMock()
        body = {
            "valid": True,
            "schema_valid": True,
            "vocabulary_valid": True,
            "schema_errors": [],
            "vocabulary_errors": [],
            "errors": [],
        }
        client._client.post.return_value = _mock_response(200, body)

        result = client.validate({"isaac_record_version": "1.0"})
        assert result["valid"] is True

    def test_invalid_record_returns_body(self):
        """400 on validate should NOT raise — it returns the validation body."""
        client = IsaacClient("https://example.com/api", "tok")
        client._client = MagicMock()
        body = {
            "valid": False,
            "schema_valid": True,
            "vocabulary_valid": False,
            "schema_errors": [],
            "vocabulary_errors": [{"path": "x", "message": "bad vocab"}],
            "errors": [],
        }
        client._client.post.return_value = _mock_response(400, body)

        result = client.validate({"bad": "record"})
        assert result["valid"] is False
        assert len(result["vocabulary_errors"]) == 1

    def test_auth_error(self):
        client = IsaacClient("https://example.com/api", "tok")
        client._client = MagicMock()
        client._client.post.return_value = _mock_response(401, {"detail": "Unauthorized"})

        with pytest.raises(IsaacAuthError):
            client.validate({})


# ---------------------------------------------------------------------------
# IsaacClient.create
# ---------------------------------------------------------------------------

class TestCreate:
    def test_success(self):
        client = IsaacClient("https://example.com/api", "tok")
        client._client = MagicMock()
        body = {"success": True, "record_id": "01JFH3Q8Z1"}
        client._client.post.return_value = _mock_response(201, body)

        result = client.create({"isaac_record_version": "1.0"})
        assert result["success"] is True
        assert result["record_id"] == "01JFH3Q8Z1"

    def test_validation_failure_raises(self):
        client = IsaacClient("https://example.com/api", "tok")
        client._client = MagicMock()
        body = {
            "success": False,
            "reason": "validation_failed",
            "schema_errors": ["field required"],
            "vocabulary_errors": [],
            "errors": ["field required"],
        }
        client._client.post.return_value = _mock_response(400, body)

        with pytest.raises(IsaacValidationError) as exc_info:
            client.create({"bad": "data"})
        assert exc_info.value.schema_errors == ["field required"]

    def test_auth_failure_raises(self):
        client = IsaacClient("https://example.com/api", "tok")
        client._client = MagicMock()
        client._client.post.return_value = _mock_response(403, {"detail": "Forbidden"})

        with pytest.raises(IsaacAuthError):
            client.create({})


# ---------------------------------------------------------------------------
# IsaacClient.list_records / get_record
# ---------------------------------------------------------------------------

class TestListAndGet:
    def test_list_records(self):
        client = IsaacClient("https://example.com/api", "tok")
        client._client = MagicMock()
        body = [{"record_id": "A"}, {"record_id": "B"}]
        client._client.get.return_value = _mock_response(200, body)

        result = client.list_records(limit=10, offset=0)
        assert len(result) == 2

    def test_get_record(self):
        client = IsaacClient("https://example.com/api", "tok")
        client._client = MagicMock()
        body = {"isaac_record_version": "1.0", "record_id": "ABC"}
        client._client.get.return_value = _mock_response(200, body)

        result = client.get_record("ABC")
        assert result["record_id"] == "ABC"
        client._client.get.assert_called_once_with("https://example.com/api/records/ABC")


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------

class TestContextManager:
    def test_context_manager_closes(self):
        client = IsaacClient("https://example.com/api", "tok")
        client._client = MagicMock()

        with client as c:
            assert c is client
        client._client.close.assert_called_once()


# ---------------------------------------------------------------------------
# URL trailing-slash handling
# ---------------------------------------------------------------------------

class TestURLNormalization:
    def test_strips_trailing_slash(self):
        client = IsaacClient("https://example.com/api/", "tok")
        assert client.base_url == "https://example.com/api"
