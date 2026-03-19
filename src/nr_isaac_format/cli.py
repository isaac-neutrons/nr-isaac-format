"""
Command-line interface for nr-isaac-format.

Manifest-driven CLI for converting data-assembler output to ISAAC format.
Takes a YAML manifest file describing a sample and its measurements,
runs each measurement through the data-assembler pipeline, and writes
one ISAAC AI-Ready Record per measurement.

Also provides commands for pushing records to the ISAAC Portal API.
"""

import json
import os
import sys
from pathlib import Path
from typing import Optional

import click
import httpx
from dotenv import load_dotenv

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
    import yaml
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

    # Load raw YAML to extract extra fields not in ManifestMeasurement
    with open(manifest) as f:
        raw_yaml = yaml.safe_load(f)
    raw_measurements = raw_yaml.get("measurements", [])

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

    # Sample-level fields from raw YAML
    raw_sample = raw_yaml.get("sample", {})
    sample_name: str | None = raw_sample.get("description")
    sample_formula: str | None = raw_sample.get("material")

    sample_id: Optional[str] = None
    written_files: list[Path] = []

    for i, measurement in enumerate(manifest_data.measurements):
        step = f"[{i + 1}/{len(manifest_data.measurements)}]"
        click.echo(click.style(f"{step} {measurement.name}", fg="cyan"))

        # Extract extra fields from raw YAML that ManifestMeasurement drops
        raw_m = raw_measurements[i] if i < len(raw_measurements) else {}
        m_context: str | None = raw_m.get("context")
        m_raw: str | None = raw_m.get("raw")

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
                click.echo(click.style(f"  Error parsing parquet files: {e}", fg="red"), err=True)
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
                click.echo(click.style(f"  Error parsing model file: {e}", fg="red"), err=True)
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
                f"  Sample: {result.sample.get('description', 'unknown')} ({sample_id[:8]}...)"
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
            context_description=m_context,
            raw_file_path=m_raw,
            sample_name=sample_name,
            sample_formula=sample_formula,
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


def _find_latest_schema(schema_dir: Path) -> Path | None:
    """Find the latest bundled schema file, preferring ornl-rev variants."""
    import re

    best_path: Path | None = None
    best_rev = -1

    for f in schema_dir.glob("isaac_record_v*-ornl-rev*.json"):
        m = re.search(r"-ornl-rev(\d+)\.json$", f.name)
        if m:
            rev = int(m.group(1))
            if rev > best_rev:
                best_rev = rev
                best_path = f

    if best_path:
        return best_path

    # Fall back to the original schema file
    fallback = schema_dir / "isaac_record_v1.json"
    return fallback if fallback.exists() else None


@main.command()
@click.argument("file", type=click.Path(exists=True, path_type=Path))
def validate(file: Path) -> None:
    """Validate an ISAAC record against the schema."""
    import jsonschema

    # Load bundled schema — prefer ornl-rev schema if available
    schema_dir = Path(__file__).parent / "schema"
    schema_path = _find_latest_schema(schema_dir)
    if not schema_path:
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


# ---------------------------------------------------------------------------
# Helper: resolve ISAAC credentials from env / options
# ---------------------------------------------------------------------------


def _resolve_credentials(url: Optional[str], token: Optional[str]) -> tuple[str, str]:
    """Return (base_url, api_token), loading .env if needed."""
    load_dotenv()  # loads .env from cwd (or parents) if present

    base_url = url or os.environ.get("ISAAC_URL", "")
    api_token = token or os.environ.get("ISAAC_KEY", "")

    if not base_url:
        click.echo(
            click.style(
                "Error: No API URL. Set ISAAC_URL in .env or pass --url.",
                fg="red",
            ),
            err=True,
        )
        sys.exit(1)

    if not api_token:
        click.echo(
            click.style(
                "Error: No API token. Set ISAAC_KEY in .env or pass --token.",
                fg="red",
            ),
            err=True,
        )
        sys.exit(1)

    return base_url, api_token


def _collect_json_files(paths: tuple[str, ...]) -> list[Path]:
    """Expand CLI paths/directories into a sorted list of JSON file paths."""
    files: list[Path] = []
    for p in paths:
        path = Path(p)
        if path.is_dir():
            files.extend(sorted(path.glob("*.json")))
        elif path.is_file():
            files.append(path)
        else:
            click.echo(
                click.style(f"Warning: skipping {p} (not found)", fg="yellow"),
                err=True,
            )
    return files


