"""
Command-line interface for nr-isaac-format.

Simple CLI for converting data-assembler output to ISAAC format.
"""

import json
import sys
from pathlib import Path

import click

from . import __version__
from .writer import IsaacWriter


@click.group()
@click.version_option(version=__version__)
def main() -> None:
    """
    NR-ISAAC Format Writer.

    Convert neutron reflectometry data from data-assembler to ISAAC AI-Ready Record format.
    """
    pass


@main.command()
@click.option("-r", "--reduced", type=click.Path(exists=True, path_type=Path), required=True,
              help="Path to reduced reflectivity data file")
@click.option("-p", "--parquet", type=click.Path(exists=True, path_type=Path),
              help="Directory containing parquet files")
@click.option("-m", "--model", type=click.Path(exists=True, path_type=Path),
              help="Path to refl1d/bumps model JSON file")
@click.option("-o", "--output", type=click.Path(path_type=Path), required=True,
              help="Output path for ISAAC JSON file")
@click.option("--compact", is_flag=True, help="Output compact JSON")
def convert(reduced: Path, parquet: Path | None, model: Path | None, output: Path, compact: bool) -> None:
    """Convert reduced data to ISAAC format via data-assembler pipeline."""
    from assembler.parsers import ReducedParser, ParquetParser, ModelParser
    from assembler.workflow import DataAssembler

    # Parse input files
    reduced_data = ReducedParser().parse(str(reduced))

    parquet_data = None
    if parquet:
        parquet_data = ParquetParser().parse_directory(parquet)

    model_data = None
    if model:
        model_data = ModelParser().parse(str(model))

    # Assemble
    assembler = DataAssembler()
    result = assembler.assemble(reduced=reduced_data, parquet=parquet_data, model=model_data)

    if result.has_errors:
        click.echo(f"Assembly errors: {result.errors}", err=True)
        sys.exit(1)

    # Write ISAAC record
    writer = IsaacWriter()
    record = writer.to_isaac(result)

    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w") as f:
        json.dump(record, f, indent=None if compact else 2, default=str)

    click.echo(f"Wrote ISAAC record: {output}")


@main.command("from-json")
@click.option("-i", "--input", "input_path", type=click.Path(exists=True, path_type=Path), required=True,
              help="Path to assembled result JSON")
@click.option("-o", "--output", type=click.Path(path_type=Path), required=True,
              help="Output path for ISAAC JSON file")
@click.option("--compact", is_flag=True, help="Output compact JSON")
def from_json(input_path: Path, output: Path, compact: bool) -> None:
    """Convert pre-assembled JSON to ISAAC format."""
    from assembler.workflow import AssemblyResult

    with open(input_path) as f:
        data = json.load(f)

    # Reconstruct AssemblyResult from JSON
    result = AssemblyResult(
        reflectivity=data.get("reflectivity"),
        sample=data.get("sample"),
        environment=data.get("environment"),
        reduced_file=data.get("reduced_file"),
        parquet_dir=data.get("parquet_dir"),
        model_file=data.get("model_file"),
        warnings=data.get("warnings", []),
        errors=data.get("errors", []),
    )

    writer = IsaacWriter()
    record = writer.to_isaac(result)

    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w") as f:
        json.dump(record, f, indent=None if compact else 2, default=str)

    click.echo(f"Wrote ISAAC record: {output}")


@main.command()
@click.argument("file", type=click.Path(exists=True, path_type=Path))
def validate(file: Path) -> None:
    """Validate an ISAAC record against the schema."""
    import jsonschema

    # Load bundled schema
    schema_path = Path(__file__).parent / "schema" / "isaac_record_v1.json"
    if not schema_path.exists():
        click.echo("Schema file not found", err=True)
        sys.exit(1)

    with open(schema_path) as f:
        schema = json.load(f)

    with open(file) as f:
        record = json.load(f)

    try:
        jsonschema.validate(record, schema)
        click.echo(f"✓ Valid ISAAC record: {file}")
    except jsonschema.ValidationError as e:
        click.echo(f"✗ Validation failed: {e.message}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
