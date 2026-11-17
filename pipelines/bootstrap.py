"""Prepare a deployment: migrate the schema, apply security policies, seed the catalog. Safe to re-run."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import update

from core.config import get_settings
from core.db import apply_security, get_engine, system_session
from modules.datalab import catalog
from modules.graph import seed as graph_seed
from modules.logging import log
from security.models import User

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
        promoted = sync_platform_admins(session)
    log("pipeline", "bootstrap.completed", platform_admins_promoted=promoted)


def sync_platform_admins(session) -> int:
    """Give existing accounts with a configured admin email platform rights. Never removes them."""
    emails = [e.strip().lower() for e in get_settings().platform_admin_emails if e.strip()]
    if not emails:
        return 0
    return session.execute(
        update(User).where(User.email.in_(emails), User.is_platform_admin.is_(False)).values(is_platform_admin=True)
    ).rowcount


if __name__ == "__main__":
    bootstrap()
