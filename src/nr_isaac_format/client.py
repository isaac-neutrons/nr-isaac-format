"""
ISAAC Portal API client.

Thin HTTP client for the ISAAC Portal REST API sidecar.
Handles authentication, record submission, validation, and retrieval.
"""

from __future__ import annotations

from typing import Any

import httpx


class IsaacAPIError(Exception):
    """Raised when the ISAAC API returns an unexpected error."""

    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"HTTP {status_code}: {detail}")


class IsaacAuthError(IsaacAPIError):
    """Raised on 401/403 authentication or authorization failures."""

    pass


class IsaacValidationError(IsaacAPIError):
    """Raised when record validation fails (400)."""

    def __init__(self, detail: str, body: dict[str, Any]):
        self.body = body
        self.schema_errors: list[Any] = body.get("schema_errors", [])
        self.vocabulary_errors: list[Any] = body.get("vocabulary_errors", [])
        super().__init__(status_code=400, detail=detail)


class IsaacClient:
    """Client for the ISAAC Portal REST API.

    Args:
        base_url: API base URL (e.g. ``https://isaac.slac.stanford.edu/portal/api``).
        token: Authentik Bearer token for authentication.
        timeout: Request timeout in seconds.
    """

    def __init__(self, base_url: str, token: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=timeout,
        )

    # -- lifecycle ------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> IsaacClient:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # -- endpoints ------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        """Check API health.

        Returns:
            ``{"status": "healthy"}`` on success.

        Raises:
            IsaacAPIError: If the health endpoint returns a non-200 status.
        """
        resp = self._client.get(f"{self.base_url}/health")
        self._check_response(resp)
        return resp.json()

    def validate(self, record: dict[str, Any]) -> dict[str, Any]:
        """Validate a record without persisting it (dry-run).

        Args:
            record: Full ISAAC record dictionary.

        Returns:
            Validation result with ``valid``, ``schema_valid``,
            ``vocabulary_valid``, and error lists.
        """
        resp = self._client.post(f"{self.base_url}/validate", json=record)
        self._check_response(resp, allow_400=True)
        return resp.json()

    def create(self, record: dict[str, Any]) -> dict[str, Any]:
        """Create (validate + persist) a record.

        Args:
            record: Full ISAAC record dictionary.

        Returns:
            ``{"success": True, "record_id": "..."}`` on success.

        Raises:
            IsaacValidationError: If the record fails validation (400).
            IsaacAuthError: On authentication/authorization failure.
        """
        resp = self._client.post(f"{self.base_url}/records", json=record)
        if resp.status_code == 400:
            body = resp.json()
            raise IsaacValidationError("Record validation failed", body)
        self._check_response(resp)
        return resp.json()

    def list_records(
        self, *, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        """List record summaries.

        Args:
            limit: Maximum records to return.
            offset: Pagination offset.

        Returns:
            List of record summary dicts.
        """
        resp = self._client.get(
            f"{self.base_url}/records",
            params={"limit": limit, "offset": offset},
        )
        self._check_response(resp)
        return resp.json()

    def get_record(self, record_id: str) -> dict[str, Any]:
        """Retrieve a single record by ID.

        Args:
            record_id: ULID of the record.

        Returns:
            Full record JSON.
        """
        resp = self._client.get(f"{self.base_url}/records/{record_id}")
        self._check_response(resp)
        return resp.json()

    def get_schema(self) -> dict[str, Any]:
        """Retrieve the latest ISAAC record schema.

        Returns:
            The JSON Schema dictionary.

        Raises:
            IsaacAPIError: If the schema endpoint returns a non-200 status.
        """
        resp = self._client.get(f"{self.base_url}/schema")
        self._check_response(resp)
        return resp.json()

    # -- helpers --------------------------------------------------------------

    def _check_response(
        self, resp: httpx.Response, *, allow_400: bool = False
    ) -> None:
        """Raise typed exceptions for non-success status codes."""
        if resp.status_code in (401, 403):
            detail = self._extract_detail(resp)
            raise IsaacAuthError(resp.status_code, detail)
        if resp.status_code == 400:
            if not allow_400:
                detail = self._extract_detail(resp)
                raise IsaacAPIError(resp.status_code, detail)
            return
        if resp.status_code >= 400:
            detail = self._extract_detail(resp)
            raise IsaacAPIError(resp.status_code, detail)

    @staticmethod
    def _extract_detail(resp: httpx.Response) -> str:
        """Best-effort extraction of error detail from a response."""
        try:
            body = resp.json()
            if isinstance(body, dict):
                return body.get("detail", body.get("message", resp.text))
            return resp.text
        except Exception:
            return resp.text
