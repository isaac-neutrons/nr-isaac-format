"""Lock the public CLI surface that aure and ndip-workflows depend on.

This is the safety mechanism for keeping nr-isaac-format a separate package
(rather than merging it into data-assembler):

- ndip-workflows' data_assembler.xml invokes ``nr-isaac-format convert-ingest``.
- aure's optional ``export`` extra subprocesses ``nr-isaac-format convert`` and
  ``nr-isaac-format validate`` (and falls back to importing ``nr_isaac_format.cli:main``).

If any of these names disappear, those integrations break silently. This test
fails loudly first.
"""

import click

from nr_isaac_format.cli import main


def test_main_is_a_click_group():
    assert isinstance(main, click.Group)


def test_required_subcommands_present():
    # convert-ingest: ndip pipeline; convert + validate: aure export extra
    required = {"convert", "convert-ingest", "validate"}
    assert required <= set(main.commands), sorted(main.commands)


def test_importable_entry_point():
    # aure's fallback path: `from nr_isaac_format.cli import main; main()`
    from nr_isaac_format.cli import main as _m

    assert callable(_m)
