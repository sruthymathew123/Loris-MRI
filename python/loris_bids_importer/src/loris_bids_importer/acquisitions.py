from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TypeVar

from lib.db.models.session import DbSession
from lib.env import Env
from lib.logging import log, log_error
from loris_bids_utils.info import BidsAcquisitionInfo

from loris_bids_importer.copy_files import add_bids_scan_row, get_loris_scans_path
from loris_bids_importer.env import BidsImportEnv


class BidsImportFileStatus(Enum):
    """
    The status of a BIDS file import.
    """

    SUCCESS = 1
    """
    The file was successfully imported.
    """

    IGNORE = 2
    """
    The file was ignored, usually because it is already in LORIS.
    """


@dataclass
class BidsImportFileResult:
    """
    The result of a BIDS acquisition import.
    """

    status: BidsImportFileStatus
    """
    The status of the BIDS file import.
    """

    path: Path
    """
    The path of the imported file relative to the LORIS data directory.
    """


T = TypeVar('T')


def import_bids_acquisitions(
    env: Env,
    import_env: BidsImportEnv,
    session: DbSession,
    acquisitions: list[tuple[T, BidsAcquisitionInfo]],
    importer: Callable[[T, BidsAcquisitionInfo], BidsImportFileResult]
):
    """
    Run an import function on a list of BIDS acquisitions, logging the overall import progress,
    and catching the eventual exceptions raised during each import.
    """

    for acquisition, bids_info in acquisitions:
        log(
            env,
            f"Importing {bids_info.data_type} acquisition '{bids_info.name}'...",
        )

        try:
            result = importer(acquisition, bids_info)
            match result.status:
                case BidsImportFileStatus.SUCCESS:
                    # Update the LORIS scans.tsv file.
                    if bids_info.scans_file is not None and bids_info.scan_row is not None:
                        loris_scans_path = get_loris_scans_path(import_env, bids_info.scans_file, session)
                        bids_info.scan_row.set_file_name(result.path.name)
                        add_bids_scan_row(import_env, bids_info.scan_row, loris_scans_path)

                    import_env.imported_acquisitions_count += 1
                    log(env, f"Successfully imported acquisition '{bids_info.name}'.")
                case BidsImportFileStatus.IGNORE:
                    import_env.ignored_acquisitions_count += 1
                    log(env, f"File '{result.path}' is already registered in LORIS. Skipping.")
        except Exception as exception:
            import_env.failed_acquisitions_count += 1
            log_error(
                env,
                (
                    f"Error while importing acquisition '{bids_info.name}'. Error message:\n"
                    f"{exception}\n"
                    "Skipping."
                )
            )
