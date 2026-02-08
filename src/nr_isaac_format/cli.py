"""
Command-line interface for nr-isaac-format.

Manifest-driven CLI for converting data-assembler output to ISAAC format.
Takes a YAML manifest file describing a sample and its measurements,
runs each measurement through the data-assembler pipeline, and writes
one ISAAC AI-Ready Record per measurement.
"""

import json
import sys
from pathlib import Path
from typing import Optional

import click

from . import __version__
from .writer import IsaacWriter


@click.group()
@click.version_option(version=__version__)
def main() -> None:
    """
    NR-ISAAC Format Writer.

    Convert neutron reflectometry data to ISAAC AI-Ready Record format
    using a YAML manifest file.
    """
    pass


@main.command()
@click.argument("manifest", type=click.Path(exists=True, path_type=Path))
@click.option("--compact", is_flag=True, help="Output compact JSON (no indentation)")
@click.option("--dry-run", is_flag=True, help="Parse and assemble but don't write output")
def convert(manifest: Path, compact: bool, dry_run: bool) -> None:
    """Convert measurements described in a YAML manifest to ISAAC format.

    MANIFEST is a YAML file describing a sample and its measurement history.
    Each measurement produces one ISAAC AI-Ready Record JSON file.

    Example:

        nr-isaac-format convert expt_34347.yaml

    \b
    Manifest format:
        title: "Experiment title"
        sample:
          description: "Sample description"
          model: /path/to/model.json
          model_dataset_index: 1
        output: /path/to/output/
        measurements:
          - name: "Measurement 1"
            reduced: /path/to/reduced.txt
            parquet: /path/to/parquet/       # optional
            model: /path/to/model.json       # optional (overrides sample.model)
            model_dataset_index: 1           # optional
            environment: "Description text"  # optional
    """
    from assembler.parsers import ManifestParser, ModelParser, ParquetParser, ReducedParser
    from assembler.tools.detection import extract_run_number
    from assembler.workflow import DataAssembler

    # Parse manifest
    parser = ManifestParser()
    try:
        manifest_data = parser.parse(manifest)
    except Exception as e:
        click.echo(click.style(f"Error parsing manifest: {e}", fg="red"), err=True)
        sys.exit(1)

    # Validate
    errors = manifest_data.validate()
    if errors:
        click.echo(click.style("Manifest validation errors:", fg="red"), err=True)
        for error in errors:
            click.echo(f"  - {error}", err=True)
        sys.exit(1)

    title = manifest_data.title or manifest.stem
    click.echo(click.style(f"Converting: {title}", fg="cyan", bold=True))
    click.echo(f"  Output: {manifest_data.output}")
    click.echo(f"  Measurements: {len(manifest_data.measurements)}")
    click.echo()

    output_path = Path(manifest_data.output)

    reduced_parser = ReducedParser()
    parquet_parser = ParquetParser()
    model_parser = ModelParser()
    assembler = DataAssembler()

    sample_id: Optional[str] = None
    written_files: list[Path] = []

    for i, measurement in enumerate(manifest_data.measurements):
        step = f"[{i + 1}/{len(manifest_data.measurements)}]"
        click.echo(click.style(f"{step} {measurement.name}", fg="cyan"))

        # Parse reduced data (required)
        try:
            reduced_data = reduced_parser.parse(measurement.reduced)
        except Exception as e:
            click.echo(click.style(f"  Error parsing reduced file: {e}", fg="red"), err=True)
            sys.exit(1)

        # Parse parquet data (optional)
        parquet_data = None
        if measurement.parquet:
            try:
                run_number = extract_run_number(measurement.reduced)
                parquet_data = parquet_parser.parse_directory(
                    measurement.parquet, run_number=run_number
                )
            except Exception as e:
                click.echo(
                    click.style(f"  Error parsing parquet files: {e}", fg="red"), err=True
                )
                sys.exit(1)

        # Parse model (optional, measurement-level overrides sample-level)
        model_data = None
        model_file = measurement.model or manifest_data.sample.model
        if model_file:
            ds_index_1based = (
                measurement.model_dataset_index or manifest_data.sample.model_dataset_index
            )
            ds_index = (ds_index_1based - 1) if ds_index_1based is not None else None
            try:
                model_data = model_parser.parse(model_file, dataset_index=ds_index)
            except Exception as e:
                click.echo(
                    click.style(f"  Error parsing model file: {e}", fg="red"), err=True
                )
                sys.exit(1)

        # Assemble via data-assembler
        result = assembler.assemble(
            reduced=reduced_data,
            parquet=parquet_data,
            model=model_data,
            environment_description=measurement.environment,
            sample_id=sample_id,
        )

        if result.has_errors:
            click.echo(click.style("  Assembly errors:", fg="red"), err=True)
            for error in result.errors:
                click.echo(f"    - {error}", err=True)
            sys.exit(1)

        for warning in result.warnings:
            click.echo(click.style(f"  Warning: {warning}", fg="yellow"), err=True)

        # Capture sample from first measurement for reuse
        if i == 0 and result.sample:
            sample_id = result.sample["id"]
            if manifest_data.sample.description:
                result.sample["description"] = manifest_data.sample.description
            click.echo(
                f"  Sample: {result.sample.get('description', 'unknown')} "
                f"({sample_id[:8]}...)"
            )
        elif sample_id:
            click.echo(f"  Sample: {sample_id[:8]}... (reused)")

        if result.reflectivity:
            refl_data = result.reflectivity.get("reflectivity", {})
            q = refl_data.get("q", [])
            run_number = result.reflectivity.get("run_number")
            click.echo(f"  Reflectivity: run {run_number}, {len(q)} Q points")

        # Write ISAAC record
        writer = IsaacWriter()
        record = writer.to_isaac(
            result,
            environment_description=measurement.environment,
        )

        if dry_run:
            click.echo(click.style("  (dry run — not written)", fg="cyan"))
        else:
            output_path.mkdir(parents=True, exist_ok=True)

            # Name file by run number (preferred) or measurement index
            run_number = result.reflectivity.get("run_number") if result.reflectivity else None
            if run_number:
                filename = f"isaac_record_{run_number}.json"
            else:
                safe_name = measurement.name.lower().replace(" ", "_")
                filename = f"isaac_record_{i + 1:02d}_{safe_name}.json"
            file_path = output_path / filename

            with open(file_path, "w") as f:
                json.dump(record, f, indent=None if compact else 2, default=str)

            written_files.append(file_path)
            click.echo(f"  Wrote: {file_path}")

        click.echo()

    # Summary
    click.echo(click.style("─" * 50, fg="cyan"))
    if dry_run:
        click.echo(click.style("Dry run complete — no files written", fg="cyan"))
    else:
        click.echo(click.style(f"Wrote {len(written_files)} ISAAC record(s):", fg="green"))
        for path in written_files:
            click.echo(f"  {path}")


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
