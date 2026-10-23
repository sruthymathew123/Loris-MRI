#!/usr/bin/env python

"""Script to import a submitted directory of PNG images into LORIS."""

import argparse
from pathlib import Path
from typing import Any

import lib.exitcode
from lib.config_file import load_config
from lib.logging import log_error_exit
from lib.make_env import make_env

from cbig.import_png_dataset.args import Args
from cbig.import_png_dataset.main import import_png_dataset

LAYOUT_DESCRIPTION = """\
expected layout:
  <directory>/participants.tsv
  <directory>/sub-<PSCID>/sessions.tsv            (optional)
  <directory>/sub-<PSCID>/ses-<VisitLabel>/<scan_type>_<NNN>.png

participants.tsv lists the participants the submission should contain.
sessions.tsv is optional, as in a BIDS dataset: the ses- directories define the
visits, and the file only supplies acquisition dates. The scan type is read from
the start of each file name and must already exist in the mri_scan_type table.

The whole submission is validated first and every problem is reported together.
Any error stops the run with nothing inserted.
"""


def main():
    parser = argparse.ArgumentParser(
        prog='import-png-dataset',
        description=(
            "Insert a submitted directory of PNG images, such as echocardiogram stills or ECG traces,"
            " into LORIS. A PNG carries no header the pipeline can read, so everything comes from the"
            " directory names and the file names."
        ),
        epilog=LAYOUT_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        '-p', '--profile',
        help="Name of the python database config file in the config directory.",
    )

    parser.add_argument(
        '-d', '--directory',
        type=Path,
        required=True,
        help="Directory of PNG images to parse and insert into LORIS.",
    )

    parser.add_argument(
        '-s', '--subject',
        help="Restrict the run to one participant, given as sub-<PSCID> or <PSCID>.",
    )

    parser.add_argument(
        '-V', '--visit',
        help="Restrict the run to one visit, given as ses-<VisitLabel> or <VisitLabel>.",
    )

    parser.add_argument(
        '-t', '--loris-scan-type',
        help="LORIS scan type from the mri_scan_type table. Overrides the scan type read from the file names.",
    )

    parser.add_argument(
        '-n', '--validate-only',
        action='store_true',
        help="Run every check and report, then exit without inserting anything.",
    )

    parser.add_argument(
        '-c', '--create-pic',
        action='store_true',
        help="Create the pics displayed in the imaging browser.",
    )

    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help="If set, be verbose.",
    )

    args = parser.parse_args()

    # Listed in the log file header, which shows each option set for the run.
    script_options: dict[str, Any] = {
        name: {'value': value} for name, value in vars(args).items()
    }

    config_file = load_config(args.profile)
    env = make_env('import_png_dataset', script_options, config_file, args.verbose)

    png_dir_path: Path = args.directory.resolve()

    if not png_dir_path.is_dir():
        log_error_exit(
            env,
            f"The --directory value '{args.directory}' is not an existing directory.",
            lib.exitcode.INVALID_PATH,
        )

    import_png_dataset(env, Args(
        png_dir_path   = png_dir_path,
        subject_label  = _strip_prefix(args.subject, 'sub-'),
        session_label  = _strip_prefix(args.visit, 'ses-'),
        scan_type_name = args.loris_scan_type,
        validate_only  = args.validate_only,
        create_pic     = args.create_pic,
        verbose        = args.verbose,
    ))


def _strip_prefix(value: str | None, prefix: str) -> str | None:
    """
    Accept a filter given either with or without its sub-/ses- prefix.
    """

    return value.removeprefix(prefix) if value is not None else None


if __name__ == '__main__':
    main()
