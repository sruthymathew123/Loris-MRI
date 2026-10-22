# C-BIG LORIS Python

## Description

C-BIG specific LORIS Python pipelines, kept in their own package so they stay separate from the upstream LORIS Python code.

## Installation

This package is installed by default with C-BIG LORIS Python.

## PNG dataset import

The PNG dataset import inserts a submitted directory of PNG images (for instance echocardiogram stills or ECG traces) into the LORIS `files` table. A PNG has no header and no JSON sidecar, so everything comes from the directory and file names.

### Layout

```
delivery/
├── participants.tsv                      required
└── sub-<PSCID>/
    ├── sessions.tsv                      optional: acquisition dates
    └── ses-<VisitLabel>/
        ├── t1_001.png
        └── t2_001.png
```

- `participants.tsv` must have a `participant_id` column. Every `sub-` directory must have a row.
- `sessions.tsv` is optional, as in a BIDS dataset: the `ses-` directories define the visits and the file only supplies the `acq_date` (`YYYY-MM-DD`) of each `session_id`.
- The scan type is the file name up to the first underscore and must already exist in `mri_scan_type`. Scan types, candidates, visits and sessions are never created.
- Identifiers are LORIS PSCIDs, so re-identification happens upstream.

The whole submission is validated before anything is written, and every problem is reported with a severity. An error stops the run with nothing inserted; warnings do not.

### Output

Path and name follow `move_minc`, so a PNG sits alongside the MINC files:

```
assembly/<CandID>/<VisitLabel>/png/native/<prefix>_<CandID>_<VisitLabel>_<scan_type>_<NNN>.png
```

where `<prefix>` is the `prefix` Config setting. The version `<NNN>` is the first one free in the `files` table and on disk, so a second delivery to the same visit never overwrites the first.

Per image: one `files` row, `parameter_file` rows for `md5hash`, `file_blake2b_hash` and `source_filename`, and with `--create-pic` the thumbnail plus `check_pic_filename`. Re-running a delivery skips images already registered with the same hash.

### Setup

The `png` imaging file type must exist in the `ImagingFileTypes` table. The pipeline checks for it before anything else and reports an error, with nothing inserted, if it is missing.

### Usage

```sh
# Report every problem, write nothing.
import-png-dataset --directory <delivery> --validate-only -v

# Insert, with imaging browser pics.
import-png-dataset --directory <delivery> --create-pic -v

# Re-run one participant out of a larger submission.
import-png-dataset --directory <delivery> --subject sub-<PSCID> --visit ses-<VisitLabel> --create-pic
```

`--profile` selects a database config file other than the default `database_config.py`, and `--loris-scan-type` overrides the scan type read from the file names. See `import-png-dataset --help` for all the options.