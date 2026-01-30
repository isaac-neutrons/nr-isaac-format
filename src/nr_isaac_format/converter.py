"""
ISAAC Record Converter - Main orchestration for converting data-assembler output.

This module provides the IsaacRecordConverter class which coordinates
the conversion of AssemblyResult from data-assembler into ISAAC AI-Ready
Record v1.0 JSON format.
"""

import json
import logging
import os
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Union

from .constants import RecordDomain, RecordType
from .mappers.base import AssemblyResultProtocol, Mapper, MapperContext
from .ulid import generate_ulid

logger = logging.getLogger(__name__)

# ISAAC Record version this converter produces
ISAAC_VERSION = "1.0"

# Type alias for clock function injection
ClockFunc = Callable[[], datetime]


class ConversionResult:
    """
    Result of converting an AssemblyResult to ISAAC format.

    Attributes:
        record: The converted ISAAC record dict
        record_id: The ULID assigned to this record
        warnings: Non-fatal issues encountered
        errors: Fatal issues encountered
        is_valid: Whether the record passed schema validation
    """

    def __init__(
        self,
        record: dict[str, Any],
        record_id: str,
        warnings: Optional[list[str]] = None,
        errors: Optional[list[str]] = None,
        is_valid: bool = True,
        error_details: Optional[list[dict[str, Any]]] = None,
    ):
        self.record = record
        self.record_id = record_id
        self.warnings = warnings or []
        self.errors = errors or []
        self.is_valid = is_valid
        self.error_details = error_details or []  # Structured error info with tracebacks

    @property
    def has_warnings(self) -> bool:
        """Check if conversion produced warnings."""
        return len(self.warnings) > 0

    @property
    def has_errors(self) -> bool:
        """Check if conversion produced errors."""
        return len(self.errors) > 0

    def to_json(self, indent: Optional[int] = 2, include_nulls: bool = False) -> str:
        """
        Serialize the record to JSON string.

        Args:
            indent: JSON indentation (None for compact)
            include_nulls: Whether to include null values

        Returns:
            JSON string representation
        """
        record = self.record
        if not include_nulls:
            record = _remove_nulls(record)
        return json.dumps(record, indent=indent, default=str)


def _remove_nulls(obj: Any) -> Any:
    """Recursively remove null values from dicts."""
    if isinstance(obj, dict):
        return {k: _remove_nulls(v) for k, v in obj.items() if v is not None}
    elif isinstance(obj, list):
        return [_remove_nulls(item) for item in obj]
    return obj


