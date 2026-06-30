"""
Command-line interface for nr-isaac-format.

Manifest-driven CLI for converting data-assembler output to ISAAC format.
Takes a YAML manifest file describing a sample and its measurements,
runs each measurement through the data-assembler pipeline, and writes
one ISAAC AI-Ready Record per measurement.

Also provides commands for pushing records to the ISAAC Portal API.
"""

import inspect
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


class _FullHelpCommand(click.Command):
    """A command that keeps its full one-line summary in the parent group's
    command listing, instead of truncating it with an ellipsis.

    Click derives the listing's short help from the docstring and clips it to
    a width-derived limit. We override that to return the complete first
    paragraph; the help formatter wraps long lines rather than dropping text.
    """

    def get_short_help_str(self, limit: int = 45) -> str:
        if self.short_help:
            return inspect.cleandoc(self.short_help).strip()
        if self.help:
            first_paragraph = inspect.cleandoc(self.help).split("\n\n", 1)[0]
            return " ".join(first_paragraph.split())
        return ""


class _FullHelpGroup(click.Group):
    """A group whose subcommands keep their full short help (no ellipsis)."""

    command_class = _FullHelpCommand


# Let help text use the full terminal width (up to 120 cols) instead of
# Click's default 80-column cap, which forces aggressive wrapping/truncation.
_CONTEXT_SETTINGS = {"max_content_width": 120}


@click.group(cls=_FullHelpGroup, context_settings=_CONTEXT_SETTINGS)
@click.version_option(version=__version__)
def main() -> None:
    """
    NR-ISAAC Format Writer.

    Convert neutron reflectometry data to ISAAC AI-Ready Record format
    using a YAML manifest file.
    """
    pass


def _convert_plan(
    plan: dict,
    output_dir: Path,
    data_dir: Path,
    compact: bool,
    dry_run: bool,
) -> list[Path]:
    """Convert a pre-fit ``plan.yaml`` (describe/states/...) to ISAAC records.

    Each ``state`` becomes one record built from its primary reduced data file
    (the first entry in ``state.data``, resolved against *data_dir*). A plan is
    pre-fit, so no model is assembled: the reflectivity curve, the sample
    ``describe`` text (→ ``sample.material.notes``) and the per-state
    ``extra_description`` (→ ``measurement.series[].notes`` + parsed potential)
    are recorded.
    """
    from assembler.parsers import ReducedParser
    from assembler.workflow import DataAssembler

    describe = plan.get("describe")
    states = plan.get("states") or []
    if not states:
        raise click.ClickException("Plan has no 'states' to convert.")

    reduced_parser = ReducedParser()
    assembler = DataAssembler()
    written: list[Path] = []
    sample_id: Optional[str] = None

    for i, state in enumerate(states):
        name = state.get("name") or f"state_{i + 1}"
        click.echo(click.style(f"[{i + 1}/{len(states)}] {name}", fg="cyan"))

        data_files = state.get("data") or []
        if not data_files:
            raise click.ClickException(f"State '{name}' has no data files.")

        # A state's data files are partial Q-ranges of one measurement; use the
        # first (primary) partial as the reduced curve, mirroring the manifest flow.
        reduced_path = data_dir / data_files[0]
        if not reduced_path.is_file():
            raise click.ClickException(f"Data file not found: {reduced_path}")
        if len(data_files) > 1:
            click.echo(
                click.style(
                    f"  Note: {len(data_files)} partial files listed; using primary "
                    f"{reduced_path.name} (siblings not merged).",
                    fg="yellow",
                )
            )

        extra = state.get("extra_description")
        try:
            reduced_data = reduced_parser.parse(str(reduced_path))
        except Exception as e:
            raise click.ClickException(f"Error parsing reduced file {reduced_path}: {e}")

        result = assembler.assemble(
            reduced=reduced_data,
            model=None,
            environment_description=extra,
            sample_id=sample_id,
        )
        if result.has_errors:
            for error in result.errors:
                click.echo(click.style(f"    - {error}", fg="red"), err=True)
            raise click.ClickException(f"Assembly failed for state '{name}'.")
        for warning in result.warnings:
            click.echo(click.style(f"  Warning: {warning}", fg="yellow"), err=True)

        if i == 0 and result.sample:
            sample_id = result.sample.get("id")

        # The plan declares back-reflection geometry; surface it for descriptors.
        # (The assembler leaves measurement_geometry as None without a model.)
        if state.get("back_reflection") and result.reflectivity is not None:
            if not result.reflectivity.get("measurement_geometry"):
                result.reflectivity["measurement_geometry"] = "back reflection"

        refl = result.reflectivity or {}
        run_number = refl.get("run_number")
        click.echo(f"  Reflectivity: run {run_number}, {len(refl.get('q', []))} Q points")

        record = IsaacWriter().to_isaac(
            result,
            context_description=extra,
            sample_name=describe,
        )

        if dry_run:
            click.echo(click.style("  (dry run — not written)", fg="cyan"))
            click.echo()
            continue

        output_dir.mkdir(parents=True, exist_ok=True)
        if run_number:
            filename = f"isaac_record_{run_number}.json"
        else:
            safe = name.lower().replace(" ", "_")
            filename = f"isaac_record_{i + 1:02d}_{safe}.json"
        file_path = output_dir / filename
        with open(file_path, "w") as f:
            json.dump(record, f, indent=None if compact else 2, default=str)
        written.append(file_path)
        click.echo(f"  Wrote: {file_path}")
        click.echo()

    return written