# ---------------------------------------------------------------------------
# push command
# ---------------------------------------------------------------------------


@main.command()
@click.argument("paths", nargs=-1, required=True)
@click.option(
    "--validate-only",
    is_flag=True,
    help="Validate records against the remote API without persisting.",
)
@click.option("--url", default=None, help="Override ISAAC_URL from .env.")
@click.option("--token", default=None, help="Override ISAAC_KEY from .env.")
def push(
    paths: tuple[str, ...], validate_only: bool, url: Optional[str], token: Optional[str]
) -> None:
    """Push ISAAC record JSON files to the ISAAC Portal API.

    PATHS can be one or more JSON files or directories containing JSON files.

    \b
    Examples:
        nr-isaac-format push output/
        nr-isaac-format push output/isaac_record_218386.json
        nr-isaac-format push output/ --validate-only
        nr-isaac-format push output/ --token my-secret-key
    """
    from .client import IsaacClient, IsaacAuthError, IsaacValidationError, IsaacAPIError

    base_url, api_token = _resolve_credentials(url, token)
    files = _collect_json_files(paths)

    if not files:
        click.echo(click.style("No JSON files found in the given paths.", fg="yellow"), err=True)
        sys.exit(1)

    mode = "Validating" if validate_only else "Pushing"
    click.echo(click.style(f"{mode} {len(files)} record(s) → {base_url}", fg="cyan", bold=True))
    click.echo()

    succeeded = 0
    failed = 0

    with IsaacClient(base_url, api_token) as client:
        for file_path in files:
            label = file_path.name
            try:
                with open(file_path) as f:
                    record = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                click.echo(click.style(f"  ✗ {label}: {e}", fg="red"), err=True)
                failed += 1
                continue

            try:
                if validate_only:
                    result = client.validate(record)
                    if result.get("valid"):
                        click.echo(click.style(f"  ✓ {label}: valid", fg="green"))
                        succeeded += 1
                    else:
                        click.echo(click.style(f"  ✗ {label}: validation failed", fg="red"))
                        for err in result.get("schema_errors", []):
                            click.echo(f"      schema: {err}", err=True)
                        for err in result.get("vocabulary_errors", []):
                            msg = err.get("message", err) if isinstance(err, dict) else err
                            click.echo(f"      vocab:  {msg}", err=True)
                        failed += 1
                else:
                    result = client.create(record)
                    rid = result.get("record_id", "?")
                    click.echo(click.style(f"  ✓ {label}: created (record_id={rid})", fg="green"))
                    succeeded += 1

            except IsaacAuthError as e:
                click.echo(
                    click.style(f"  ✗ Authentication error: {e.detail}", fg="red"),
                    err=True,
                )
                click.echo("Aborting — check your ISAAC_KEY.", err=True)
                sys.exit(1)

            except IsaacValidationError as e:
                click.echo(click.style(f"  ✗ {label}: validation failed", fg="red"))
                for err in e.schema_errors:
                    click.echo(f"      schema: {err}", err=True)
                for err in e.vocabulary_errors:
                    msg = err.get("message", err) if isinstance(err, dict) else err
                    click.echo(f"      vocab:  {msg}", err=True)
                failed += 1

            except IsaacAPIError as e:
                click.echo(click.style(f"  ✗ {label}: {e}", fg="red"), err=True)
                failed += 1

            except httpx.HTTPError as e:
                click.echo(click.style(f"  ✗ {label}: network error — {e}", fg="red"), err=True)
                failed += 1

    # Summary
    click.echo()
    click.echo(click.style("─" * 50, fg="cyan"))
    action = "validated" if validate_only else "pushed"
    if failed == 0:
        click.echo(click.style(f"All {succeeded} record(s) {action} successfully.", fg="green"))
    else:
        click.echo(
            click.style(
                f"{succeeded} succeeded, {failed} failed.", fg="yellow" if succeeded else "red"
            )
        )
        sys.exit(1)


# ---------------------------------------------------------------------------
# health command
# ---------------------------------------------------------------------------


