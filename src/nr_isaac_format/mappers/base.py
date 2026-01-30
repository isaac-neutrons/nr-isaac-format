"""
Base mapper class and context for ISAAC record conversion.

Provides the abstract interface that all block mappers must implement,
along with a shared context for passing data between mappers.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, Protocol, runtime_checkable


@runtime_checkable
class AssemblyResultProtocol(Protocol):
    """
    Protocol defining the interface for assembly results.

    This allows the converter to work with any object that provides
    these attributes, not just the concrete AssemblyResult class.
    This improves testability and decouples from data-assembler.
    """

    @property
    def reflectivity(self) -> Optional[dict[str, Any]]: ...

    @property
    def sample(self) -> Optional[dict[str, Any]]: ...

    @property
    def environment(self) -> Optional[dict[str, Any]]: ...

    @property
    def warnings(self) -> list[str]: ...

    @property
    def errors(self) -> list[str]: ...


@dataclass
class MeasurementData:
    """
    Data extracted from measurement mapping.

    Used to pass measurement metadata to dependent mappers (like DescriptorsMapper)
    in an explicit, type-safe way instead of using mutable shared state.
    """

    q_min: Optional[float] = None
    q_max: Optional[float] = None
    n_points: Optional[int] = None
    measurement_geometry: Optional[str] = None


@dataclass
class MapperContext:
    """
    Shared context passed between mappers during conversion.

    Contains the source data from data-assembler and accumulates
    warnings/errors during the conversion process.

    Attributes:
        result: Object conforming to AssemblyResultProtocol
        record_id: The ULID for this ISAAC record
        created_utc: Timestamp when conversion started
        warnings: Non-fatal issues encountered during mapping
        errors: Fatal issues that may invalidate the record
        metadata: Additional data that mappers can share (deprecated, use typed fields)
        measurement_data: Typed measurement metadata for dependent mappers
    """

    result: AssemblyResultProtocol
    record_id: str
    created_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)  # Kept for backwards compat
    measurement_data: MeasurementData = field(default_factory=MeasurementData)

    @property
    def reflectivity(self) -> Optional[dict[str, Any]]:
        """Shortcut to reflectivity record from AssemblyResult."""
        return self.result.reflectivity

    @property
    def sample(self) -> Optional[dict[str, Any]]:
        """Shortcut to sample record from AssemblyResult."""
        return self.result.sample

    @property
    def environment(self) -> Optional[dict[str, Any]]:
        """Shortcut to environment record from AssemblyResult."""
        return self.result.environment

    def add_warning(self, message: str) -> None:
        """Add a warning message to the context."""
        self.warnings.append(message)

    def add_error(self, message: str) -> None:
        """Add an error message to the context."""
        self.errors.append(message)

    @property
    def has_warnings(self) -> bool:
        """Check if any warnings have been added."""
        return len(self.warnings) > 0

    @property
    def has_errors(self) -> bool:
        """Check if any errors have been added."""
        return len(self.errors) > 0


class Mapper(ABC):
    """
    Abstract base class for ISAAC schema block mappers.

    Each mapper is responsible for converting a portion of the
    data-assembler AssemblyResult into a specific block of the
    ISAAC AI-Ready Record schema.

    Subclasses must implement:
    - block_name: The name of the ISAAC block (e.g., "timestamps", "sample")
    - map(): The conversion logic

    Example:
        class TimestampsMapper(Mapper):
            block_name = "timestamps"

            def map(self, context: MapperContext) -> dict[str, Any]:
                return {
                    "created_utc": context.created_utc.isoformat(),
                    "acquired_start_utc": ...,
                }
    """

    @property
    @abstractmethod
    def block_name(self) -> str:
        """
        The name of the ISAAC schema block this mapper produces.

        This is used as the key in the final ISAAC record dict.
        """
        pass

    @abstractmethod
    def map(self, context: MapperContext) -> Optional[dict[str, Any]]:
        """
        Map data from the context to an ISAAC schema block.

        Args:
            context: The shared MapperContext with source data

        Returns:
            Dict representing the ISAAC block, or None if the block
            should be omitted (e.g., optional block with no data)
        """
        pass

    def is_required(self) -> bool:
        """
        Whether this block is required in the ISAAC schema.

        Override in subclasses for required blocks.
        Default is False (optional block).
        """
        return False

    def validate(self, block: dict[str, Any], context: MapperContext) -> bool:
        """
        Validate the mapped block against ISAAC schema requirements.

        Override in subclasses for block-specific validation.
        Default implementation returns True.

        Args:
            block: The mapped block dict
            context: The shared context for reporting issues

        Returns:
            True if valid, False if validation failed
        """
        return True