@main.command()
@click.argument("input_file", type=click.Path(exists=True, path_type=Path))
@click.option(
    "-o",
    "--output",
    "output_dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Output directory for ISAAC records. Required for a plan.yaml; "
    "overrides a manifest's `output:` field when given.",
)
@click.option(
    "-d",
    "--data-dir",
    "data_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Directory holding the reduced data files. Required for a plan.yaml.",
)
@click.option("--compact", is_flag=True, help="Output compact JSON (no indentation)")
@click.option("--dry-run", is_flag=True, help="Parse and assemble but don't write output")
def convert(
    input_file: Path,
    output_dir: Path | None,
    data_dir: Path | None,
    compact: bool,
    dry_run: bool,
) -> None:
    """Convert a manifest.yaml or a plan.yaml to ISAAC AI-Ready Records.

    Manual/standalone route: builds a record directly from raw files. The
    canonical pipeline route is ``convert-ingest`` (fed by the data-assembler),
    which carries fit uncertainties, χ², and structured conditions; the manifest
    is no longer the pipeline handoff.

    INPUT_FILE is either a fitted-result *manifest* (sample + measurements with
    models) or a pre-fit *plan* (describe + states). The format is detected
    automatically. Each measurement/state produces one ISAAC record.

    Example:

        nr-isaac-format convert expt_34347.yaml
        nr-isaac-format convert plan/job_230539.yaml -d Rawdata/ -o records/

    \b
    Manifest format:
        title: "Experiment title"
        sample:
          description: "Sample description"
          model: /path/to/model.json
        output: /path/to/output/
        measurements:
          - name: "Measurement 1"
            reduced: /path/to/reduced.txt
            environment: "Description text"  # optional

    \b
    Plan format (pre-fit; needs -d for data and -o for output):
        describe: "Sample stack description"
        states:
          - name: run_230539
            data: [REFL_230539_1_230539_partial.txt, ...]
            back_reflection: true
            extra_description: "OCV measurement in D2O electrolyte, ..."
    """
    import yaml

    raw_yaml = yaml.safe_load(input_file.read_text())
    if not isinstance(raw_yaml, dict):
        click.echo(click.style(f"Error: {input_file} is not a YAML mapping.", fg="red"), err=True)
        sys.exit(1)

    # --- plan.yaml path (pre-fit: describe + states[]) ---
    if "states" in raw_yaml:
        if data_dir is None:
            raise click.UsageError(
                "A plan file requires -d/--data-dir (the directory holding the reduced data files)."
            )
        if output_dir is None:
            raise click.UsageError("A plan file requires -o/--output (the output directory).")

        title = raw_yaml.get("describe") or input_file.stem
        click.echo(click.style(f"Converting plan: {title}", fg="cyan", bold=True))
        click.echo(f"  Data dir: {data_dir}")
        click.echo(f"  Output: {output_dir}")
        click.echo(f"  States: {len(raw_yaml.get('states') or [])}")
        click.echo()

        written = _convert_plan(raw_yaml, output_dir, data_dir, compact, dry_run)

        click.echo(click.style("─" * 50, fg="cyan"))
        if dry_run:
            click.echo(click.style("Dry run complete — no files written", fg="cyan"))
        else:
            click.echo(click.style(f"Wrote {len(written)} ISAAC record(s):", fg="green"))
            for path in written:
                click.echo(f"  {path}")
        return

    # --- manifest.yaml path ---
    from assembler.parsers import ManifestParser, ModelParser, ParquetParser, ReducedParser
    from assembler.tools.detection import extract_run_number
    from assembler.workflow import DataAssembler

    # Parse manifest
    parser = ManifestParser()
    try:
        manifest_data = parser.parse(input_file)
    except Exception as e:
        click.echo(click.style(f"Error parsing manifest: {e}", fg="red"), err=True)
        sys.exit(1)

    raw_measurements = raw_yaml.get("measurements", [])

    # Validate
    errors = manifest_data.validate()
    if errors:
        click.echo(click.style("Manifest validation errors:", fg="red"), err=True)
        for error in errors:
            click.echo(f"  - {error}", err=True)
        sys.exit(1)

    # -o overrides the manifest's own output directory when supplied.
    output_path = output_dir or Path(manifest_data.output)

    title = manifest_data.title or input_file.stem
    click.echo(click.style(f"Converting: {title}", fg="cyan", bold=True))
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
            refl_data = result.reflectivity
            q = refl_data.get("q", [])
            run_number = refl_data.get("run_number")
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


# ---------------------------------------------------------------------------
# plan-to-manifest command
# ---------------------------------------------------------------------------


