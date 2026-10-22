import getpass
import os
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from loris_bids_utils.files.participants import BidsParticipantsTsvFile
from loris_bids_utils.tsv import BidsTsvFile, BidsTsvRow
from loris_utils.crypto import compute_file_md5_hash

from cbig.import_png_dataset.args import Args
from cbig.import_png_dataset.problems import ProblemLog

# First eight bytes of any PNG file. Checked because a renamed JPEG or a
# truncated transfer is a common way for a submission to arrive broken, and both
# would otherwise fail much later with an unhelpful message.
PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'

# mri_scan_type names may not contain commas, hyphens, spaces or periods. A scan
# type read from a file name cannot contain an underscore either, since that is
# the separator the name is split on.
SCAN_TYPE_FROM_FILE_NAME_REGEX = re.compile(r'^[A-Za-z0-9]+$')
SCAN_TYPE_ARG_REGEX            = re.compile(r'^[A-Za-z0-9_]+$')

PARTICIPANTS_TSV_NAME = 'participants.tsv'
SESSIONS_TSV_NAME     = 'sessions.tsv'

# Matched in full rather than as a prefix. See _read_subjects.
SUBJECT_DIR_REGEX = re.compile(r'sub-([a-zA-Z0-9]+)')
SESSION_DIR_REGEX = re.compile(r'ses-([a-zA-Z0-9]+)')


@dataclass
class SubmissionSubject:
    """
    A participant directory of the submission, with its name read in full.
    """

    label: str
    path: Path


@dataclass
class SubmissionSession:
    """
    A visit directory of the submission, with its name read in full.
    """

    label: str
    path: Path


@dataclass
class PngImage:
    """
    One PNG image the submission asks to insert, before anything is resolved
    against the database.
    """

    path: Path
    psc_id: str
    visit_label: str
    scan_type_name: str
    acq_date: date | None
    md5_hash: str
    location: str


def _is_hidden(name: str) -> bool:
    """
    True for entries no submission ever means to include.

    Covers dotfiles and the AppleDouble companions that macOS writes beside every
    file in a zip archive. The companions matter because they mirror the name they
    shadow: `._sessions.tsv` ends with 'sessions.tsv' and `._t1_001.png` ends with
    '.png', so a suffix test alone picks them up and then fails on their contents,
    which are a binary resource fork rather than the file they appear to be.
    """

    return name.startswith('.')


def _list_dir(dir_path: Path) -> list[Path]:
    """
    List the non-hidden entries of a directory, sorted by name.
    """

    return sorted(
        (path for path in dir_path.iterdir() if not _is_hidden(path.name)),
        key=lambda path: path.name,
    )


def read_submission(args: Args, problems: ProblemLog) -> list[PngImage]:
    """
    Walk the submitted directory and return the images it asks to insert.

    Nothing is resolved against the database here. This establishes what the
    submission claims to contain and checks that the directories, the TSV files
    and the images themselves agree with each other.

    A PNG submission borrows the sub-/ses- naming of BIDS, but is not a BIDS
    dataset: it has no dataset_description.json and no BIDS-valid file names. So
    the LORIS BIDS TSV readers are used for participants.tsv and sessions.tsv,
    but the directory walk is done here.
    """

    tsv_participants = _read_tsv_participants(args.png_dir_path, problems)

    if tsv_participants is None:
        return []

    subjects = _read_subjects(args.png_dir_path, problems)

    if not subjects:
        return []

    _report_stray_root_entries(args.png_dir_path, problems)

    for psc_id in sorted(tsv_participants - {subject.label for subject in subjects}):
        problems.warning(
            PARTICIPANTS_TSV_NAME,
            f"row 'sub-{psc_id}' has no matching directory; nothing will be inserted"
            f" for that participant.",
        )

    images: list[PngImage] = []

    for subject in subjects:
        if args.subject_label is not None and subject.label != args.subject_label:
            continue

        if subject.label not in tsv_participants:
            problems.error(
                f"sub-{subject.label}",
                "directory has no row in participants.tsv, so it was not part of the"
                " agreed submission.",
            )
            continue

        images += _read_subject(subject, args, problems)

    if args.subject_label is not None \
            and args.subject_label not in {subject.label for subject in subjects}:
        problems.error('--subject', f"no directory sub-{args.subject_label} in the submission.")

    if not images and not problems.has_errors():
        problems.error('root', f"no PNG file found under {args.png_dir_path}.")

    _check_images(images, problems)

    return images


