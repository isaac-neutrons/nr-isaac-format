"""
Command-line interface for nr-isaac-format.

Provides commands for converting data-assembler output to ISAAC format.
"""

import json
import logging
import sys
from pathlib import Path
from typing import Optional

import click

from . import __version__
from .converter import IsaacRecordConverter

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


# Common output format options
def output_format_options(func):
    """Decorator to add common output format options."""
    func = click.option(
        "--pretty/--no-pretty",
        default=True,
        help="Pretty-print JSON output with indentation (default: enabled)",
    )(func)
    func = click.option(
        "--compact",
        is_flag=True,
        help="Output compact JSON (overrides --pretty)",
    )(func)
    func = click.option(
        "--include-nulls",
        is_flag=True,
        help="Include null values in output (default: omit nulls)",
    )(func)
    return func


def get_json_options(pretty: bool, compact: bool, include_nulls: bool) -> dict:
    """Get JSON serialization options from CLI flags."""
    indent = None if compact else (2 if pretty else None)
    return {
        "indent": indent,
        "include_nulls": include_nulls,
    }


@click.group()
@click.version_option(version=__version__)
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose output")
def main(verbose: bool) -> None:
    """
    NR-ISAAC Format Converter.

    Convert neutron reflectometry data from data-assembler to ISAAC AI-Ready Record format.
    """
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)


@main.command()
@click.option(
    "-r",
    "--reduced",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Path to reduced reflectivity data file (.txt)",
)
@click.option(
    "-p",
    "--parquet",
    type=click.Path(exists=True, path_type=Path),
    help="Directory containing parquet files from nexus-processor",
)
@click.option(
    "-m",
    "--model",
    type=click.Path(exists=True, path_type=Path),
    help="Path to refl1d/bumps model JSON file",
)
@click.option(
    "-o",
    "--output",
    type=click.Path(path_type=Path),
    required=True,
    help="Output path for ISAAC JSON file",
)
@click.option(
    "--validate/--no-validate",
    default=True,
    help="Validate output against ISAAC schema",
)
@click.option(
    "--schema",
    type=click.Path(exists=True, path_type=Path),
    help="Path to custom ISAAC JSON schema file",
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="Parse and convert but don't write output",
)
@output_format_options
def convert(
    reduced: Path,
    parquet: Optional[Path],
    model: Optional[Path],
    output: Path,
    validate: bool,
    schema: Optional[Path],
    dry_run: bool,
    pretty: bool,
    compact: bool,
    include_nulls: bool,
) -> None:
    """
    Convert data-assembler inputs to ISAAC AI-Ready Record format.

    This command runs the data-assembler pipeline and converts the result
    to ISAAC format in a single step.

    Example:

        nr-isaac-format convert -r reduced.txt -o output.json

        nr-isaac-format convert -r reduced.txt -p parquet/ -m model.json -o output.json
    """
    from assembler.parsers import ModelParser, ParquetParser, ReducedParser
    from assembler.workflow import DataAssembler

    from .converter import IsaacRecordConverter

    click.echo(f"Converting {reduced.name} to ISAAC format...")

    # Parse input files using data-assembler
    try:
        reduced_data = ReducedParser().parse(str(reduced))
        click.echo(f"  Parsed reduced data: {len(reduced_data.q)} Q points")
    except Exception as e:
        click.echo(f"Error parsing reduced file: {e}", err=True)
        sys.exit(1)

    parquet_data = None
    if parquet:
        try:
            run_number = reduced_data.run_number
            parquet_data = ParquetParser().parse_directory(str(parquet), run_number=run_number)
            click.echo(f"  Parsed parquet metadata")
        except Exception as e:
            click.echo(f"Warning: Could not parse parquet: {e}", err=True)

    model_data = None
    if model:
        try:
            model_data = ModelParser().parse(str(model))
            click.echo(f"  Parsed model: {len(model_data.layers)} layers")
        except Exception as e:
            click.echo(f"Warning: Could not parse model: {e}", err=True)

    # Assemble data
    assembler = DataAssembler()
    result = assembler.assemble(
        reduced=reduced_data,
        parquet=parquet_data,
        model=model_data,
    )

    if result.has_errors:
        click.echo("Assembly errors:", err=True)
        for error in result.errors:
            click.echo(f"  - {error}", err=True)
        sys.exit(1)

    # Convert to ISAAC format
    converter = IsaacRecordConverter(validate_output=validate, schema_path=schema)
    conversion = converter.convert(result)

    # Report warnings
    if conversion.has_warnings:
        click.echo("Warnings:")
        for warning in conversion.warnings:
            click.echo(f"  - {warning}")

    # Report errors
    if conversion.has_errors:
        click.echo("Errors:", err=True)
        for error in conversion.errors:
            click.echo(f"  - {error}", err=True)

    if not conversion.is_valid:
        click.echo("Output failed schema validation", err=True)
        sys.exit(1)

    # Get JSON formatting options
    json_opts = get_json_options(pretty, compact, include_nulls)

    # Write output
    if dry_run:
        click.echo(f"\nDry run - would write to: {output}")
        click.echo("\nRecord preview:")
        click.echo(
            conversion.to_json(indent=json_opts["indent"], include_nulls=json_opts["include_nulls"])
        )
    else:
        converter.write_json(
            conversion, output, indent=json_opts["indent"], include_nulls=json_opts["include_nulls"]
        )
        click.echo(f"\nWrote ISAAC record to: {output}")
        click.echo(f"  Record ID: {conversion.record_id}")