@main.command()
@click.option("--url", default=None, help="Override ISAAC_URL from .env.")
@click.option("--token", default=None, help="Override ISAAC_KEY from .env.")
def health(url: Optional[str], token: Optional[str]) -> None:
    """Check connectivity to the ISAAC Portal API."""
    from .client import IsaacClient, IsaacAPIError

    base_url, api_token = _resolve_credentials(url, token)

    try:
        with IsaacClient(base_url, api_token) as client:
            result = client.health()
            status = result.get("status", "unknown")
            click.echo(click.style(f"✓ API healthy (status={status})", fg="green"))
    except IsaacAPIError as e:
        click.echo(click.style(f"✗ API error: {e}", fg="red"), err=True)
        sys.exit(1)
    except httpx.HTTPError as e:
        click.echo(click.style(f"✗ Connection failed: {e}", fg="red"), err=True)
        sys.exit(1)


# ---------------------------------------------------------------------------
# fetch-schema command
# ---------------------------------------------------------------------------


def _extract_schema_version(schema: dict) -> str:
    """Extract the major schema version number from a schema dict.

    Looks for a top-level ``version`` key first, then parses the ``title``
    field for a pattern like ``v1.0``.

    Returns:
        Version string (e.g. ``"1"``).
    """
    import re

    # Prefer explicit version field
    version = schema.get("version")
    if version:
        # Take the major part: "1.0" → "1", "2" → "2"
        return str(version).split(".")[0]

    # Fall back to title parsing
    title = schema.get("title", "")
    match = re.search(r"v(\d+)", title, re.IGNORECASE)
    if match:
        return match.group(1)

    return "unknown"


def _next_revision(
    schema_dir: Path, version: str, prefix: str = "isaac_record"
) -> int:
    """Determine the next revision number for a given version.

    Scans *schema_dir* for files matching
    ``<prefix>_v<version>-ornl-rev<N>.json`` and returns ``max(N) + 1``.
    Returns ``1`` when no prior revisions exist.
    """
    import re

    pattern = re.compile(
        rf"^{re.escape(prefix)}_v{re.escape(version)}-ornl-rev(\d+)\.json$"
    )
    max_rev = 0
    if schema_dir.is_dir():
        for f in schema_dir.iterdir():
            m = pattern.match(f.name)
            if m:
                max_rev = max(max_rev, int(m.group(1)))
    return max_rev + 1


@main.command("fetch-schema")
@click.option("--url", default=None, help="Override ISAAC_URL from .env.")
@click.option("--token", default=None, help="Override ISAAC_KEY from .env.")
def fetch_schema(url: Optional[str], token: Optional[str]) -> None:
    """Fetch the latest ISAAC schema from the Portal API and save it locally.

    The schema is saved to
    src/nr_isaac_format/schema/isaac_record_v<N>-ornl-rev<M>.json
    where N is the schema version and M is an auto-incremented local revision.

    If the fetched schema is identical to the latest local revision, no new
    file is written.
    """
    from .client import IsaacAPIError, IsaacClient

    base_url, api_token = _resolve_credentials(url, token)
    schema_dir = Path(__file__).parent / "schema"
    schema_dir.mkdir(parents=True, exist_ok=True)

    try:
        with IsaacClient(base_url, api_token) as client:
            schema = client.get_schema()
    except IsaacAPIError as e:
        click.echo(click.style(f"✗ API error: {e}", fg="red"), err=True)
        sys.exit(1)
    except httpx.HTTPError as e:
        click.echo(click.style(f"✗ Connection failed: {e}", fg="red"), err=True)
        sys.exit(1)

    version = _extract_schema_version(schema)
    if version == "unknown":
        click.echo(
            click.style("Warning: could not detect schema version; using 'unknown'", fg="yellow"),
            err=True,
        )

    next_rev = _next_revision(schema_dir, version)
    new_content = json.dumps(schema, indent=2) + "\n"

    # Check if the content matches the latest existing revision
    if next_rev > 1:
        prev_file = schema_dir / f"isaac_record_v{version}-ornl-rev{next_rev - 1}.json"
        if prev_file.exists():
            existing = prev_file.read_text()
            if existing == new_content:
                click.echo(
                    click.style(
                        f"Schema unchanged (matches rev {next_rev - 1})",
                        fg="cyan",
                    )
                )
                return

    out_path = schema_dir / f"isaac_record_v{version}-ornl-rev{next_rev}.json"
    out_path.write_text(new_content)
    click.echo(
        click.style(
            f"✓ Saved schema v{version} rev {next_rev} → {out_path}",
            fg="green",
        )
    )


