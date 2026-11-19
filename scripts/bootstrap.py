"""Generate local demo credentials without printing secrets. Never overwrites .env."""

import secrets
from pathlib import Path


def main():
    destination = Path(".env")
    try:
        with destination.open("x") as output:
            output.write("DATABASE_URL=sqlite:///./resolvedesk.db\n")
            for role in ("AGENT", "MANAGER", "AUDITOR"):
                output.write(f"{role}_API_KEY={secrets.token_urlsafe(36)}\n")
        destination.chmod(0o600)
    except FileExistsError:
        print(".env already exists; kept unchanged.")
    else:
        print("Created .env with local demo keys. Open it in VS Code; do not commit it.")


if __name__ == "__main__":
    main()