# =============================================================================
#  participants.tsv
# =============================================================================

def _read_tsv_participants(png_dir_path: Path, problems: ProblemLog) -> set[str] | None:
    """
    Read and check participants.tsv. Returns the participant labels it lists,
    without their sub- prefix, or None when the file is unusable.
    """

    path = png_dir_path / PARTICIPANTS_TSV_NAME

    if not path.is_file():
        problems.error(
            'root',
            "no participants.tsv. It lists the participants the submission is expected"
            " to contain.",
        )
        return None

    if path.stat().st_size == 0:
        problems.error(PARTICIPANTS_TSV_NAME, "the file is empty.")
        return None

    # A submission saved as CSV rather than tab-separated is the single most
    # common TSV mistake, and produces a baffling "missing participant_id"
    # otherwise.
    with open(path, encoding='utf-8-sig', errors='replace') as tsv_file:
        header = tsv_file.readline()

    if '\t' not in header and ',' in header:
        problems.error(
            PARTICIPANTS_TSV_NAME,
            "the header has no tab but does contain commas; the file looks"
            " comma-separated. Save it as Tab Delimited Text.",
        )
        return None

    try:
        # Raises on a row without a participant_id.
        participants_file = BidsParticipantsTsvFile(path)
    except Exception as exception:
        problems.error(PARTICIPANTS_TSV_NAME, f"could not be read: {exception}")
        return None

    if not participants_file.rows:
        problems.error(PARTICIPANTS_TSV_NAME, "the file has a header but no data rows.")
        return None

    # The participant set collapses a repeated row silently, so repeats are
    # counted from the rows and reported.
    _check_duplicate_values(
        [row.participant_id for row in participants_file.rows],
        'participant_id',
        PARTICIPANTS_TSV_NAME,
        problems,
    )

    return {row.participant_id for row in participants_file.rows}


# =============================================================================
#  Directories
# =============================================================================

def _read_subjects(png_dir_path: Path, problems: ProblemLog) -> list[SubmissionSubject]:
    """
    Return the participant directories, rejecting any whose name is not readable.

    The name is matched in full with `fullmatch`, not with the `re.match` prefix
    match the BIDS readers use. A prefix match turns `sub-ARCHI_0001` into the
    label `ARCHI` and `sub-P014-B` into `P014`, with nothing to show that the
    rest of the name was dropped. That is the right behavior for a BIDS dataset,
    where an entity is followed by other entities, and the wrong one here, where
    the whole directory name is one identifier. A mismatch is reported rather
    than silently trimmed.
    """

    subjects: list[SubmissionSubject] = []
    found_any = False

    for path in _list_dir(png_dir_path):
        if not path.is_dir() or not path.name.startswith('sub-'):
            continue

        found_any = True

        match = SUBJECT_DIR_REGEX.fullmatch(path.name)

        if match is None:
            problems.error(
                path.name,
                "participant identifiers may only contain letters and numbers after the"
                " sub- prefix. This directory cannot be read as an identifier, so"
                " nothing in it was looked at.",
            )
            continue

        subjects.append(SubmissionSubject(label=match.group(1), path=path))

    if not found_any:
        problems.error('root', "no sub- directory found.")

    return subjects


