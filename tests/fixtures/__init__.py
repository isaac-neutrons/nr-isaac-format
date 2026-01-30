"""Test fixtures for nr-isaac-format tests."""

from .assembly_results import (
    create_minimal_assembly,
    create_full_assembly,
    create_sns_refl_assembly,
    create_simulated_assembly,
    create_partial_assembly,
)
from .golden_records import (
    GOLDEN_RECORD_MINIMAL,
    GOLDEN_RECORD_FULL,
)

__all__ = [
    "create_minimal_assembly",
    "create_full_assembly",
    "create_sns_refl_assembly",
    "create_simulated_assembly",
    "create_partial_assembly",
    "GOLDEN_RECORD_MINIMAL",
    "GOLDEN_RECORD_FULL",
]