def _build_manifest_from_plan(
    plan: dict,
    plan_path: Path,
    data_dir: Path | None,
    records_dir: str,
) -> tuple[str, dict, list[str]]:
    """Build a ``manifest.yaml`` document from a pre-fit ``plan.yaml``.

    Each plan ``state`` becomes one manifest ``measurement`` under a single
    shared sample, so the measurements stay grouped as one sample's history.
    When the manifest is converted, the assembler builds the sample once from
    the first measurement and reuses that sample identity for the rest, rather
    than treating each state as an unrelated one-off as separate conversions
    would. (The reused identity is internal to assembly; the records carry the
    same sample description, not a record-level id.)

    The plan is pre-fit, so no layer model is attached; a header comment shows
    where to add one after fitting. Field mapping (mirroring ``_convert_plan``):

    - ``describe`` → ``sample.description``
    - ``state.name`` → ``measurement.name``
    - ``state.data[0]`` → ``measurement.reduced`` (primary partial, resolved
      against *data_dir*; siblings are noted, not merged)
    - ``state.extra_description`` → ``measurement.environment`` (classified) and
      ``measurement.context`` (free-text notes), matching how the plan path
      feeds the same text to both the assembler and the writer
    - ``state.back_reflection`` → folded into ``measurement.context`` as a
      geometry note (the manifest ``convert`` path has no structured slot, so
      this drops the structured ``measurement_geometry`` descriptor that
      ``convert <plan>`` would emit)
    - ``model_name`` / ``metadata.notes`` / any other plan-only state field
      (``theta_offset``, ``sample_broadening``, ``background``, …) → YAML comments

    Returns ``(yaml_text, manifest_dict, warnings)``.
    """
    import textwrap

    import yaml

    def _flat(value: object) -> str:
        """Collapse all whitespace (incl. newlines) so *value* is safe to drop
        into a single-line ``# `` comment without breaking out of it."""
        return " ".join(str(value).split())

    warnings: list[str] = []
    describe = plan.get("describe")
    states = plan.get("states") or []
    model_name = plan.get("model_name")
    title = model_name or plan_path.stem

    measurements: list[dict] = []
    measurement_comments: list[list[str]] = []  # parallel to measurements

    # State keys this command maps into the manifest; every other key is a
    # plan-only field with no manifest home and is preserved as a comment.
    mapped_state_keys = {"name", "data", "extra_description", "back_reflection"}

    for i, state in enumerate(states):
        if not isinstance(state, dict):
            raise click.ClickException(
                f"Plan state {i + 1} is not a mapping (got {type(state).__name__})."
            )
        name = state.get("name") or f"state_{i + 1}"
        data_files = state.get("data") or []
        measurement: dict = {"name": name}
        comments: list[str] = []

        if data_files:
            primary = data_files[0]
            if data_dir is not None:
                resolved = (data_dir / primary).resolve()
                if not resolved.is_file():
                    warnings.append(f"State '{name}': data file not found: {resolved}")
                measurement["reduced"] = str(resolved)
            else:
                measurement["reduced"] = primary
            if len(data_files) > 1:
                siblings = _flat(", ".join(str(s) for s in data_files[1:]))
                comments.append(
                    f"primary reduced is data[0]; {len(data_files) - 1} sibling "
                    f"partial(s) not merged: {siblings}"
                )
        else:
            warnings.append(f"State '{name}': no data files; 'reduced' left empty.")
            measurement["reduced"] = ""
            comments.append("plan state had no 'data'; set 'reduced' before converting")

        # extra_description feeds both fields, exactly as the plan conversion
        # does: environment (→ enum classification) and context (→ series notes).
        extra = state.get("extra_description")
        if extra:
            measurement["environment"] = extra

        context_parts: list[str] = []
        if extra:
            context_parts.append(extra)
        if state.get("back_reflection"):
            context_parts.append(
                "Measured in back-reflection geometry (beam enters from the substrate side)."
            )
        if context_parts:
            measurement["context"] = " ".join(context_parts)

        # Any other plan-only fields (theta_offset, sample_broadening,
        # background, …) have no manifest analog → preserve them verbatim as
        # comments. repr() keeps each on one line, so a newline in a value
        # cannot break out of the comment.
        for key, value in state.items():
            if key not in mapped_state_keys:
                comments.append(f"{key}: {value!r}  (plan-only; no manifest field)")

        measurements.append(measurement)
        measurement_comments.append(comments)

    manifest_dict: dict = {"title": title}
    sample: dict = {}
    if describe:
        sample["description"] = describe
    if sample:
        manifest_dict["sample"] = sample
    manifest_dict["output"] = records_dir
    manifest_dict["measurements"] = measurements

    # --- render: provenance header (comments) + clean body + inline comments ---
    lines: list[str] = [
        f"# Manifest generated by nr-isaac-format {__version__} (plan-to-manifest)",
        f"# Source plan: {plan_path}",
        "#",
        "# This plan is PRE-FIT: no layer model is attached. After fitting, add",
        "#   sample.model: /path/to/model.json   # (or a per-measurement `model:`)",
        "# and optionally sample.material, then run `nr-isaac-format convert <this file>`.",
    ]
    if model_name:
        lines += ["#", f"# Plan model_name: {_flat(model_name)}"]
    notes = (plan.get("metadata") or {}).get("notes")
    if notes:
        lines += ["#", "# Plan metadata.notes:"]
        for paragraph in str(notes).splitlines() or [str(notes)]:
            lines += [f"#   {line}" for line in (textwrap.wrap(paragraph, width=94) or [""])]

    dump = lambda obj: yaml.safe_dump(  # noqa: E731
        obj, sort_keys=False, allow_unicode=True, default_flow_style=False, width=4096
    ).rstrip("\n")

    top = {k: manifest_dict[k] for k in ("title", "sample", "output") if k in manifest_dict}
    lines += ["", *dump(top).split("\n"), "", "measurements:"]
    for measurement, comments in zip(measurements, measurement_comments):
        lines += [f"# {c}" for c in comments]
        lines += dump([measurement]).split("\n")

    yaml_text = "\n".join(lines) + "\n"

    # Self-check: the hand-composed document must round-trip to EXACTLY the
    # structure we intended. Comparing full content (not just the measurement
    # count) catches any comment/indent/escaping bug — including a stray newline
    # that would inject or corrupt a key.
    try:
        check = yaml.safe_load(yaml_text)
    except yaml.YAMLError as e:
        raise click.ClickException(f"internal error: generated manifest is not valid YAML ({e}).")
    if check != manifest_dict:
        raise click.ClickException("internal error: generated manifest failed its self-check.")

    return yaml_text, manifest_dict, warnings


