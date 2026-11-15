"""Alembic environment. The database URL comes from AUREX_DATABASE_URL, never from a file."""

from alembic import context
from sqlalchemy import create_engine

from core.config import get_settings
from pipelines.schema import metadata


def run_migrations() -> None:
    connectable = context.config.attributes.get("connection")
    if connectable is not None:
        context.configure(connection=connectable, target_metadata=metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(get_settings().database_url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()
        connection.commit()


run_migrations()
