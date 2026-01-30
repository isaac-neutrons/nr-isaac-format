"""
ULID generation utility for ISAAC record IDs.

ISAAC AI-Ready Record v1.0 requires record_id to be a ULID:
- 26 characters
- Uppercase alphanumeric (0-9, A-Z)
- Lexicographically sortable by creation time

Example:
    01JFH3Q8Z1Q9F0XG3V7N4K2M8C
"""

from datetime import datetime
from typing import Optional

from ulid import ULID


def generate_ulid(timestamp: Optional[datetime] = None) -> str:
    """
    Generate a ULID string for use as an ISAAC record_id.

    Args:
        timestamp: Optional datetime to use for the ULID's time component.
                   If None, uses current time.

    Returns:
        26-character uppercase ULID string matching ISAAC schema pattern.

    Example:
        >>> ulid = generate_ulid()
        >>> len(ulid)
        26
        >>> ulid.isupper() and ulid.isalnum()
        True
    """
    if timestamp is not None:
        ulid_obj = ULID.from_datetime(timestamp)
    else:
        ulid_obj = ULID()

    return str(ulid_obj).upper()


def validate_ulid(value: str) -> bool:
    """
    Validate that a string is a valid ULID for ISAAC records.

    Args:
        value: String to validate

    Returns:
        True if valid ULID format, False otherwise

    The ISAAC schema requires:
    - Exactly 26 characters
    - Pattern: ^[0-9A-Z]{26}$
    """
    if len(value) != 26:
        return False

    # Check all characters are uppercase alphanumeric
    for char in value:
        if char not in "0123456789ABCDEFGHJKMNPQRSTVWXYZ":
            return False

    return True


def ulid_from_uuid(uuid_str: str) -> str:
    """
    Generate a ULID from a UUID string.

    This is useful for converting existing data-assembler UUIDs
    to ULID format for ISAAC compatibility.

    Note: This creates a new ULID with current timestamp, as UUIDs
    don't contain temporal information that maps to ULID's time component.

    Args:
        uuid_str: UUID string (used as seed/reference, not directly converted)

    Returns:
        New ULID string
    """
    # UUIDs don't have the same structure as ULIDs, so we generate a new one
    # The UUID can be used for reference/logging but we need a proper ULID
    return generate_ulid()
