from dataclasses import dataclass, field
from pathlib import Path

import lib.exitcode
from lib.env import Env
from lib.logging import log, log_error_exit, log_warning

ERROR   = 'ERROR'
WARNING = 'WARNING'


@dataclass
class Problem:
    """
    One thing wrong with a submission, tied to the file or row it was found in.
    """

    severity: str
    location: str
    message: str

    @property
    def sort_key(self) -> tuple[str, str]:
        return (self.location, self.message)


@dataclass
class ProblemLog:
    """
    Every problem found while validating a submission.

    Problems are collected rather than raised so that the whole submission can be
    reported at once. A submitter fixing a delivery then sees everything wrong
    with it in a single run, instead of discovering the next problem after each
    correction.
    """

    problems: list[Problem] = field(default_factory=list[Problem])

    def error(self, location: str, message: str):
        self.problems.append(Problem(ERROR, location, message))

    def warning(self, location: str, message: str):
        self.problems.append(Problem(WARNING, location, message))

    @property
    def errors(self) -> list[Problem]:
        return [problem for problem in self.problems if problem.severity == ERROR]

    @property
    def warnings(self) -> list[Problem]:
        return [problem for problem in self.problems if problem.severity == WARNING]

    def has_errors(self) -> bool:
        return any(problem.severity == ERROR for problem in self.problems)

    def report(self, env: Env, png_dir_path: Path, image_count: int):
        """
        Print every problem found, then stop the run if any of them was an error.
        """

        if not self.problems:
            log(env, f"Validated {image_count} image(s). No problems found.")
            return

        ordered = sorted(self.errors, key=lambda problem: problem.sort_key) \
            + sorted(self.warnings, key=lambda problem: problem.sort_key)

        lines = [
            f"  {problem.severity:<7}  {problem.location}: {problem.message}"
            for problem in ordered
        ]

        report = (
            f"{len(self.errors)} error(s) and {len(self.warnings)} warning(s)"
            f" in {png_dir_path}:\n" + "\n".join(lines)
        )

        if not self.errors:
            log_warning(env, report)
            log(env, f"Validated {image_count} image(s). Warnings do not stop the run.")
            return

        log_error_exit(
            env,
            f"{report}\n\nNothing was inserted. Fix the errors and run again.",
            lib.exitcode.INVALID_IMPORT,
        )
