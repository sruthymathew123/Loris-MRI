from dataclasses import dataclass
from pathlib import Path


@dataclass
class Args:
    """
    Command line arguments of the PNG dataset import pipeline.
    """

    png_dir_path: Path
    subject_label: str | None
    session_label: str | None
    scan_type_name: str | None
    validate_only: bool
    create_pic: bool
    verbose: bool