@main.command("plan-to-manifest")
@click.argument("plan_file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "-o",
    "--output",
    "output",
    type=click.Path(path_type=Path),
    default=None,
    help="Manifest file to write, or a directory to write into. "
    "Defaults to <plan>_manifest.yaml beside the plan.",
)
@click.option(
    "-d",
    "--data-dir",
    "data_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=None,
    help="Directory holding the reduced data files; resolves the plan's bare "
    "filenames to absolute `reduced:` paths. Without it, filenames are kept verbatim.",
)
@click.option(
    "--records-dir",
    "records_dir",
    default="./output",
    show_default=True,
    help="Value for the manifest's required `output:` field (where `convert` "
    "will write the ISAAC records).",
)
@click.option("--force", is_flag=True, help="Overwrite the manifest file if it already exists.")
@click.option("--dry-run", is_flag=True, help="Print the manifest to stdout instead of writing.")
def plan_to_manifest(
    plan_file: Path,
    output: Path | None,
    data_dir: Path | None,
    records_dir: str,
    force: bool,
    dry_run: bool,
) -> None:
    """Create a manifest.yaml from a pre-fit plan.yaml.

    A plan's ``states`` become the manifest's ``measurements`` under one shared
    sample, so the link between measurements that belong together — and the
    sample's history — is preserved when the manifest is later converted: the
    first measurement creates the sample record and the rest reuse its id.
    Converting each state on its own instead would mint a fresh sample every
    time and lose that connection.

    PLAN_FILE is a pre-fit plan (``describe`` + ``states``). The output is a
    manifest skeleton — because the plan is pre-fit it has no model; add
    ``sample.model`` (or a per-measurement ``model:``) after fitting, then run
    ``nr-isaac-format convert <manifest>``.

    Example:

        nr-isaac-format plan-to-manifest plan/job_230539.yaml -d Rawdata/

    \b
    Mapping:
        describe                 → sample.description
        states[].name            → measurements[].name
        states[].data[0]         → measurements[].reduced (resolved against -d)
        states[].extra_description → measurements[].environment + .context
        states[].back_reflection → folded into measurements[].context (text)
    """
    import yaml

    raw = yaml.safe_load(plan_file.read_text())
    if not isinstance(raw, dict):
        raise click.ClickException(f"{plan_file} is not a YAML mapping.")
    if "states" not in raw:
        if "measurements" in raw:
            raise click.ClickException(
                f"{plan_file} looks like a manifest already (has 'measurements', not 'states')."
            )
        raise click.ClickException(f"{plan_file} has no 'states' — it is not a plan.")
    if not (raw.get("states") or []):
        raise click.ClickException(f"{plan_file} has an empty 'states' list — nothing to convert.")

    yaml_text, manifest_dict, warnings = _build_manifest_from_plan(
        raw, plan_file, data_dir, records_dir
    )

    for warning in warnings:
        click.echo(click.style(f"  Warning: {warning}", fg="yellow"), err=True)

    if dry_run:
        click.echo(yaml_text, nl=False)
        return

    # Resolve the output path: explicit file, a directory to write into, or the
    # default <plan>_manifest.yaml beside the plan.
    default_name = f"{plan_file.stem}_manifest.yaml"
    if output is None:
        out_path = plan_file.with_name(default_name)
    elif output.is_dir() or output.suffix == "":
        out_path = output / default_name
    else:
        out_path = output

    if out_path.exists() and not force:
        raise click.ClickException(f"{out_path} already exists — pass --force to overwrite.")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(yaml_text)

    n = len(manifest_dict["measurements"])
    click.echo(
        click.style(f"Wrote manifest with {n} measurement(s): {out_path}", fg="green")
    )
    click.echo(f"  Next: nr-isaac-format convert {out_path}")


# ---------------------------------------------------------------------------
# convert-ingest command
# ---------------------------------------------------------------------------


