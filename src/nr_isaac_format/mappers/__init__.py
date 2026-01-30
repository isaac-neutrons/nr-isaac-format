"""
Mappers for converting data-assembler records to ISAAC schema blocks.

Each mapper is responsible for transforming a portion of the AssemblyResult
into the corresponding ISAAC AI-Ready Record block.
"""

from .acquisition_source import AcquisitionSourceMapper
from .assets import AssetsMapper
from .base import Mapper, MapperContext
from .context import ContextMapper
from .descriptors import DescriptorsMapper
from .links import LinksMapper
from .measurement import MeasurementMapper
from .sample import SampleMapper
from .system import SystemMapper
from .timestamps import TimestampsMapper

__all__ = [
    "Mapper",
    "MapperContext",
    # Required mappers (Phase 2)
    "TimestampsMapper",
    "AcquisitionSourceMapper",
    "MeasurementMapper",
    "DescriptorsMapper",
    # Optional mappers (Phase 3)
    "SampleMapper",
    "SystemMapper",
    "ContextMapper",
    "AssetsMapper",
    "LinksMapper",
]
