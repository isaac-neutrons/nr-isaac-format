"""
NR-ISAAC Format Writer.

Convert neutron reflectometry data from data-assembler to ISAAC AI-Ready Record format.

This package provides a writer to transform AssemblyResult from data-assembler
into JSON records conforming to the ISAAC AI-Ready Scientific Record v1.0 schema.

Example::

    from assembler.workflow import DataAssembler
    from nr_isaac_format import IsaacWriter

    # Get assembled data from data-assembler
    assembler = DataAssembler()
    result = assembler.assemble(reduced=reduced_data)

    # Write to ISAAC format
    writer = IsaacWriter()
    writer.write(result, "isaac_record.json")

    # Or get dict directly
    record = writer.to_isaac(result)
"""

__version__ = "0.1.0"

from .writer import IsaacWriter, write_isaac_record

__all__ = ["IsaacWriter", "write_isaac_record", "__version__"]