def _read_sessions(subject: SubmissionSubject, problems: ProblemLog) -> list[SubmissionSession]:
    """
    Return the visit directories of a participant, rejecting unreadable names.

    Same prefix-match trap as the participant directories, and more likely to
    bite: `4_month_echocardiography` is a perfectly good LORIS visit label, but
    `ses-4_month_echocardiography` would yield the label `4` and then fail a
    lookup naming a visit the submitter never mentioned.
    """

    sessions: list[SubmissionSession] = []

    for path in _list_dir(subject.path):
        if not path.is_dir() or not path.name.startswith('ses-'):
            continue

        match = SESSION_DIR_REGEX.fullmatch(path.name)

        if match is None:
            problems.error(
                f"sub-{subject.label}/{path.name}",
                "visit directory names may only contain letters and numbers after the"
                " ses- prefix. A LORIS visit label that contains other characters cannot"
                " be given as a directory name; ask the ARCHIMEDES team how to submit it.",
            )
            continue

        sessions.append(SubmissionSession(label=match.group(1), path=path))

    return sessions


def _report_stray_root_entries(png_dir_path: Path, problems: ProblemLog):
    """
    Warn about anything at the top level the layout does not account for.

    Usually harmless, occasionally the reason a participant is missing: a
    directory named `Sub-ARCHI0001` or `ARCHI0001` does not match the sub-
    pattern at all, so it is invisible to the walk and would otherwise vanish
    without comment.
    """

    strays = [
        path.name for path in _list_dir(png_dir_path)
        if path.name != PARTICIPANTS_TSV_NAME
        and not (path.name.startswith('sub-') and path.is_dir())
    ]

    if strays:
        problems.warning(
            'root',
            f"{len(strays)} entr(y/ies) not matching the expected layout were ignored:"
            f" {', '.join(strays[:5])}{' ...' if len(strays) > 5 else ''}",
        )


# =============================================================================
#  Per participant
# =============================================================================

def _read_subject(subject: SubmissionSubject, args: Args, problems: ProblemLog) -> list[PngImage]:
    """
    Read one participant's optional sessions.tsv and the images under each visit.
    """

    location = f"sub-{subject.label}"

    acq_dates, tsv_present = _read_sessions_tsv(subject, location, problems)

    if acq_dates is None:
        return []

    sessions = _read_sessions(subject, problems)

    if not sessions:
        problems.warning(location, "no ses- directory; nothing to insert for this participant.")
        return []

    if tsv_present:
        for visit_label in sorted(set(acq_dates) - {session.label for session in sessions}):
            problems.warning(
                f"{location}/{SESSIONS_TSV_NAME}",
                f"row 'ses-{visit_label}' has no matching directory.",
            )

    images: list[PngImage] = []

    for session in sessions:
        if args.session_label is not None and session.label != args.session_label:
            continue

        # sessions.tsv is optional, so the ses- directories are what define the
        # visits. When the file is there it supplies acquisition dates and a
        # cross-check; a directory it does not list is worth flagging, but not
        # worth refusing, since the directory is the authority.
        if tsv_present and session.label not in acq_dates:
            problems.warning(
                f"{location}/ses-{session.label}",
                "directory has no row in sessions.tsv; no acquisition date will be"
                " recorded for it.",
            )

        images += _read_session(
            session, subject.label, acq_dates.get(session.label), args, problems
        )

    return images


