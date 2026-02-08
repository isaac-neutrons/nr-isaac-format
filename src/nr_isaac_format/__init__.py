"""
NR-ISAAC Format Writer.

Convert neutron reflectometry data from data-assembler to ISAAC AI-Ready Record format.

This package provides a CLI and writer to transform data described by a YAML
manifest into JSON records conforming to the ISAAC AI-Ready Scientific Record
v1.0 schema.

CLI usage::

    nr-isaac-format convert experiment.yaml
    nr-isaac-format validate output/isaac_record_01_steady-state_ocv.json

Programmatic usage::

    from assembler.parsers import ManifestParser, ReducedParser
    from assembler.workflow import DataAssembler
    from nr_isaac_format import IsaacWriter

    # Parse manifest and assemble data
    manifest = ManifestParser().parse("experiment.yaml")
    result = DataAssembler().assemble(reduced=ReducedParser().parse(...))

    # Convert to ISAAC format
    writer = IsaacWriter()
    record = writer.to_isaac(result, title=manifest.title)
"""

__version__ = "0.1.0"

from .writer import IsaacWriter, write_isaac_record

__all__ = ["IsaacWriter", "write_isaac_record", "__version__"]