class IsaacRecordConverter:
    """
    Converts data-assembler AssemblyResult to ISAAC AI-Ready Record format.

    The converter uses a collection of Mapper instances to transform
    each block of the ISAAC schema. It orchestrates the conversion
    process, handles validation, and produces the final record.

    Example:
        from assembler.workflow import DataAssembler, AssemblyResult
        from nr_isaac_format import IsaacRecordConverter

        # Get assembled data
        assembler = DataAssembler()
        result = assembler.assemble(reduced=reduced_data)

        # Convert to ISAAC format
        converter = IsaacRecordConverter()
        conversion = converter.convert(result)

        if conversion.is_valid:
            converter.write_json(conversion, "output.json")
        else:
            print("Errors:", conversion.errors)

    Attributes:
        mappers: List of Mapper instances for each ISAAC block
        validate_output: Whether to validate against JSON schema
        schema_path: Optional custom path to ISAAC JSON schema
        clock: Function returning current datetime (for testing)
    """

    def __init__(
        self,
        mappers: Optional[list[Mapper]] = None,
        validate_output: bool = True,
        schema_path: Optional[Union[str, Path]] = None,
        clock: Optional[ClockFunc] = None,
    ):
        """
        Initialize the converter.

        Args:
            mappers: Optional list of Mapper instances. If None, uses
                     default mappers for all ISAAC blocks.
            validate_output: Whether to validate output against ISAAC schema
            schema_path: Optional path to ISAAC JSON schema file
            clock: Optional function returning current datetime (for testing)
        """
        self.mappers = mappers or self._default_mappers()
        self.validate_output = validate_output
        self._schema: Optional[dict] = None
        self._schema_path = Path(schema_path) if schema_path else None
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def _default_mappers(self) -> list[Mapper]:
        """
        Create the default set of mappers for ISAAC blocks.

        Returns list of mapper instances in processing order.
        Order matters: MeasurementMapper populates context.measurement_data
        that DescriptorsMapper uses.
        """
        from .mappers import (
            AcquisitionSourceMapper,
            AssetsMapper,
            ContextMapper,
            DescriptorsMapper,
            LinksMapper,
            MeasurementMapper,
            SampleMapper,
            SystemMapper,
            TimestampsMapper,
        )

        return [
            # Required blocks first
            TimestampsMapper(),
            AcquisitionSourceMapper(),
            # Measurement populates metadata for descriptors
            MeasurementMapper(),
            # Descriptors uses measurement_data from measurement
            DescriptorsMapper(),
            # Optional blocks (Phase 3)
            SampleMapper(),
            SystemMapper(),
            ContextMapper(),
            AssetsMapper(),
            LinksMapper(),
        ]

    def convert(
        self,
        result: AssemblyResultProtocol,
        record_id: Optional[str] = None,
        timestamp: Optional[datetime] = None,
    ) -> ConversionResult:
        """
        Convert an AssemblyResult to ISAAC AI-Ready Record format.

        Args:
            result: Object conforming to AssemblyResultProtocol
            record_id: Optional ULID to use. If None, generates new ULID.
            timestamp: Optional timestamp for ULID generation and created_utc

        Returns:
            ConversionResult containing the ISAAC record and any issues
        """
        # Determine creation timestamp using injected clock
        if timestamp is None:
            timestamp = self._clock()

        # Generate record ID if not provided
        if record_id is None:
            record_id = generate_ulid(timestamp)

        # Create mapper context with the AssemblyResult
        context = MapperContext(
            result=result,
            record_id=record_id,
            created_utc=timestamp,
        )

        # Initialize record with required fields using enums
        record: dict[str, Any] = {
            "record_id": record_id,
            "isaac_record_version": ISAAC_VERSION,
            "record_type": RecordType.EVIDENCE.value,
            "record_domain": RecordDomain.CHARACTERIZATION.value,
        }

        # Track error details for debugging
        error_details: list[dict[str, Any]] = []

        # Run each mapper
        for mapper in self.mappers:
            try:
                block = mapper.map(context)
                if block is not None:
                    # Validate block
                    if not mapper.validate(block, context):
                        logger.warning(f"Mapper {mapper.block_name} validation failed")
                    record[mapper.block_name] = block
                elif mapper.is_required():
                    context.add_error(f"Required block '{mapper.block_name}' returned None")
            except Exception as e:
                error_msg = f"Mapper {mapper.block_name} failed: {e}"
                context.add_error(error_msg)
                # Capture detailed error info for debugging
                error_details.append(
                    {
                        "mapper": mapper.block_name,
                        "error": str(e),
                        "type": type(e).__name__,
                        "traceback": traceback.format_exc(),
                    }
                )
                logger.exception(f"Mapper {mapper.block_name} raised exception")

        # Validate against JSON schema if enabled
        is_valid = True
        if self.validate_output:
            schema_errors = self._validate_schema(record)
            if schema_errors:
                context.errors.extend(schema_errors)
                is_valid = False

        return ConversionResult(
            record=record,
            record_id=record_id,
            warnings=context.warnings,
            errors=context.errors,
            is_valid=is_valid and not context.has_errors,
            error_details=error_details,
        )

    def _validate_schema(self, record: dict[str, Any]) -> list[str]:
        """
        Validate record against ISAAC JSON schema.

        Returns list of validation errors (empty if valid).
        """
        try:
            import jsonschema
        except ImportError:
            logger.warning("jsonschema not installed, skipping validation")
            return []

        schema = self._load_schema()
        if schema is None:
            return []

        validator = jsonschema.Draft7Validator(schema)
        errors = []
        for error in validator.iter_errors(record):
            path = ".".join(str(p) for p in error.absolute_path)
            errors.append(f"{path}: {error.message}" if path else error.message)

        return errors

    def _load_schema(self) -> Optional[dict]:
        """
        Load the ISAAC JSON schema.

        Search order:
        1. Explicitly configured schema_path
        2. Environment variable ISAAC_SCHEMA_PATH
        3. Bundled schema in package
        """
        if self._schema is not None:
            return self._schema

        # 1. User-provided schema path
        if self._schema_path and self._schema_path.exists():
            return self._load_schema_from_path(self._schema_path)

        # 2. Environment variable
        env_path = os.environ.get("ISAAC_SCHEMA_PATH")
        if env_path:
            env_path_obj = Path(env_path)
            if env_path_obj.exists():
                return self._load_schema_from_path(env_path_obj)

        # 3. Bundled schema in package
        bundled_path = Path(__file__).parent / "schema" / "isaac_record_v1.json"
        if bundled_path.exists():
            return self._load_schema_from_path(bundled_path)

        logger.warning(
            "Could not find ISAAC JSON schema. Pass schema_path to "
            "IsaacRecordConverter or set ISAAC_SCHEMA_PATH environment variable."
        )
        return None

    def _load_schema_from_path(self, path: Path) -> Optional[dict]:
        """Load schema from a specific path."""
        try:
            with open(path) as f:
                self._schema = json.load(f)
            logger.info(f"Loaded ISAAC schema from {path}")
            return self._schema
        except Exception as e:
            logger.warning(f"Failed to load schema from {path}: {e}")
            return None

    def write_json(
        self,
        result: ConversionResult,
        output_path: str | Path,
        indent: Optional[int] = 2,
        include_nulls: bool = False,
    ) -> None:
        """
        Write conversion result to JSON file.

        Args:
            result: The ConversionResult to write
            output_path: Path to output file
            indent: JSON indentation level (None for compact)
            include_nulls: Whether to include null values
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        record = result.record
        if not include_nulls:
            record = _remove_nulls(record)

        with open(output_path, "w") as f:
            json.dump(record, f, indent=indent, default=str)

        logger.info(f"Wrote ISAAC record to {output_path}")

    @classmethod
    def from_json_file(
        cls,
        input_path: str | Path,
        validate: bool = True,
    ) -> ConversionResult:
        """
        Load an existing ISAAC record from JSON file.

        Args:
            input_path: Path to JSON file
            validate: Whether to validate against schema

        Returns:
            ConversionResult with the loaded record
        """
        input_path = Path(input_path)

        with open(input_path) as f:
            record = json.load(f)

        record_id = record.get("record_id", "unknown")
        converter = cls(validate_output=validate)

        errors = []
        if validate:
            errors = converter._validate_schema(record)

        return ConversionResult(
            record=record,
            record_id=record_id,
            errors=errors,
            is_valid=len(errors) == 0,
        )
