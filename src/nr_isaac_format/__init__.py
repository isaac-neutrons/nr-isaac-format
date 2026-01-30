"""
NR-ISAAC Format Converter.

Convert neutron reflectometry data from data-assembler to ISAAC AI-Ready Record format.

This package provides tools to transform the AssemblyResult from data-assembler
into JSON records conforming to the ISAAC AI-Ready Scientific Record v1.0 schema.

Submodules:
- nr_isaac_format.converter: Main conversion orchestration (IsaacRecordConverter)
- nr_isaac_format.mappers: Individual block mappers for ISAAC schema
- nr_isaac_format.ulid: ULID generation utility
- nr_isaac_format.cli: Command-line interface

Example::

    from assembler.workflow import DataAssembler
    from nr_isaac_format import IsaacRecordConverter

    # Get assembled data from data-assembler
    assembler = DataAssembler()
    result = assembler.assemble(reduced=reduced_data)

    # Convert to ISAAC format
    converter = IsaacRecordConverter()
    isaac_record = converter.convert(result)

    # Write to file
    converter.write_json(isaac_record, "output.json")
"""

__version__ = "0.1.0"

from .converter import IsaacRecordConverter

__all__ = ["IsaacRecordConverter", "__version__"]
