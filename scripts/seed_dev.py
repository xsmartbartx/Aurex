"""Create a local demonstration account. Development only: refuses to run in production."""

import sys

from sqlalchemy import select

from core.config import get_settings
from core.db import system_session
from security import auth
from security.models import User

EMAIL = "demo@example.com"
PASSWORD = "Aurex-demo-2026"  # noqa: S105 - local demonstration account, never used in production
ORGANIZATION = "Demo Research"


def main() -> None:
    if get_settings().environment == "production":
        sys.exit("The demonstration account is not created in production.")
    with system_session() as session:
        user = session.scalar(select(User).where(User.email == EMAIL))
        if user is None:
            auth.sign_up(
                session, email=EMAIL, password=PASSWORD, display_name="Demo Analyst", organization=ORGANIZATION
            )
            user = session.scalar(select(User).where(User.email == EMAIL))
        user.is_platform_admin = True
    print(f"Demonstration account ready: {EMAIL} (password in scripts/seed_dev.py)")


if __name__ == "__main__":
    main()
