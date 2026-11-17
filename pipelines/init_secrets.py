"""Create a deployment's secrets once, in a directory such as a Docker volume (see deploy/docker-compose.edge.yml).

The database password and the session secret are generated here, on the host that uses them, so they never have to
be typed, written into .env or passed through a shell. Values are never printed and existing files are never
replaced, so restarts and upgrades keep them. Run as root it hands each file to the user that reads it.
"""

import os
import secrets
import sys
from pathlib import Path

POSTGRES_UID = 70  # the postgres user in the postgres:*-alpine image
APP_UID = 10001  # the aurex image's user (see Dockerfile)


def _write(path: Path, value: str, uid: int) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
    with os.fdopen(descriptor, "w") as handle:
        handle.write(value)
    if os.geteuid() == 0:
        os.chown(path, uid, uid)


def ensure(directory: Path) -> list[str]:
    """Write whichever secrets are missing and return their names, never their values."""
    directory.mkdir(parents=True, exist_ok=True)
    # The database and the application must agree on the password, so an existing one is reused.
    known = [directory / name for name in ("db_password", "aurex_database_password")]
    password = next((p.read_text().strip() for p in known if p.exists()), "") or secrets.token_hex(24)
    wanted = {
        "db_password": (password, POSTGRES_UID),
        "aurex_database_password": (password, APP_UID),
        "aurex_secret_key": (secrets.token_hex(32), APP_UID),
    }
    created = []
    for name, (value, uid) in wanted.items():
        path = directory / name
        if not path.exists():
            _write(path, value, uid)
            created.append(name)
    return created


def main(argv: list[str]) -> None:
    created = ensure(Path(argv[0] if argv else "/run/aurex-secrets"))
    print("Secrets created: " + (", ".join(created) if created else "none, all present"))


if __name__ == "__main__":
    main(sys.argv[1:])