# ---------------------------------------------------------------------------
# fetch-ontology command
# ---------------------------------------------------------------------------


@main.command("fetch-ontology")
@click.option("--url", default=None, help="Override ISAAC_URL from .env.")
@click.option("--token", default=None, help="Override ISAAC_KEY from .env.")
def fetch_ontology(url: Optional[str], token: Optional[str]) -> None:
    """Fetch the ISAAC ontology from the Portal API and save it locally.

    The ontology is saved to
    src/nr_isaac_format/schema/isaac_ontology_v<N>-ornl-rev<M>.json
    where N is the schema version and M is an auto-incremented local revision.

    If the fetched ontology is identical to the latest local revision, no new
    file is written.
    """
    from .client import IsaacAPIError, IsaacClient

    base_url, api_token = _resolve_credentials(url, token)
    schema_dir = Path(__file__).parent / "schema"
    schema_dir.mkdir(parents=True, exist_ok=True)

    try:
        with IsaacClient(base_url, api_token) as client:
            ontology = client.get_ontology()
    except IsaacAPIError as e:
        click.echo(click.style(f"✗ API error: {e}", fg="red"), err=True)
        sys.exit(1)
    except httpx.HTTPError as e:
        click.echo(click.style(f"✗ Connection failed: {e}", fg="red"), err=True)
        sys.exit(1)

    version = _extract_schema_version(ontology)
    if version == "unknown":
        click.echo(
            click.style(
                "Warning: could not detect ontology version; using 'unknown'", fg="yellow"
            ),
            err=True,
        )

    prefix = "isaac_ontology"
    next_rev = _next_revision(schema_dir, version, prefix=prefix)
    new_content = json.dumps(ontology, indent=2) + "\n"

    # Check if the content matches the latest existing revision
    if next_rev > 1:
        prev_file = schema_dir / f"{prefix}_v{version}-ornl-rev{next_rev - 1}.json"
        if prev_file.exists():
            existing = prev_file.read_text()
            if existing == new_content:
                click.echo(
                    click.style(
                        f"Ontology unchanged (matches rev {next_rev - 1})",
                        fg="cyan",
                    )
                )
                return

    out_path = schema_dir / f"{prefix}_v{version}-ornl-rev{next_rev}.json"
    out_path.write_text(new_content)
    click.echo(
        click.style(
            f"✓ Saved ontology v{version} rev {next_rev} → {out_path}",
            fg="green",
        )
    )


# ---------------------------------------------------------------------------
# Schema migration helpers
# ---------------------------------------------------------------------------

# Mapping of rev1 descriptor source values to rev2 enum values
_DESCRIPTOR_SOURCE_MAP = {
    "computed": "auto",
    "metadata": "auto",
}


def _migrate_record_to_rev2(record: dict) -> bool:
    """Migrate an ISAAC record from rev1 schema to rev2 in-place.

    Applies all structural changes required by v1-ornl-rev2:
    - Removes ``acquisition_source``, adds top-level ``source_type``
    - Remaps descriptor ``source`` values to rev2 enum
    - Adds ``system.technique`` and removes freeform config keys
    - Removes ``system.configuration`` freeform keys not in rev2 enum

    Returns True if any changes were made, False if already rev2-compatible.
    """
    changed = False

    # 1. acquisition_source → source_type
    if "acquisition_source" in record:
        acq = record.pop("acquisition_source")
        if "source_type" not in record:
            record["source_type"] = acq.get("source_type", "facility")
        changed = True
    elif "source_type" not in record:
        record["source_type"] = "facility"
        changed = True

    # 2. Descriptor source values
    for output in record.get("descriptors", {}).get("outputs", []):
        for desc in output.get("descriptors", []):
            old_src = desc.get("source", "")
            new_src = _DESCRIPTOR_SOURCE_MAP.get(old_src)
            if new_src:
                desc["source"] = new_src
                changed = True

    # 3. system.technique + clean configuration
    system = record.get("system")
    if system:
        if "technique" not in system:
            system["technique"] = "neutron_reflectometry"
            changed = True
        config = system.get("configuration")
        if config:
            # Remove the entire configuration block — rev2 restricts keys
            # and our freeform keys (measurement_geometry, probe, technique)
            # are not in the allowed enum
            del system["configuration"]
            changed = True

    return changed


