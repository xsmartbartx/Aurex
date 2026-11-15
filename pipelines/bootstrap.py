"""Prepare a deployment: migrate the schema, apply security policies, seed the catalog. Safe to re-run."""

from pathlib import Path

from alembic import command
from alembic.config import Config

from core.config import get_settings
from core.db import apply_security, get_engine, system_session
from modules.datalab import catalog
from modules.graph import seed as graph_seed
from modules.logging import log

ROOT = Path(__file__).resolve().parent.parent


def migrate() -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(config, "head")


def bootstrap() -> None:
    get_settings().assert_safe()
    migrate()
    with get_engine().begin() as connection:
        apply_security(connection)
    with system_session() as session:
        catalog.seed(session)
        graph_seed.seed(session)
    log("pipeline", "bootstrap.completed")


if __name__ == "__main__":
    bootstrap()
