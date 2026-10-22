from collections.abc import Sequence
from pathlib import Path
from tarfile import TarFile
from zipfile import ZIP_DEFLATED, ZipFile


def create_tar_gz_archive_with_file(archive_path: Path, file_path: Path):
    """
    Create a tar gzip archive with the provided file or directory.
    """

    create_tar_gz_archive_with_files(archive_path, [file_path])


def create_tar_gz_archive_with_files(archive_path: Path, paths: Sequence[Path]):
    """
    Create a tar gzip archive with the provided files and directories. Files and directories are
    added using their base name, which should therefore all be distinct.
    """

    with TarFile.open(archive_path, 'w:gz') as tar:
        for path in paths:
            tar.add(path, arcname=path.name)


def create_zip_archive_with_file(archive_path: Path, file_path: Path):
    """
    Create a zip archive with the provided file or directory.
    """

    create_zip_archive_with_files(archive_path, [file_path])


def create_zip_archive_with_files(archive_path: Path, paths: Sequence[Path]):
    """
    Create a zip archive with the provided files and directories. Files and directories are added
    using their base name, which should therefore all be distinct.
    """

    with ZipFile(archive_path, 'w', ZIP_DEFLATED) as archive:
        for path in paths:
            write_zip_archive_file(archive, path)


def write_zip_archive_file(archive: ZipFile, path: Path):
    """
    Write a file or directory to a zip archive.
    """

    if path.is_file():
        archive.write(path, path.name)
        return

    if path.is_dir():
        archive.write(path, path.name)
        for child_path in sorted(path.rglob('*')):
            archive.write(child_path, Path(path.name) / child_path.relative_to(path))
        return

    raise FileNotFoundError(path)
