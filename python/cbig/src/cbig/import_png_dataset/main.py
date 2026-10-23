import lib.exitcode
from lib.config import get_data_dir_path_config
from lib.env import Env
from lib.logging import log, log_error, log_error_exit

from cbig.import_png_dataset.args import Args
from cbig.import_png_dataset.check import Resolved, check_against_database, check_environment
from cbig.import_png_dataset.insert import PngInsertError, insert_image
from cbig.import_png_dataset.problems import ProblemLog
from cbig.import_png_dataset.submission import read_submission


def import_png_dataset(env: Env, args: Args):
    """
    Validate a submitted directory of PNG images, then insert it.

    Everything is checked before anything is written, and all problems are
    reported together. Any error stops the run with nothing inserted; warnings
    are reported and the run continues.

    Each image is then inserted on its own: an image that fails is reported and
    left out entirely, and the other images are still inserted. The run exits
    with an error if any image failed, so it can be fixed and re-run; images
    already inserted are skipped by hash on the next run.
    """

    # Exits with an error if the data directory is missing or not writable.
    data_dir_path = get_data_dir_path_config(env)

    log(env, f"Reading PNG submission at {args.png_dir_path}...")

    problems = ProblemLog()
    resolved = Resolved()

    check_environment(env, data_dir_path, args, resolved, problems)

    images = read_submission(args, problems)

    check_against_database(env, images, resolved, problems)

    # Exits with the full report if anything found was an error.
    problems.report(env, args.png_dir_path, len(images))

    if args.validate_only:
        log(env, "Validation only: nothing was inserted.")
        return

    inserted = 0
    skipped  = 0
    failed: list[str] = []

    for image in images:
        try:
            if insert_image(env, data_dir_path, image, resolved, args.create_pic):
                inserted += 1
            else:
                skipped += 1
        except PngInsertError as error:
            log_error(env, str(error))
            failed.append(image.location)

    summary = (
        f"{inserted} file(s) inserted, {skipped} already registered, {len(failed)} failed,"
        f" out of {len(images)} validated."
    )

    if failed:
        log_error_exit(
            env,
            f"{summary}\nFailed: {', '.join(failed)}\nFix the problem and run again; inserted images are skipped.",
            lib.exitcode.INSERT_FAILURE,
        )

    log(env, summary)