def _read_sessions_tsv(
    subject: SubmissionSubject, location: str, problems: ProblemLog,
) -> tuple[dict[str, date | None] | None, bool]:
    """
    Read one participant's sessions.tsv.

    Returns the acquisition dates it holds, and whether the file was present.
    """

    # The file is sessions.tsv. A sub-<PSCID>_ prefix is accepted too, since some
    # submissions carry one, but it must name this participant:
    # sub-X_sessions.tsv sitting in sub-Y's directory is a copy-paste error, and
    # reading it would apply the wrong visit list to every image with nothing
    # flagged anywhere.
    found = [
        path for path in _list_dir(subject.path)
        if path.name.lower().endswith(SESSIONS_TSV_NAME) and path.is_file()
    ]

    if not found:
        # Optional, as in a BIDS dataset, so this warns rather than failing. It
        # is worth a warning all the same: a PNG has no header and no JSON
        # sidecar, so sessions.tsv is the only place an acquisition date can come
        # from, and it cannot be recovered later without going back to the
        # submitter.
        problems.warning(
            location,
            "no sessions.tsv. Continuing with the visits named by the ses- directories;"
            " no acquisition date will be recorded for any of them.",
        )
        return {}, False

    if len(found) > 1:
        problems.error(
            location,
            f"{len(found)} sessions files in the participant's directory"
            f" ({', '.join(path.name for path in found)}); there must be at most one.",
        )
        return None, True

    path = found[0]
    name = path.name

    claimed = re.fullmatch(r'sub-(.+)_sessions\.tsv', name, flags=re.IGNORECASE)

    if claimed is not None and claimed.group(1) != subject.label:
        problems.error(
            location,
            f"the sessions file is named {name}, which belongs to sub-{claimed.group(1)},"
            f" not to this directory. Rename it to {SESSIONS_TSV_NAME} or move it to the"
            f" right participant.",
        )
        return None, True

    if name != SESSIONS_TSV_NAME:
        problems.warning(
            location,
            f"the sessions file is named {name}; rename it to {SESSIONS_TSV_NAME}."
            f" Reading it anyway.",
        )

    if path.stat().st_size == 0:
        problems.error(f"{location}/{name}", "the file is empty.")
        return None, True

    try:
        rows = BidsTsvFile(BidsTsvRow, path).rows
    except Exception as exception:
        problems.error(f"{location}/{name}", f"could not be read: {exception}")
        return None, True

    if not rows:
        problems.error(f"{location}/{name}", "the file has a header but no data rows.")
        return None, True

    if 'session_id' not in rows[0].data:
        problems.error(
            f"{location}/{name}",
            f"no session_id column. Columns found: {', '.join(rows[0].data.keys())}.",
        )
        return None, True

    acq_dates: dict[str, date | None] = {}

    for row in rows:
        session_id = (row.data.get('session_id') or '').strip()

        if not session_id:
            problems.error(f"{location}/{name}", "a row has an empty session_id.")
            continue

        visit_label = session_id.removeprefix('ses-')

        if visit_label in acq_dates:
            problems.error(
                f"{location}/{name}", f"session_id '{session_id}' appears more than once.",
            )
            continue

        acq_dates[visit_label] = _read_acq_date(row, f"{location}/{name}", session_id, problems)

    return acq_dates, True


def _read_acq_date(
    row: BidsTsvRow, location: str, session_id: str, problems: ProblemLog,
) -> date | None:
    """
    Return acq_date as a date, or None when it is absent or unusable.
    """

    acq_date = (row.data.get('acq_date') or '').strip()

    if not acq_date:
        return None

    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', acq_date):
        problems.error(
            location, f"acq_date '{acq_date}' for {session_id} is not in YYYY-MM-DD format.",
        )
        return None

    try:
        parsed = date.fromisoformat(acq_date)
    except ValueError:
        problems.error(location, f"acq_date '{acq_date}' for {session_id} is not a real date.")
        return None

    # Not an error: a date slightly ahead of the clock can be a timezone or a
    # scheduling artifact. Worth surfacing, not worth refusing.
    if parsed > date.today():
        problems.warning(location, f"acq_date '{acq_date}' for {session_id} is in the future.")

    return parsed


# =============================================================================
#  Per visit
# =============================================================================

