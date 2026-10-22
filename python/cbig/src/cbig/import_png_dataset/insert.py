import re
import shutil
from pathlib import Path

import lib.exitcode
from lib.db.models.file import DbFile
from lib.db.models.session import DbSession
from lib.db.queries.config import try_get_config_with_setting_name
from lib.db.queries.file import try_get_file_with_hash, try_get_file_with_path
from lib.env import Env
from lib.imaging_lib.file import register_mri_file
from lib.imaging_lib.file_parameter import register_mri_file_parameter, register_mri_file_parameters
from lib.logging import log, log_error_exit, log_verbose, log_warning
from loris_utils.crypto import compute_file_blake2b_hash
from PIL import Image

from cbig.import_png_dataset.check import Resolved
from cbig.import_png_dataset.submission import PngImage

# Subdirectory under the visit directory, the PNG equivalent of the 'mri' and
# 'pet' directories move_minc writes into.
ASSEMBLY_SUBDIR = 'png'

# Width in pixels of the pic shown in the imaging browser.
PIC_WIDTH = 200


def insert_image(
    env: Env, data_dir_path: Path, image: PngImage, resolved: Resolved, create_pic: bool,
) -> bool:
    """
    Copy and register one validated PNG image. Returns whether it was inserted.
    """

    session       = resolved.sessions[image.psc_id, image.visit_label]
    mri_scan_type = resolved.mri_scan_types[image.scan_type_name]
    file_type     = resolved.file_type

    assert session is not None and file_type is not None

    blake2b_hash = compute_file_blake2b_hash(image.path)

    # try_get_file_with_hash matches either file_blake2b_hash or md5hash in a
    # single query, so one call covers both. Checked here rather than during
    # validation because an image inserted earlier in this same run counts too.
    existing = try_get_file_with_hash(env.db, blake2b_hash)

    if existing is not None:
        log_warning(
            env,
            f"{image.location} is already registered in the files table as"
            f" {existing.path} (FileID {existing.id}). Skipping.",
        )
        return False

    file_rel_path = _determine_file_rel_path(env, data_dir_path, session, image.scan_type_name)
    file_path     = data_dir_path / file_rel_path

    # 0o775, not 0o770: Apache serves the image for download and reads the pic
    # for the imaging browser thumbnail, and it is not in the owning group on
    # every install. The core pipeline leaves the mode to the umask for the same
    # reason. A directory created 0o770 renders as a broken image with nothing
    # logged anywhere.
    file_path.parent.mkdir(mode=0o775, parents=True, exist_ok=True)

    # A copy rather than a move, so the submitted directory survives the run and
    # can be re-ingested after a failure. The Perl pipeline moves instead,
    # because it owns the incoming upload; here the caller does. The
    # destination is known to be free (see _determine_file_rel_path), so
    # nothing is ever overwritten.
    log_verbose(env, f"Copying {image.path} to {file_path}")
    try:
        shutil.copyfile(image.path, file_path)
    except OSError as exception:
        log_error_exit(
            env,
            f"Could not copy {image.location} to {file_path}: {exception}",
            lib.exitcode.COPY_FAILURE,
        )

    # Everything from here writes to the database. The registration helpers
    # only flush, so nothing is committed until the commit below and a failure
    # rolls back the whole image. The copy above would then be an orphan: a file
    # in the assembly tree that no files row points at, which nothing will ever
    # clean up. So the copy is removed before the error is raised.
    try:
        # A PNG carries no header and no JSON sidecar, so sessions.tsv is the
        # only place an acquisition date can come from.
        file = register_mri_file(
            env,
            file_rel_path,
            file_type,
            session,
            mri_scan_type,
            scanner                  = None,
            dicom_archive            = None,
            series_instance_uid      = None,
            echo_time                = None,
            echo_number              = None,
            phase_encoding_direction = None,
            acquisition_date         = image.acq_date,
            caveat                   = False,
        )

        # source_filename preserves the name the submitter gave the image, which
        # the rename to the assembly convention would otherwise lose.
        register_mri_file_parameters(env, file, {
            'md5hash':           image.md5_hash,
            'file_blake2b_hash': blake2b_hash,
            'source_filename':   image.path.name,
        })

        env.db.commit()
    except Exception as exception:
        env.db.rollback()
        file_path.unlink(missing_ok=True)

        log_error_exit(
            env,
            f"Could not register {image.location}: {exception}",
            lib.exitcode.INSERT_FAILURE,
        )

    log(env, f"{image.location} inserted as FileID {file.id} ({file_rel_path})")

    if create_pic:
        _create_pic(env, data_dir_path, file)

    return True