# ---------------------------------------------------------------------------
# update command
# ---------------------------------------------------------------------------


def _next_record_version(file_path: Path) -> Path:
    """Return the next versioned path for an ISAAC record file.

    Given ``isaac_record_218386.json``, scans siblings for
    ``isaac_record_218386_v*.json`` and returns the next available path.
    The original file (no ``_vN`` suffix) is considered v1.
    """
    import re

    stem = file_path.stem  # e.g. "isaac_record_218386" or "isaac_record_218386_v2"
    # Strip any existing _vN suffix to get the base stem
    base_stem = re.sub(r"_v\d+$", "", stem)
    parent = file_path.parent

    max_ver = 1  # original file is implicitly v1
    pattern = re.compile(rf"^{re.escape(base_stem)}_v(\d+)\.json$")
    for f in parent.iterdir():
        m = pattern.match(f.name)
        if m:
            max_ver = max(max_ver, int(m.group(1)))

    return parent / f"{base_stem}_v{max_ver + 1}.json"


def _find_existing_record_id(
    output_dir: Path, run_number: str
) -> tuple[str | None, Path | None]:
    """Look for an existing ISAAC record for a run number and return its record_id.

    Checks for ``isaac_record_<run>.json`` first (original), then falls back
    to the highest ``_vN`` variant.  Returns ``(record_id, path)`` or
    ``(None, None)`` when no match is found.
    """
    import re

    base = f"isaac_record_{run_number}"

    # Try original file first
    original = output_dir / f"{base}.json"
    if original.is_file():
        with open(original) as f:
            record = json.load(f)
        return record.get("record_id"), original

    # Fall back to latest versioned file
    best_ver = 0
    best_path: Path | None = None
    pattern = re.compile(rf"^{re.escape(base)}_v(\d+)\.json$")
    for f in output_dir.iterdir():
        m = pattern.match(f.name)
        if m:
            ver = int(m.group(1))
            if ver > best_ver:
                best_ver = ver
                best_path = f

    if best_path:
        with open(best_path) as fh:
            record = json.load(fh)
        return record.get("record_id"), best_path

    return None, None


