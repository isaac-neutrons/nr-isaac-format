"""
Constants and enums for ISAAC record generation.

Centralizes magic strings to improve maintainability and type safety.
"""

from enum import Enum


class RecordType(str, Enum):
    """ISAAC record_type values."""

    EVIDENCE = "evidence"
    INTERPRETATION = "interpretation"
    PROTOCOL = "protocol"
    ANNOTATION = "annotation"


class RecordDomain(str, Enum):
    """ISAAC record_domain values."""

    CHARACTERIZATION = "characterization"
    SYNTHESIS = "synthesis"
    SIMULATION = "simulation"
    THEORY = "theory"


class SourceType(str, Enum):
    """Acquisition source types."""

    FACILITY = "facility"
    LABORATORY = "laboratory"
    COMPUTATION = "computation"
    LITERATURE = "literature"
    DATABASE = "database"


class ContentRole(str, Enum):
    """Asset content_role values."""

    RAW_DATA_POINTER = "raw_data_pointer"
    REDUCTION_PRODUCT = "reduction_product"
    PROCESSING_RECIPE = "processing_recipe"
    INPUT_STRUCTURE = "input_structure"
    METADATA_SNAPSHOT = "metadata_snapshot"
    SUPPLEMENTARY_IMAGE = "supplementary_image"
    OTHER = "other"


class ChannelRole(str, Enum):
    """Measurement channel role values."""

    PRIMARY_SIGNAL = "primary_signal"
    MEASURED_RESPONSE = "measured_response"
    SIMULATED_OBSERVABLE = "simulated_observable"
    DERIVED_SIGNAL = "derived_signal"
    AUXILIARY_SIGNAL = "auxiliary_signal"
    CONTROL_READBACK = "control_readback"
    QUALITY_MONITOR = "quality_monitor"


class QCStatus(str, Enum):
    """Quality control status values."""

    VALID = "valid"
    SUSPECT = "suspect"
    INVALID = "invalid"


class DescriptorKind(str, Enum):
    """Descriptor kind values."""

    ABSOLUTE = "absolute"
    DIFFERENTIAL = "differential"
    CATEGORICAL = "categorical"
    SIMILARITY = "similarity"
    MODEL = "model"


class DescriptorSource(str, Enum):
    """Descriptor source values."""

    COMPUTED = "computed"
    METADATA = "metadata"
    MODEL = "model"
    UNKNOWN = "unknown"
    SYSTEM = "system"


class SampleForm(str, Enum):
    """Common sample form values."""

    THIN_FILM = "thin_film"
    BULK = "bulk"
    POWDER = "powder"
    SOLUTION = "solution"
    GAS = "gas"


class SystemDomain(str, Enum):
    """System domain values."""

    EXPERIMENTAL = "experimental"
    COMPUTATIONAL = "computational"


class InstrumentType(str, Enum):
    """Instrument type values."""

    BEAMLINE_ENDSTATION = "beamline_endstation"
    LAB_INSTRUMENT = "lab_instrument"
    SIMULATION_SOFTWARE = "simulation_software"


class LinkType(str, Enum):
    """Link type values for record relationships."""

    DERIVED_FROM = "derived_from"
    PART_OF = "part_of"
    RELATED_TO = "related_to"
    SUPERSEDES = "supersedes"
    CITES = "cites"
    REFERENCES = "references"


# Default values for neutron reflectometry
DEFAULT_ENDSTATION = "reflectometer"
DEFAULT_PROBE = "neutrons"
DEFAULT_TECHNIQUE = "reflectivity"
DEFAULT_Q_UNIT = "Å⁻¹"
DEFAULT_R_UNIT = "dimensionless"

# ISAAC schema version
ISAAC_VERSION = "1.0"