def _load_ingest_records(ingest_dir: Path) -> tuple[list[dict], dict, dict, dict | None]:
    """Load the raw records from a data-assembler ingest dir.

    Prefers JSON (written with ``--json``); falls back to Parquet. Loads ALL
    reflectivity records (a state has several angles) and ALL sample/environment
    records (a multi-state run has one of each per state), keyed by id, plus the
    single fit record. Handles both the flat single-state layout
    (``json/sample.json``) and the multi-state layout (``json/sample/<id>.json``).

    Returns ``(reflectivity_records, samples_by_id, envs_by_id, fit)``.
    """
    reflectivity_records: list[dict] = []
    samples: list[dict] = []
    environments: list[dict] = []
    fit: dict | None = None

    json_root = ingest_dir / "json"
    if json_root.is_dir():
        for m in sorted(json_root.rglob("reflectivity.json")):
            with open(m) as f:
                reflectivity_records.append(json.load(f))
        for m in sorted(json_root.rglob("sample.json")) + sorted(
            (json_root / "sample").glob("*.json")
        ):
            with open(m) as f:
                samples.append(json.load(f))
        for m in sorted(json_root.rglob("environment.json")) + sorted(
            (json_root / "environment").glob("*.json")
        ):
            with open(m) as f:
                environments.append(json.load(f))
        fm = sorted(json_root.rglob("reflectivity_model.json"))
        if fm:
            with open(fm[0]) as f:
                fit = json.load(f)

    # Parquet fallback (each table dir holds id-keyed *.parquet files).
    def _pq_all(table: str) -> list[dict]:
        import pyarrow.parquet as pq

        d = ingest_dir / table
        out: list[dict] = []
        for m in sorted(d.rglob("*.parquet")) if d.is_dir() else []:
            out.extend(pq.ParquetFile(str(m)).read().to_pylist())
        return out

    if not reflectivity_records:
        reflectivity_records = _pq_all("reflectivity")
    if not samples:
        samples = _pq_all("sample")
    if not environments:
        environments = _pq_all("environment")
    if fit is None:
        fits = _pq_all("reflectivity_model")
        fit = fits[0] if fits else None

    # Sort runs deterministically by run number (files are id-keyed on disk, so
    # disk order is arbitrary). This makes the per-state primary run the lowest
    # number and keeps series in ascending Q-segment order.
    def _run_sort_key(r: dict):
        rn = r.get("run_number")
        try:
            return (0, int(rn))
        except (TypeError, ValueError):
            return (1, str(rn))

    reflectivity_records.sort(key=_run_sort_key)

    samples_by_id = {s.get("id"): s for s in samples}
    envs_by_id = {e.get("id"): e for e in environments}
    return reflectivity_records, samples_by_id, envs_by_id, fit


def _assembly_result(reflectivity, additional, sample, environment, fit):
    """Build an AssemblyResult, tolerating an older data-assembler.

    The multi-run ``additional_reflectivities`` field only exists on the updated
    data-assembler. When running against an older one, construct with the base
    fields and attach the extras only if supported — degrading to single-series
    with a clear warning rather than crashing on an unexpected kwarg.
    """
    from assembler.workflow import AssemblyResult

    result = AssemblyResult(
        reflectivity=reflectivity,
        sample=sample,
        environment=environment,
        reflectivity_model=fit,
    )
    extra = [r for r in (additional or []) if r]
    if extra:
        if hasattr(result, "additional_reflectivities"):
            result.additional_reflectivities = list(extra)
        else:
            click.echo(
                click.style(
                    f"  Warning: the installed data-assembler predates multi-run "
                    f"support; {len(extra)} extra run(s) dropped (single series). "
                    f"Upgrade data-assembler for multi-angle / multi-state export.",
                    fg="yellow",
                ),
                err=True,
            )
    return result


def _load_assembly_from_ingest(ingest_dir: Path):
    """Reconstruct a single AssemblyResult from an ingest dir (all runs, one state).

    Loads every reflectivity record (a multi-angle state has several) plus the
    first sample/environment and the fit. For a multi-state dir use
    :func:`_load_states_from_ingest` to split per state instead.
    """
    reflectivity_records, samples_by_id, envs_by_id, fit = _load_ingest_records(ingest_dir)
    if not reflectivity_records:
        raise click.ClickException(
            f"No reflectivity output found in {ingest_dir} "
            "(looked for json/**/reflectivity.json and reflectivity/*.parquet)"
        )
    samples = list(samples_by_id.values())
    envs = list(envs_by_id.values())
    return _assembly_result(
        reflectivity=reflectivity_records[0],
        additional=reflectivity_records[1:],
        sample=samples[0] if samples else None,
        environment=envs[0] if envs else None,
        fit=fit,
    )