def _determine_file_rel_path(env: Env, data_dir_path: Path, session: DbSession, scan_type_name: str) -> Path:
    """
    Build a file path that does not collide with anything in the visit already.

    Both the directory and the name follow the convention move_minc produces for
    MINC files, so a PNG sits alongside them and reads the same way:

        assembly/<CandID>/<VisitLabel>/png/native/
        <prefix>_<CandID>_<VisitLabel>_<scan_type>_<NNN>.png

    where <prefix> is the 'prefix' setting from the Config module, the same
    value move_minc uses. No hyphens anywhere: the MINC files have none, and
    mri_scan_type names may not contain them either.

    The version is incremented until the path is free both in the files table
    and on disk, as move_minc does. Deriving it from what already exists rather
    than from the submitted file names is what makes a second delivery to the
    same visit safe; numbering from the input would restart at 1 and overwrite
    the first delivery.
    """

    cand_id     = session.candidate.cand_id
    visit_label = session.visit_label
    prefix      = _get_prefix_config(env)

    directory = Path('assembly', str(cand_id), visit_label, ASSEMBLY_SUBDIR, 'native')

    version = 1

    while True:
        rel_path = directory / f"{prefix}_{cand_id}_{visit_label}_{scan_type_name}_{version:03d}.png"

        if try_get_file_with_path(env.db, rel_path) is None and not (data_dir_path / rel_path).exists():
            return rel_path

        version += 1


def _get_prefix_config(env: Env) -> str:
    """
    Read the 'prefix' setting that move_minc uses to name assembled files.
    """

    config = try_get_config_with_setting_name(env.db, 'prefix')

    if config is None or config.value is None:
        log_error_exit(
            env,
            "No 'prefix' configuration value found in the database. It is the same"
            " setting the MINC insertion uses to name assembled files.",
            lib.exitcode.MISSING_CONFIG_SETTING,
        )

    return config.value


def _create_pic(env: Env, data_dir_path: Path, file: DbFile):
    """
    Write the check pic and register it in parameter_file.

    lib.imaging_lib.nifti_pic.create_nifti_preview_picture cannot be reused: it
    renders a volume with nilearn's plot_anat and builds its name by stripping a
    .nii or .nii.gz suffix. The naming convention it produces is followed here,
    file ID included, which is why this runs after the registration rather than
    before.
    """

    cand_id      = file.session.candidate.cand_id
    file_path    = data_dir_path / file.path
    pic_name     = re.sub(r'\.png$', f"_{file.id}_check.png", file.path.name)
    pic_rel_path = Path(str(cand_id)) / pic_name
    pic_path     = data_dir_path / 'pic' / pic_rel_path

    try:
        pic_path.parent.mkdir(mode=0o775, parents=True, exist_ok=True)

        with Image.open(file_path) as image:
            # Flattened onto black: these exports often carry an alpha channel,
            # and a transparent surround renders as a broken image in the imaging
            # browser rather than as the image itself.
            flat = Image.new('RGB', image.size, (0, 0, 0))
            flat.paste(image, mask=image.split()[3] if image.mode == 'RGBA' else None)

            width  = min(PIC_WIDTH, flat.width)
            height = max(1, round(flat.height * (width / flat.width)))

            flat.resize((width, height)).save(pic_path, 'PNG')
    except Exception as exception:
        # A missing pic costs a preview, not the insertion, so this warns rather
        # than failing. The files row is already valid without it.
        log_warning(env, f"Could not create the pic for FileID {file.id}: {exception}")
        return

    # The registration helper only flushes, so the parameter must be committed
    # here or it is lost when the session closes.
    register_mri_file_parameter(env, file, 'check_pic_filename', str(pic_rel_path))
    env.db.commit()

    log_verbose(env, f"Created pic {pic_rel_path}")
