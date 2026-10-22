from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from lib.config_file import load_config
from lib.db.base import Base
from lib.db.connect import get_database_engine


def create_test_database():
    """
    Create an empty in-memory database to be used for unit tests.
    """

    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    return Session(engine)


def get_integration_database_engine():
    """
    Get an SQLAlchemy engine for the integration testing database using the configuration from the
    Python configuration file.
    """

    # C-BIG OVERRIDE START
    # Remove when adopting the new config system
    # - https://github.com/aces/loris-mri/pull/1317
    # - https://github.com/aces/loris-mri/pull/1318
    config = load_config('database_config.py')
    # C-BIG OVERRIDE END
    return get_database_engine(config.mysql)


def get_integration_database_session():
    """
    Get an SQLAlchemy session for the integration testing database using the configuration from the
    Python configuration file.
    """

    return Session(get_integration_database_engine())
