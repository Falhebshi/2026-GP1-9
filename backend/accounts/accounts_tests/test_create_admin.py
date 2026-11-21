import sqlite3
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from backend.accounts.create_admin import main
from backend.accounts.passwords import verify_password
from backend.accounts.server import create_app
from backend.accounts.storage import REPO_ROOT, ROLE_ADMIN, AccountStorage

# An artificial administrator, not a real account
NAME = "Noura Almutairi"
EMAIL = "noura@ksu.edu.sa"
PASSWORD = "lantern desert noon falcon"


def run(database, answers, name=NAME, email=EMAIL):
    """Run the command with typed answers; return (exit code, messages)."""

    typed = iter(answers)
    messages = []
    code = main(
        ["--name", name, "--email", email, "--database", str(database)],
        ask=lambda prompt: next(typed),
        say=messages.append,
    )

    return code, messages


@pytest.fixture
def database(tmp_path):
    return tmp_path / "accounts" / "accounts.db"


def test_an_admin_is_created_with_a_hashed_password(database):
    code, messages = run(database, [PASSWORD, PASSWORD])

    assert code == 0
    assert messages == [f"Administrator created: {NAME} ({EMAIL}). Log in with this email."]

    record = AccountStorage(database).find_login(EMAIL)
    assert record.account.role == ROLE_ADMIN
    assert record.account.name == NAME
    assert record.password_hash.startswith("$argon2id$")
    assert PASSWORD not in record.password_hash
    assert verify_password(record.password_hash, PASSWORD)


def test_the_new_admin_can_log_in(database):
    run(database, [PASSWORD, PASSWORD])

    with TestClient(create_app(AccountStorage(database))) as client:
        response = client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})

    assert response.status_code == 200
    assert response.json()["user"]["role"] == "admin"


def test_the_email_is_stored_lowercase(database):
    run(database, [PASSWORD, PASSWORD], email=" Noura@KSU.edu.sa ")

    assert AccountStorage(database).find_login(EMAIL) is not None


@pytest.mark.parametrize(
    ("answers", "message"),
    [
        (["short one", "short one"], "Use at least 15 characters. A short phrase works well."),
        (["1q2w3e4r5t6y7u8i9o0p"] * 2, "This password is too common. Choose another one."),
        (["Noura.Almutairi2026"] * 2, "Do not build the password from the person's name, email or Jaadah."),
        ([PASSWORD, PASSWORD + "s"], "The two passwords do not match. Nothing was created."),
    ],
)
def test_a_refused_password_creates_nothing(database, answers, message):
    code, messages = run(database, answers)

    assert code == 1
    assert messages == [message]
    assert not database.exists() or AccountStorage(database).find_login(EMAIL) is None


@pytest.mark.parametrize(
    ("name", "email", "message"),
    [
        ("   ", EMAIL, "Enter a name."),
        (NAME, "noura.ksu.edu.sa", "Enter an email address like name@organization.gov.sa."),
    ],
)
def test_a_missing_name_or_bad_email_is_refused_before_the_password(
    database, name, email, message,
):
    asked = []
    code = main(
        ["--name", name, "--email", email, "--database", str(database)],
        ask=lambda prompt: asked.append(prompt) or PASSWORD,
        say=lambda text: asked.append(text),
    )

    assert code == 1
    assert asked == [message]           # no password was asked for


def test_an_email_that_already_has_an_account_is_refused(database):
    run(database, [PASSWORD, PASSWORD])

    code, messages = run(database, [PASSWORD, PASSWORD], name="Someone Else")

    assert code == 1
    assert messages == [f"An account with {EMAIL} already exists. Nothing was created."]


def test_the_command_runs_as_a_module():
    result = subprocess.run(
        [sys.executable, "-m", "backend.accounts.create_admin", "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "--name" in result.stdout and "--email" in result.stdout


# ============================================================
# ADMINISTRATOR AND ENGINEER IN ONE COMMAND (--engineer-email)
# ============================================================

ENGINEER_EMAIL = "noura.engineer@ksu.edu.sa"


def run_both(database, answers, engineer_email=ENGINEER_EMAIL, email=EMAIL):
    typed = iter(answers)
    messages = []
    code = main(
        ["--name", NAME, "--email", email, "--engineer-email", engineer_email,
         "--database", str(database)],
        ask=lambda prompt: next(typed),
        say=messages.append,
    )
    return code, messages


def test_engineer_email_also_creates_an_engineer_with_the_same_password(database):
    code, messages = run_both(database, [PASSWORD, PASSWORD])

    assert code == 0
    assert messages == [
        f"Administrator created: {NAME} ({EMAIL}). Log in with this email.",
        f"Traffic engineer created: {NAME} ({ENGINEER_EMAIL}). Log in with this email.",
    ]
    storage = AccountStorage(database)
    admin = storage.find_login(EMAIL)
    engineer = storage.find_login(ENGINEER_EMAIL)
    assert (admin.account.role, engineer.account.role) == (ROLE_ADMIN, "engineer")
    assert engineer.account.name == NAME
    assert verify_password(engineer.password_hash, PASSWORD)
    # Each hash has its own salt
    assert admin.password_hash != engineer.password_hash


def test_both_accounts_can_log_in(database):
    run_both(database, [PASSWORD, PASSWORD])

    with TestClient(create_app(AccountStorage(database))) as client:
        roles = [
            client.post("/auth/login", json={"email": address, "password": PASSWORD})
            .json()["user"]["role"]
            for address in (EMAIL, ENGINEER_EMAIL)
        ]

    assert roles == ["admin", "engineer"]


def test_the_two_emails_must_differ(database):
    code, messages = run_both(database, [PASSWORD, PASSWORD], engineer_email=" NOURA@ksu.edu.sa ")

    assert code == 1
    assert messages == ["Use a different email for the engineer account."]


def test_a_bad_engineer_email_is_refused_before_the_password(database):
    asked = []
    code = main(
        ["--name", NAME, "--email", EMAIL, "--engineer-email", "not-an-email",
         "--database", str(database)],
        ask=lambda prompt: asked.append(prompt) or PASSWORD,
        say=asked.append,
    )

    assert code == 1
    assert asked == ["Enter an email address like name@organization.gov.sa."]


@pytest.mark.parametrize("taken", [EMAIL, ENGINEER_EMAIL])
def test_if_either_email_is_taken_nothing_is_created(database, taken):
    storage = AccountStorage(database)
    storage.initialize()
    storage.create_account("Someone Else", taken, "$argon2id$x", ROLE_ADMIN)

    code, messages = run_both(database, [PASSWORD, PASSWORD])

    assert code == 1
    assert messages == [f"An account with {taken} already exists. Nothing was created."]
    other = ENGINEER_EMAIL if taken == EMAIL else EMAIL
    assert storage.find_login(other) is None


def test_the_password_cannot_be_made_of_the_engineer_email_either(database):
    # "noura.engineer" gives the words noura and engineer
    code, messages = run_both(database, ["engineer engineer 2026"] * 2)

    assert code == 1
    assert messages == ["Do not build the password from the person's name, email or Jaadah."]


def test_without_engineer_email_only_the_administrator_is_created(database):
    run(database, [PASSWORD, PASSWORD])

    with sqlite3.connect(database) as connection:
        roles = connection.execute("SELECT role FROM accounts").fetchall()

    assert roles == [("admin",)]
