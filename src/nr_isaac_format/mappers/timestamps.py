"""
Timestamps block mapper for ISAAC records.

Maps temporal data from the data-assembler reflectivity record
to the ISAAC timestamps block.
"""

from datetime import datetime, timezone
from typing import Any, Optional

from .base import Mapper, MapperContext


class TimestampsMapper(Mapper):
    """
    Maps timestamps from data-assembler to ISAAC timestamps block.

    Source fields:
    - reflectivity.created_at -> created_utc
    - reflectivity.run_start -> acquired_start_utc, acquired_end_utc

    ISAAC Schema:
    ```json
    "timestamps": {
        "created_utc": "2025-01-15T12:00:00Z",  // required
        "acquired_start_utc": "2025-01-15T10:30:00Z",
        "acquired_end_utc": "2025-01-15T10:45:00Z"
    }
    ```
    """

    @property
    def block_name(self) -> str:
        return "timestamps"

    def is_required(self) -> bool:
        return True

    def map(self, context: MapperContext) -> Optional[dict[str, Any]]:
        """
        Map timestamps from reflectivity record.

        Falls back to context.created_utc if source timestamps unavailable.
        """
        result: dict[str, Any] = {}

        # created_utc is required - use context timestamp as baseline
        created_utc = context.created_utc

        # Try to get created_at from reflectivity record
        if context.reflectivity:
            refl_created = context.reflectivity.get("created_at")
            if refl_created:
                created_utc = self._normalize_datetime(refl_created)

        result["created_utc"] = self._format_iso(created_utc)

        # acquired_start_utc from run_start
        if context.reflectivity:
            run_start = context.reflectivity.get("run_start")
            if run_start:
                acquired_start = self._normalize_datetime(run_start)
                result["acquired_start_utc"] = self._format_iso(acquired_start)

                # acquired_end_utc - we don't have duration info, so omit
                # rather than duplicate start time
            else:
                context.add_warning("run_start not found, acquired timestamps omitted")

        return result

    def _normalize_datetime(self, value: Any) -> datetime:
        """Convert various datetime representations to datetime object."""
        if isinstance(value, datetime):
            # Ensure timezone-aware
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value

        if isinstance(value, str):
            # Parse ISO format string
            try:
                # Handle various ISO formats
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
                return dt
            except ValueError:
                pass

        # Fallback to current time
        return datetime.now(timezone.utc)

    def _format_iso(self, dt: datetime) -> str:
        """Format datetime as ISO 8601 string with Z suffix."""
        # Ensure UTC
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)

        # Format with Z suffix as per ISAAC convention
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    def validate(self, block: dict[str, Any], context: MapperContext) -> bool:
        """Validate timestamps block has required created_utc."""
        if "created_utc" not in block:
            context.add_error("timestamps.created_utc is required")
            return False
        return True