@main.command()
@click.argument("manifest", type=click.Path(exists=True, path_type=Path))
@click.option("--compact", is_flag=True, help="Output compact JSON (no indentation)")
@click.option("--dry-run", is_flag=True, help="Parse and assemble but don't write output")
def update(manifest: Path, compact: bool, dry_run: bool) -> None:
    """Regenerate ISAAC records from a manifest using the latest writer and schema.

    Re-runs the full data-assembler pipeline for each measurement in MANIFEST
    and writes new versioned copies.  If an existing record is found in the
    output directory, its record_id is preserved so that external references
    remain valid.  Originals are never overwritten.

    \b
    Examples:
        nr-isaac-format update expt_34347.yaml
        nr-isaac-format update expt_34347.yaml --dry-run
    """
    import yaml
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

    # Load raw YAML to extract extra fields not in ManifestMeasurement
    with open(manifest) as f:
        raw_yaml = yaml.safe_load(f)
    raw_measurements = raw_yaml.get("measurements", [])

    # Validate
    errors = manifest_data.validate()
    if errors:
        click.echo(click.style("Manifest validation errors:", fg="red"), err=True)
        for error in errors:
            click.echo(f"  - {error}", err=True)
        sys.exit(1)

    title = manifest_data.title or manifest.stem
    output_path = Path(manifest_data.output)

    click.echo(click.style(f"Updating: {title}", fg="cyan", bold=True))
    click.echo(f"  Output: {output_path}")
    click.echo(f"  Measurements: {len(manifest_data.measurements)}")
    click.echo()

    reduced_parser = ReducedParser()
    parquet_parser = ParquetParser()
    model_parser = ModelParser()
    assembler = DataAssembler()

    # Sample-level fields from raw YAML
    raw_sample = raw_yaml.get("sample", {})
    sample_name: str | None = raw_sample.get("description")
    sample_formula: str | None = raw_sample.get("material")

    sample_id: Optional[str] = None
    written_files: list[Path] = []

    for i, measurement in enumerate(manifest_data.measurements):
        step = f"[{i + 1}/{len(manifest_data.measurements)}]"
        click.echo(click.style(f"{step} {measurement.name}", fg="cyan"))

        # Extract extra fields from raw YAML that ManifestMeasurement drops
        raw_m = raw_measurements[i] if i < len(raw_measurements) else {}
        m_context: str | None = raw_m.get("context")
        m_raw: str | None = raw_m.get("raw")

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
                f"  Sample: {result.sample.get('description', 'unknown')} ({sample_id[:8]}...)"
            )
        elif sample_id:
            click.echo(f"  Sample: {sample_id[:8]}... (reused)")

        # Determine run number for file naming and record_id lookup
        run_number_str = (
            str(result.reflectivity.get("run_number"))
            if result.reflectivity and result.reflectivity.get("run_number")
            else None
        )

        # Look for existing record to preserve record_id
        existing_id: str | None = None
        existing_path: Path | None = None
        if run_number_str and output_path.is_dir():
            existing_id, existing_path = _find_existing_record_id(output_path, run_number_str)

        if existing_id:
            click.echo(f"  Preserving record_id from {existing_path.name}")

        # Generate record with latest writer
        writer = IsaacWriter()
        record = writer.to_isaac(
            result,
            environment_description=measurement.environment,
            context_description=m_context,
            raw_file_path=m_raw,
            sample_name=sample_name,
            sample_formula=sample_formula,
            record_id=existing_id,
        )

        if dry_run:
            click.echo(click.style("  (dry run — not written)", fg="cyan"))
        else:
            output_path.mkdir(parents=True, exist_ok=True)

            if existing_path:
                # Write as next version alongside the original
                file_path = _next_record_version(existing_path)
            else:
                # No existing record — write new file
                if run_number_str:
                    filename = f"isaac_record_{run_number_str}.json"
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
        click.echo(click.style(f"Updated {len(written_files)} ISAAC record(s):", fg="green"))
        for path in written_files:
            click.echo(f"  {path}")


# ---------------------------------------------------------------------------
# migrate command
# ---------------------------------------------------------------------------


@main.command()
@click.argument("paths", nargs=-1, required=True)
def migrate(paths: tuple[str, ...]) -> None:
    """Migrate ISAAC records to the latest schema revision (v1-ornl-rev2).

    Lightweight schema-only migration: applies structural changes (removes
    acquisition_source, fixes descriptor sources, adds system.technique, etc.)
    without re-running the data pipeline.  Use this when the original data
    files are not available; prefer ``update`` for a full regeneration.

    Writes a new versioned copy — the original file is never overwritten.

    \b
    Examples:
        nr-isaac-format migrate output/
        nr-isaac-format migrate output/isaac_record_218386.json
    """
    files = _collect_json_files(paths)
    if not files:
        click.echo(click.style("No JSON files found in the given paths.", fg="yellow"), err=True)
        sys.exit(1)

    click.echo(
        click.style(f"Migrating {len(files)} record(s) to rev2 schema", fg="cyan", bold=True)
    )
    click.echo()

    migrated = 0
    skipped = 0

    for file_path in files:
        label = file_path.name
        try:
            with open(file_path) as f:
                record = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            click.echo(click.style(f"  ✗ {label}: {e}", fg="red"), err=True)
            continue

        if not _migrate_record_to_rev2(record):
            click.echo(click.style(f"  – {label}: already rev2-compatible", fg="yellow"))
            skipped += 1
            continue

        out_path = _next_record_version(file_path)
        with open(out_path, "w") as f:
            json.dump(record, f, indent=2, default=str)

        click.echo(click.style(f"  ✓ {label} → {out_path.name}", fg="green"))
        migrated += 1

    click.echo()
    click.echo(click.style("─" * 50, fg="cyan"))
    if migrated:
        click.echo(click.style(f"Migrated {migrated} record(s).", fg="green"))
    if skipped:
        click.echo(click.style(f"Skipped {skipped} record(s) (already rev2).", fg="yellow"))


if __name__ == "__main__":
    main()
