from lib.exitcode import SUCCESS
from tests.util.run_integration_script import run_integration_script


def test_successful_run():
    """
    Test running the ORM/SQL schema sync check script.
    """

    process = run_integration_script([
        'python/scripts/check_orm_sql_sync.py',
    ])

    assert process.returncode == SUCCESS
    assert process.stdout == "ORM/SQL schema sync check passed.\n"
    assert process.stderr == ""
