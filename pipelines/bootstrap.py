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
        admins = sync_platform_admins(session)
    log(
        "pipeline",
        "bootstrap.completed",
        platform_admins_promoted=admins["promoted"],
        platform_admins_demoted=admins["demoted"],
    )


def sync_platform_admins(session) -> dict[str, int]:
    """Make the configured admin emails the complete list of platform administrators.

    Accounts with a listed email get platform rights and every other account loses them, so the list decides who
    administers the deployment. With no list configured nothing changes: a local deployment keeps the administrator
    its first account became.
    """
    emails = [e.strip().lower() for e in get_settings().platform_admin_emails if e.strip()]
    if not emails:
        return {"promoted": 0, "demoted": 0}
    promoted = session.execute(
        update(User).where(User.email.in_(emails), User.is_platform_admin.is_(False)).values(is_platform_admin=True)
    ).rowcount
    demoted = session.execute(
        update(User).where(User.email.not_in(emails), User.is_platform_admin.is_(True)).values(is_platform_admin=False)
    ).rowcount
    return {"promoted": promoted, "demoted": demoted}


if __name__ == "__main__":
    bootstrap()
