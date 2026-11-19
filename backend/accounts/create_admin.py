"""
Create an administrator account: the only way an administrator is made.

Jaadah has no default login. Whoever sets up the accounts server runs
this once (and again for each extra administrator):

    python -m backend.accounts.create_admin --name "Aliyah Alharbi" --email aliyah@ksu.edu.sa

It asks for the password twice without showing it on screen, checks it
with the same rules as every account (passwords.py), and stores only
its Argon2id hash. The password never appears in the code, the command
line or the terminal history.
"""

import argparse
import getpass
import sys
from collections.abc import Callable
from pathlib import Path

from backend.accounts.passwords import hash_password, password_problem
from backend.accounts.storage import (
    DEFAULT_DATABASE,
    ROLE_ADMIN,
    AccountStorage,
    DuplicateEmailError,
    normalise_email,
    valid_email,
)


def parse_arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m backend.accounts.create_admin",
        description="Create a Jaadah administrator account.",
    )
    parser.add_argument("--name", required=True, help='full name, e.g. "Aliyah Alharbi"')
    parser.add_argument("--email", required=True, help="work email, used to log in")
    parser.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DATABASE,
        help="accounts database (default: data/accounts/accounts.db)",
    )

    return parser.parse_args(argv)


def main(
    argv: list[str] | None = None,
    ask: Callable[[str], str] = getpass.getpass,
    say: Callable[[str], None] = print,
) -> int:
    """Create the administrator; return 0 on success and 1 otherwise.

    ask reads a password without showing it; tests replace ask and say.
    """

    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)
    name = arguments.name.strip()
    email = normalise_email(arguments.email)

    if not name:
        say("Enter a name.")
        return 1
    if not valid_email(email):
        say("Enter an email address like name@organization.gov.sa.")
        return 1

    password = ask("Password: ")
    problem = password_problem(password, name, email)
    if problem:
        say(problem)
        return 1

    if ask("Type the password again: ") != password:
        say("The two passwords do not match. Nothing was created.")
        return 1

    storage = AccountStorage(arguments.database)
    storage.initialize()

    try:
        storage.create_account(name, email, hash_password(password), ROLE_ADMIN)
    except DuplicateEmailError:
        say(f"An account with {email} already exists. Nothing was created.")
        return 1

    say(f"Administrator created: {name} ({email}). Log in with this email.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
