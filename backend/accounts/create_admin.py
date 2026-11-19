"""
Create an administrator account: the only way an administrator is made.

Jaadah has no default login. Whoever sets up the accounts server runs
this once (and again for each extra administrator):

    python -m backend.accounts.create_admin --name "Noura Almutairi" --email noura@ksu.edu.sa

It asks for the password twice without showing it on screen, checks it
with the same rules as every account (passwords.py), and stores only
its Argon2id hash. The password never appears in the code, the command
line or the terminal history.

To set up a teammate's laptop in one step, --engineer-email also creates
their traffic engineer account, with the same name and password:

    python -m backend.accounts.create_admin --name "Noura Almutairi" \
        --email noura.admin@ksu.edu.sa --engineer-email noura@ksu.edu.sa
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
    ROLE_ENGINEER,
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
    parser.add_argument("--name", required=True, help='full name, e.g. "Noura Almutairi"')
    parser.add_argument("--email", required=True, help="work email, used to log in")
    parser.add_argument(
        "--engineer-email",
        help="also create a traffic engineer account with this email, "
        "the same name and the same password",
    )
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
    """Create the administrator (and the engineer, if asked); return 0 on success and 1 otherwise.

    ask reads a password without showing it; tests replace ask and say.
    """

    arguments = parse_arguments(sys.argv[1:] if argv is None else argv)
    name = arguments.name.strip()
    email = normalise_email(arguments.email)
    engineer_email = (
        normalise_email(arguments.engineer_email) if arguments.engineer_email else None
    )

    if not name:
        say("Enter a name.")
        return 1
    for address in (email, engineer_email):
        if address is not None and not valid_email(address):
            say("Enter an email address like name@organization.gov.sa.")
            return 1
    if engineer_email == email:
        say("Use a different email for the engineer account.")
        return 1

    storage = AccountStorage(arguments.database)
    storage.initialize()

    # Checked before anything is created, so either both accounts are
    # made or neither is
    for address in (email, engineer_email):
        if address is not None and storage.find_login(address) is not None:
            say(f"An account with {address} already exists. Nothing was created.")
            return 1

    password = ask("Password: ")
    # The password must not be made of the name or of either email
    context = name if engineer_email is None else f"{name} {engineer_email.split('@')[0]}"
    problem = password_problem(password, context, email)
    if problem:
        say(problem)
        return 1

    if ask("Type the password again: ") != password:
        say("The two passwords do not match. Nothing was created.")
        return 1

    created = [(email, ROLE_ADMIN, "Administrator")]
    if engineer_email is not None:
        created.append((engineer_email, ROLE_ENGINEER, "Traffic engineer"))

    for number, (address, role, _) in enumerate(created):
        try:
            storage.create_account(name, address, hash_password(password), role)
        except DuplicateEmailError:
            # Only if someone created this email in the same moment
            done = "Nothing was created." if number == 0 else (
                f"The administrator account ({email}) was created; the engineer account was not."
            )
            say(f"An account with {address} already exists. {done}")
            return 1

    for address, _, label in created:
        say(f"{label} created: {name} ({address}). Log in with this email.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
