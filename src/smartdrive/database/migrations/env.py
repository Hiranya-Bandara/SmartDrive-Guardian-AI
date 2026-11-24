"""Alembic environment.

The application passes its own connection through ``config.attributes["connection"]`` so the
same SQLite pragmas apply. When run from the Alembic CLI the URL comes from ``alembic.ini``
or the ``SMARTDRIVE_DB_URL`` environment variable.
"""

import os

from alembic import context
from sqlalchemy import Connection, create_engine

from smartdrive.database.models import Base

config = context.config
target_metadata = Base.metadata


def _configure_and_run(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    context.configure(
        url=os.environ.get("SMARTDRIVE_DB_URL") or config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    provided = config.attributes.get("connection")
    if provided is not None:
        _configure_and_run(provided)
        return
    url = os.environ.get("SMARTDRIVE_DB_URL") or config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError("Set SMARTDRIVE_DB_URL or sqlalchemy.url to run migrations.")
    engine = create_engine(url)
    with engine.begin() as connection:
        _configure_and_run(connection)
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