def _load_states_from_ingest(ingest_dir: Path) -> list:
    """Split an ingest dir into one AssemblyResult per state.

    A state is the set of runs sharing ``(sample_id, environment_id)`` — recovered
    entirely from the store's foreign keys (no manifest, no file-name parsing).
    Each result carries that state's runs (one series each downstream), its
    matching sample and environment, and the shared fit. Runs missing FKs fall
    into a single default group, preserving single-state behavior.
    """
    reflectivity_records, samples_by_id, envs_by_id, fit = _load_ingest_records(ingest_dir)
    if not reflectivity_records:
        raise click.ClickException(
            f"No reflectivity output found in {ingest_dir} "
            "(looked for json/**/reflectivity.json and reflectivity/*.parquet)"
        )

    # Group by (sample_id, environment_id), preserving first-seen order.
    groups: dict[tuple, list[dict]] = {}
    order: list[tuple] = []
    for refl in reflectivity_records:
        key = (refl.get("sample_id"), refl.get("environment_id"))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(refl)

    results = []
    for sid, eid in order:
        runs = groups[(sid, eid)]
        results.append(
            _assembly_result(
                reflectivity=runs[0],
                additional=runs[1:],
                sample=samples_by_id.get(sid) or (next(iter(samples_by_id.values()), None)),
                environment=envs_by_id.get(eid) or (next(iter(envs_by_id.values()), None)),
                fit=fit,
            )
        )
    return results


def _wire_same_sample_links(records: list[dict]) -> None:
    """Cross-link ISAAC records that measured the same physical sample, in place.

    Records sharing a ``sample.sample_id`` get reciprocal ``same_sample_as``
    links (``rel=same_sample_as``, ``basis=same_sample_id``) targeting each
    other's ``record_id`` — the ISAAC schema's mechanism for asserting "these
    records are the same physical object." This is the multi-state co-refinement
    of ONE sample (the default): every per-state record points at its siblings.

    Records with no ``sample_id``, or a unique one (e.g. a ``distinct_sample``
    co-refinement, where each state is a different physical sample), are left
    unlinked. Idempotent: an existing identical link is not duplicated.
    """
    groups: dict[str, list[dict]] = {}
    for rec in records:
        sample = rec.get("sample") if isinstance(rec, dict) else None
        sid = sample.get("sample_id") if isinstance(sample, dict) else None
        if sid:
            groups.setdefault(str(sid), []).append(rec)

    for group in groups.values():
        if len(group) < 2:
            continue  # a lone record has no sibling to link to
        for rec in group:
            links = rec.setdefault("links", [])
            existing = {(lk.get("rel"), lk.get("target")) for lk in links}
            for other in group:
                target = other.get("record_id")
                if other is rec or not target:
                    continue
                if ("same_sample_as", target) in existing:
                    continue
                links.append(
                    {
                        "rel": "same_sample_as",
                        "target": target,
                        "basis": "same_sample_id",
                    }
                )
                existing.add(("same_sample_as", target))