@main.command()
@click.option(
    "-i",
    "--input",
    "input_path",
    type=click.Path(exists=True, path_type=Path),
    required=True,
    help="Path to assembled result JSON (from data-assembler --json)",
)
@click.option(
    "-o",
    "--output",
    type=click.Path(path_type=Path),
    required=True,
    help="Output path for ISAAC JSON file",
)
@click.option(
    "--validate/--no-validate",
    default=True,
    help="Validate output against ISAAC schema",
)
@click.option(
    "--schema",
    type=click.Path(exists=True, path_type=Path),
    help="Path to custom ISAAC JSON schema file",
)
@output_format_options
def from_json(
    input_path: Path,
    output: Path,
    validate: bool,
    schema: Optional[Path],
    pretty: bool,
    compact: bool,
    include_nulls: bool,
) -> None:
    """
    Convert a data-assembler JSON output to ISAAC format.

    Use this when you have already run data-assembler with --json flag
    and want to convert the output to ISAAC format.

    Example:

        nr-isaac-format from-json -i assembled.json -o isaac_record.json
    """
    import json

    from assembler.workflow.result import AssemblyResult

    from .converter import IsaacRecordConverter

    click.echo(f"Loading {input_path.name}...")

    try:
        with open(input_path) as f:
            data = json.load(f)

        # Reconstruct AssemblyResult from JSON
        result = AssemblyResult(
            reflectivity=data.get("reflectivity"),
            sample=data.get("sample"),
            environment=data.get("environment"),
            reduced_file=data.get("reduced_file"),
            model_file=data.get("model_file"),
            warnings=data.get("warnings", []),
            errors=data.get("errors", []),
            needs_review=data.get("needs_review", {}),
        )

    except Exception as e:
        click.echo(f"Error loading JSON: {e}", err=True)
        sys.exit(1)

    # Convert to ISAAC format
    converter = IsaacRecordConverter(validate_output=validate, schema_path=schema)
    conversion = converter.convert(result)

    if conversion.has_warnings:
        click.echo("Warnings:")
        for warning in conversion.warnings:
            click.echo(f"  - {warning}")

    if not conversion.is_valid:
        click.echo("Output failed schema validation", err=True)
        for error in conversion.errors:
            click.echo(f"  - {error}", err=True)
        sys.exit(1)

    json_opts = get_json_options(pretty, compact, include_nulls)
    converter.write_json(
        conversion, output, indent=json_opts["indent"], include_nulls=json_opts["include_nulls"]
    )
    click.echo(f"Wrote ISAAC record to: {output}")
    click.echo(f"  Record ID: {conversion.record_id}")


@main.command()
@click.option(
    "-i",
    "--input-dir",
    "input_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    required=True,
    help="Input directory containing assembled JSON files",
)
@click.option(
    "-o",
    "--output-dir",
    "output_dir",
    type=click.Path(file_okay=False, path_type=Path),
    required=True,
    help="Output directory for ISAAC JSON files",
)
@click.option(
    "--pattern",
    default="*.json",
    help="Glob pattern for input files (default: *.json)",
)
@click.option(
    "--validate/--no-validate",
    default=True,
    help="Validate output against ISAAC schema",
)
@click.option(
    "--schema",
    type=click.Path(exists=True, path_type=Path),
    help="Path to custom ISAAC JSON schema file",
)
@click.option(
    "--continue-on-error",
    is_flag=True,
    help="Continue processing if a file fails",
)
@output_format_options
def batch(
    input_dir: Path,
    output_dir: Path,
    pattern: str,
    validate: bool,
    schema: Optional[Path],
    continue_on_error: bool,
    pretty: bool,
    compact: bool,
    include_nulls: bool,
) -> None:
    """
    Batch convert multiple data-assembler JSON files to ISAAC format.

    Processes all files matching the pattern in the input directory
    and writes converted files to the output directory.

    Example:

        nr-isaac-format batch -i assembled/ -o isaac_records/

        nr-isaac-format batch -i data/ -o output/ --pattern "run_*.json" --compact
    """
    from assembler.workflow.result import AssemblyResult

    from .converter import IsaacRecordConverter

    # Find input files
    input_files = sorted(input_dir.glob(pattern))

    if not input_files:
        click.echo(f"No files matching '{pattern}' found in {input_dir}", err=True)
        sys.exit(1)

    click.echo(f"Found {len(input_files)} files to convert")

    # Create output directory
    output_dir.mkdir(parents=True, exist_ok=True)

    # Initialize converter
    converter = IsaacRecordConverter(validate_output=validate, schema_path=schema)
    json_opts = get_json_options(pretty, compact, include_nulls)

    # Track statistics
    success_count = 0
    error_count = 0
    warning_count = 0

    # Process files with progress bar
    with click.progressbar(
        input_files,
        label="Converting files",
        show_pos=True,
        item_show_func=lambda p: p.name if p else "",
    ) as files:
        for input_file in files:
            try:
                result = _convert_single_file(input_file, output_dir, converter, json_opts)

                if result["success"]:
                    success_count += 1
                    if result["warnings"]:
                        warning_count += len(result["warnings"])
                else:
                    error_count += 1
                    if not continue_on_error:
                        click.echo(f"\nError processing {input_file.name}:", err=True)
                        for error in result["errors"]:
                            click.echo(f"  - {error}", err=True)
                        sys.exit(1)

            except Exception as e:
                error_count += 1
                if not continue_on_error:
                    click.echo(f"\nFailed to process {input_file.name}: {e}", err=True)
                    sys.exit(1)

    # Summary
    click.echo(f"\nBatch conversion complete:")
    click.echo(f"  ✓ {success_count} files converted successfully")
    if warning_count > 0:
        click.echo(f"  ⚠ {warning_count} warnings")
    if error_count > 0:
        click.echo(f"  ✗ {error_count} files failed")
        sys.exit(1)