def _read_session(
    session: SubmissionSession,
    psc_id: str,
    acq_date: date | None,
    args: Args,
    problems: ProblemLog,
) -> list[PngImage]:
    """
    Collect the images of one visit, checking the directory's contents.
    """

    location = f"sub-{psc_id}/ses-{session.label}"

    png_paths: list[Path] = []
    strays: list[str] = []

    for path in _list_dir(session.path):
        if path.is_dir():
            problems.warning(
                location,
                f"contains a subdirectory '{path.name}'. Images are expected directly"
                f" inside the visit directory, and it was not searched.",
            )
            continue

        if path.suffix.lower() == '.png':
            png_paths.append(path)
        else:
            strays.append(path.name)

    if strays:
        problems.warning(
            location,
            f"{len(strays)} non-PNG file(s) will be ignored:"
            f" {', '.join(strays[:5])}{' ...' if len(strays) > 5 else ''}",
        )

    if not png_paths:
        problems.warning(location, "no PNG file; nothing to insert for this visit.")
        return []

    images: list[PngImage] = []

    for path in png_paths:
        image_location = f"{location}/{path.name}"

        images.append(PngImage(
            path           = path,
            psc_id         = psc_id,
            visit_label    = session.label,
            scan_type_name = _determine_scan_type(path, image_location, args, problems),
            acq_date       = acq_date,
            md5_hash       = '',
            location       = image_location,
        ))

    return images


def _determine_scan_type(path: Path, location: str, args: Args, problems: ProblemLog) -> str:
    """
    Read the scan type off the start of a file name and check its shape.

    `echo_001.png` yields 'echo'; `ecg.png` yields 'ecg'. The character set is
    checked here rather than left to the database lookup, because "scan type
    'echo-2d' not found" is a much less useful message than saying hyphens are
    not allowed in the first place.
    """

    if args.scan_type_name is not None:
        if not SCAN_TYPE_ARG_REGEX.fullmatch(args.scan_type_name):
            problems.error(
                '--loris-scan-type',
                f"'{args.scan_type_name}' contains characters that mri_scan_type names"
                f" may not hold. Letters, numbers and underscores only.",
            )

        return args.scan_type_name

    # Everything before the first underscore, or the whole stem when the file
    # name carries no sequence number.
    scan_type_name = path.stem.split('_')[0]

    if not scan_type_name:
        problems.error(
            location,
            "the file name begins with an underscore, so no scan type can be read from"
            " it. Expected <scan_type>_<NNN>.png.",
        )
    elif not SCAN_TYPE_FROM_FILE_NAME_REGEX.fullmatch(scan_type_name):
        problems.error(
            location,
            f"scan type '{scan_type_name}' read from the file name contains characters"
            f" that mri_scan_type names may not hold. Letters and numbers only.",
        )

    return scan_type_name


# =============================================================================
#  The images themselves
# =============================================================================

def _check_images(images: list[PngImage], problems: ProblemLog):
    """
    Check every image is readable, non-empty and really a PNG.

    Also catches the same image submitted twice within one delivery, which the
    database duplicate check cannot see, because neither copy is inserted yet
    when the first one is checked.
    """

    hashes_seen: dict[str, str] = {}

    for image in images:
        if not os.access(image.path, os.R_OK):
            problems.error(image.location, f"not readable by {getpass.getuser()}.")
            continue

        if image.path.stat().st_size == 0:
            problems.error(image.location, "the file is empty.")
            continue

        try:
            with open(image.path, 'rb') as image_file:
                signature = image_file.read(len(PNG_SIGNATURE))
        except OSError as exception:
            problems.error(image.location, f"could not be read: {exception}")
            continue

        if signature != PNG_SIGNATURE:
            problems.error(
                image.location,
                "does not start with the PNG signature. It is named .png but is another"
                " format, or the transfer was truncated.",
            )
            continue

        image.md5_hash = compute_file_md5_hash(image.path)

        if image.md5_hash in hashes_seen:
            problems.warning(
                image.location,
                f"is byte-identical to {hashes_seen[image.md5_hash]} in the same"
                f" submission. Only the first will be inserted.",
            )
        else:
            hashes_seen[image.md5_hash] = image.location


def _check_duplicate_values(values: list[str], column: str, location: str, problems: ProblemLog):
    """
    Report a value that appears more than once in a TSV column.
    """

    seen: set[str] = set()

    for value in values:
        if value in seen:
            problems.error(location, f"{column} '{value}' appears more than once.")

        seen.add(value)