@main.command("convert-ingest")
@click.argument(
    "ingest_dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    required=False,
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=None,
    help="Output path. May be a file or a directory; defaults to the ingest dir.",
)
@click.option("--compact", is_flag=True, help="Output compact JSON (no indentation)")
@click.option("--dry-run", is_flag=True, help="Assemble but don't write output")
@click.option("--sample-name", default=None, help="Sample name (overrides assembled composition)")
@click.option(
    "--sample-formula", default=None, help="Sample formula (overrides assembled composition)"
)
@click.option(
    "--environment",
    "environment_desc",
    default=None,
    help="Environment description (e.g. 'in_situ', 'operando').",
)
@click.option("--context", default=None, help="Free-text context description")
@click.option("--raw", "raw_file", default=None, help="Path to the raw NeXus file")
@click.option(
    "--reduced",
    "reduced_file",
    default=None,
    help="Path to the reduced data file (recorded as a reduction_product asset)",
)
@click.option(
    "--result-out",
    "result_out",
    type=click.Path(dir_okay=False),
    default=None,
    help="Write a neutral ndip-tool-result/1 manifest (params/artifacts/info) "
    "describing the conversion. Schema-agnostic.",
)
def convert_ingest(
    ingest_dir: Path | None,
    output: Path | None,
    compact: bool,
    dry_run: bool,
    sample_name: str | None,
    sample_formula: str | None,
    environment_desc: str | None,
    context: str | None,
    raw_file: str | None,
    reduced_file: str | None,
    result_out: str | None,
) -> None:
    """Convert a data-assembler ingest output directory to an ISAAC record.

    This is the canonical route: the data-assembler is the structured-truth
    layer (typically populated by ``data-assembler ingest-workflow <run>``,
    which pulls the fitted model with uncertainties, χ², and experimental
    conditions), and this command maps its records to ISAAC.

    INGEST_DIR is the directory written by ``data-assembler ingest`` /
    ``ingest-workflow``. The JSON files (when written with ``--json``) are
    preferred; otherwise the Parquet files are read.
    One ISAAC AI-Ready Record is written.
    """
    from .result_manifest import write_manifest

    def _fail_manifest(message: str) -> None:
        if result_out is not None:
            write_manifest(
                result_out,
                "nr-isaac-format",
                "failed",
                params={"ingest_dir": str(ingest_dir) if ingest_dir else None},
                exit_code=1,
                messages=[{"level": "error", "text": message}],
            )

    if ingest_dir is None:
        raise click.UsageError("INGEST_DIR is required.")
    if not ingest_dir.is_dir():
        raise click.UsageError(f"INGEST_DIR does not exist: {ingest_dir}")

    try:
        # One AssemblyResult per state (runs sharing sample_id+environment_id).
        # Single-state dirs yield a one-element list → unchanged behavior.
        states = _load_states_from_ingest(ingest_dir)
    except click.ClickException as e:
        _fail_manifest(f"convert-ingest failed to read ingest dir: {e}")
        raise
    except Exception as e:
        _fail_manifest(f"convert-ingest error: {e}")
        click.echo(click.style(f"Error reading ingest output: {e}", fg="red"), err=True)
        sys.exit(1)

    n_states = len(states)
    if reduced_file:
        states[0].reduced_file = reduced_file

    first_refl = states[0].reflectivity or {}
    title = first_refl.get("run_title") or (
        f"run {first_refl.get('run_number')}" if first_refl.get("run_number") else ingest_dir.name
    )
    click.echo(click.style(f"Converting: {title}", fg="cyan", bold=True))
    click.echo(f"  Source: {ingest_dir}")
    if n_states > 1:
        click.echo(f"  States: {n_states} → {n_states} ISAAC record(s) (one per state)")
    click.echo()

    # Resolve output: explicit .json file (single state only), or a directory.
    if output is None:
        out_dir, out_file_explicit = ingest_dir, None
    elif output.suffix == ".json":
        out_dir, out_file_explicit = output.parent, output
    else:
        out_dir, out_file_explicit = output, None

    if out_file_explicit is not None and n_states > 1:
        msg = f"{n_states} states found; pass -o as a directory (one record is written per state)."
        _fail_manifest(msg)
        raise click.UsageError(msg)

    writer = IsaacWriter()
    # Pass 1: build every record (record_id assigned here). We build all records
    # before writing so per-state records of one physical sample can be
    # cross-linked by record_id (same_sample_as) — a forward reference no
    # single-record pass could resolve.
    built: list[tuple] = []  # (run_number, record)
    for state in states:
        refl = state.reflectivity or {}
        run_number = refl.get("run_number")
        if state.sample:
            click.echo(
                f"  Sample: {state.sample.get('description', 'unknown')} "
                f"({str(state.sample.get('id', ''))[:8]}...)"
            )
        if state.environment:
            click.echo(f"  Environment: {state.environment.get('description', 'unknown')}")
        runs = state.reflectivities
        total_q = sum(len(r.get("q") or []) for r in runs)
        label = f"run {run_number}" if run_number else "state"
        click.echo(f"  [{label}] {len(runs)} run(s) → {len(runs)} series; {total_q} Q points")

        record = writer.to_isaac(
            state,
            environment_description=environment_desc,
            context_description=context,
            raw_file_path=raw_file,
            sample_name=sample_name,
            sample_formula=sample_formula,
        )
        built.append((run_number, record))

    # Cross-link records that measured the SAME physical sample (multi-state
    # co-refinement of one sample → reciprocal same_sample_as). distinct_sample
    # states carry distinct sample_ids upstream and stay unlinked.
    _wire_same_sample_links([rec for _, rec in built])
    n_links = sum(len(rec.get("links") or []) for _, rec in built)
    if n_links:
        click.echo(f"  Linked {n_links} same_sample_as relation(s) across states")

    if dry_run:
        click.echo(click.style(f"  (dry run — {len(built)} record(s) not written)", fg="cyan"))
        return

    written: list[Path] = []
    for run_number, record in built:
        out_dir.mkdir(parents=True, exist_ok=True)
        if out_file_explicit is not None:
            out_file = out_file_explicit
        else:
            # Guarantee a unique filename per state: two states can share (or
            # lack) a primary run_number, which would otherwise overwrite.
            base = f"isaac_record_{run_number}" if run_number else "isaac_record"
            out_file = out_dir / f"{base}.json"
            dup = 2
            while out_file in written:
                out_file = out_dir / f"{base}_{dup}.json"
                dup += 1

        with open(out_file, "w") as f:
            json.dump(record, f, indent=None if compact else 2, default=str)
        written.append(out_file)
        click.echo(click.style(f"  Wrote: {out_file}", fg="green"))

    if result_out is not None:
        if len(written) == 1:
            artifacts = {"isaac_record": str(written[0].resolve())}
        else:
            artifacts = {"isaac_records": [str(p.resolve()) for p in written]}
        write_manifest(
            result_out,
            "nr-isaac-format",
            "ok",
            params={
                "ingest_dir": str(ingest_dir.resolve()),
                "reduced_input": reduced_file,
                "nexus_input": raw_file,
            },
            artifacts=artifacts,
            info={"isaac_status": "converted", "record_count": len(written)},
        )
        click.echo(click.style(f"Result manifest written: {Path(result_out).resolve()}", fg="green"))


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
    from .client import IsaacAPIError, IsaacAuthError, IsaacClient, IsaacValidationError

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
    from .client import IsaacAPIError, IsaacClient

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