def _convert_single_file(
    input_file: Path,
    output_dir: Path,
    converter: "IsaacRecordConverter",
    json_opts: dict,
) -> dict:
    """Convert a single file and return result info."""
    from assembler.workflow.result import AssemblyResult

    # Load input JSON
    with open(input_file) as f:
        data = json.load(f)

    # Reconstruct AssemblyResult
    result = AssemblyResult(
        reflectivity=data.get("reflectivity"),
        sample=data.get("sample"),
        environment=data.get("environment"),
        reduced_file=data.get("reduced_file"),
        model_file=data.get("model_file"),
        warnings=data.get("warnings", []),
        errors=data.get("errors", []),
        needs_review=data.get("needs_review", {}),
    )

    # Convert
    conversion = converter.convert(result)

    if conversion.is_valid:
        # Write output
        output_file = output_dir / f"isaac_{input_file.stem}.json"
        converter.write_json(
            conversion,
            output_file,
            indent=json_opts["indent"],
            include_nulls=json_opts["include_nulls"],
        )

    return {
        "success": conversion.is_valid,
        "record_id": conversion.record_id,
        "warnings": conversion.warnings,
        "errors": conversion.errors,
    }


@main.command()
@click.argument(
    "json_file",
    type=click.Path(exists=True, path_type=Path),
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    help="Show detailed validation information",
)
def validate(json_file: Path, verbose: bool) -> None:
    """
    Validate an ISAAC record against the JSON schema.

    Example:

        nr-isaac-format validate output.json

        nr-isaac-format validate output.json --verbose
    """
    import jsonschema

    click.echo(f"Validating {json_file.name}...")

    try:
        with open(json_file) as f:
            record = json.load(f)
    except json.JSONDecodeError as e:
        click.echo(f"✗ Invalid JSON: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error loading file: {e}", err=True)
        sys.exit(1)

    # Show record info if verbose
    if verbose:
        record_id = record.get("record_id", "unknown")
        version = record.get("isaac_record_version", "unknown")
        click.echo(f"  Record ID: {record_id}")
        click.echo(f"  ISAAC version: {version}")
        click.echo(
            f"  Blocks present: {', '.join(k for k in record.keys() if k not in ['record_id', 'isaac_record_version', 'record_type', 'record_domain'])}"
        )

    # Load schema
    schema_path = Path.home() / "git" / "isaac-ai-ready-record" / "schema" / "isaac_record_v1.json"
    if not schema_path.exists():
        click.echo(f"Schema not found at: {schema_path}", err=True)
        sys.exit(1)

    try:
        with open(schema_path) as f:
            schema = json.load(f)
    except Exception as e:
        click.echo(f"Error loading schema: {e}", err=True)
        sys.exit(1)

    # Validate with detailed error collection
    validator = jsonschema.Draft7Validator(schema)
    errors = list(validator.iter_errors(record))

    if not errors:
        click.echo("✓ Record is valid against ISAAC schema v1.0")
        return

    # Report errors with enhanced details
    click.echo(f"✗ Validation failed with {len(errors)} error(s):", err=True)

    for i, error in enumerate(errors, 1):
        path = ".".join(str(p) for p in error.absolute_path) or "(root)"
        click.echo(f"\n  [{i}] Path: {path}", err=True)
        click.echo(f"      Error: {error.message}", err=True)

        if verbose:
            # Show schema context
            if error.schema_path:
                schema_loc = ".".join(str(p) for p in error.schema_path)
                click.echo(f"      Schema location: {schema_loc}", err=True)

            # Show failing value (truncated if long)
            if error.instance is not None:
                instance_str = str(error.instance)
                if len(instance_str) > 80:
                    instance_str = instance_str[:77] + "..."
                click.echo(f"      Value: {instance_str}", err=True)

    sys.exit(1)


if __name__ == "__main__":
    main()