def _next_revision(schema_dir: Path, version: str, prefix: str = "isaac_record") -> int:
    """Determine the next revision number for a given version.

    Scans *schema_dir* for files matching
    ``<prefix>_v<version>-ornl-rev<N>.json`` and returns ``max(N) + 1``.
    Returns ``1`` when no prior revisions exist.
    """
    import re

    pattern = re.compile(rf"^{re.escape(prefix)}_v{re.escape(version)}-ornl-rev(\d+)\.json$")
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
            click.style("Warning: could not detect ontology version; using 'unknown'", fg="yellow"),
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


def _migrate_record_to_rev3(record: dict) -> bool:
    """Migrate an ISAAC record from rev2 schema to rev3 in-place.

    Applies all structural changes required by v1-ornl-rev3:
    - Bumps ``isaac_record_version`` to ``"1.05"``
    - Moves ``context.pressure_Pa`` under ``context.thermodynamics``
    - Strips ``context.description`` and ``context.ambient_medium`` (rev3
      forbids these via ``additionalProperties: false``) and re-emits them
      as a ``metadata_snapshot`` asset so the data is preserved.

    Returns True if any changes were made, False if already rev3-compatible.
    """
    import base64
    import hashlib

    changed = False

    if record.get("isaac_record_version") != "1.05":
        record["isaac_record_version"] = "1.05"
        changed = True

    ctx = record.get("context")
    if isinstance(ctx, dict):
        if "pressure_Pa" in ctx:
            pressure = ctx.pop("pressure_Pa")
            thermo = ctx.setdefault("thermodynamics", {})
            thermo.setdefault("pressure_Pa", pressure)
            changed = True

        snapshot_payload: dict = {}
        for legacy_key in ("description", "ambient_medium"):
            if legacy_key in ctx:
                snapshot_payload[legacy_key] = ctx.pop(legacy_key)
                changed = True

        if snapshot_payload:
            inline = json.dumps(snapshot_payload, sort_keys=True)
            sha = hashlib.sha256(inline.encode("utf-8")).hexdigest()
            uri = "data:application/json;base64," + base64.b64encode(inline.encode("utf-8")).decode(
                "ascii"
            )
            assets = record.setdefault("assets", [])
            assets.append(
                {
                    "asset_id": "context_metadata_snapshot",
                    "content_role": "metadata_snapshot",
                    "media_type": "application/json",
                    "uri": uri,
                    "sha256": sha,
                }
            )

    return changed


def _migrate_record_to_rev4(record: dict) -> bool:
    """Migrate an ISAAC record from rev3 schema to rev4 in-place.

    rev4 closes most blocks with ``additionalProperties: false``. Applies:
    - Removes ``descriptors.policy`` (the block is now closed; ``outputs`` only).
    - Rewrites each descriptor's ``uncertainty`` from the old ``{"type": ...}``
      shape to rev4's ``{"sigma": null}``.
    - Relocates ``measurement.description`` → ``measurement.series[].notes``.
    - Relocates ``sample.description`` → ``sample.material.notes``.

    ``isaac_record_version`` const is unchanged ("1.05"). Returns True if any
    changes were made, False if already rev4-compatible.
    """
    changed = False

    descriptors = record.get("descriptors")
    if isinstance(descriptors, dict):
        if "policy" in descriptors:
            del descriptors["policy"]
            changed = True
        for output in descriptors.get("outputs", []):
            for desc in output.get("descriptors", []):
                unc = desc.get("uncertainty")
                if isinstance(unc, dict) and "type" in unc and "sigma" not in unc:
                    desc["uncertainty"] = {"sigma": None}
                    changed = True

    measurement = record.get("measurement")
    if isinstance(measurement, dict) and "description" in measurement:
        note = measurement.pop("description")
        series = measurement.get("series")
        if isinstance(series, list) and series and isinstance(series[0], dict):
            series[0].setdefault("notes", note)
        changed = True

    sample = record.get("sample")
    if isinstance(sample, dict) and "description" in sample:
        note = sample.pop("description")
        material = sample.get("material")
        if isinstance(material, dict):
            material.setdefault("notes", note)
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


def _find_existing_record_id(output_dir: Path, run_number: str) -> tuple[str | None, Path | None]:
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
    """Migrate ISAAC records to the latest schema revision (v1-ornl-rev4).

    Lightweight schema-only migration: applies structural changes from
    rev1 → rev2 (acquisition_source removal, descriptor source remap,
    system.technique addition), rev2 → rev3 (version bump, pressure_Pa
    relocation under thermodynamics, removal of forbidden context fields
    into a metadata_snapshot asset), and rev3 → rev4 (drop descriptors.policy,
    rewrite uncertainty to the sigma shape, relocate descriptions to
    series/material notes) without re-running the data pipeline. Use this when
    the original data files are not available; prefer ``update`` for a full
    regeneration.

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
        click.style(f"Migrating {len(files)} record(s) to rev4 schema", fg="cyan", bold=True)
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

        changed = _migrate_record_to_rev2(record)
        changed = _migrate_record_to_rev3(record) or changed
        changed = _migrate_record_to_rev4(record) or changed

        if not changed:
            click.echo(click.style(f"  – {label}: already rev4-compatible", fg="yellow"))
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
        click.echo(click.style(f"Skipped {skipped} record(s) (already rev4).", fg="yellow"))


if __name__ == "__main__":
    main()
