import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from backend.accounts.create_admin import main
from backend.accounts.passwords import verify_password
from backend.accounts.server import create_app
from backend.accounts.storage import REPO_ROOT, ROLE_ADMIN, AccountStorage

# An artificial administrator, not a real account
NAME = "Aliyah Alharbi"
EMAIL = "aliyah@ksu.edu.sa"
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
    run(database, [PASSWORD, PASSWORD], email=" Aliyah@KSU.edu.sa ")

    assert AccountStorage(database).find_login(EMAIL) is not None


@pytest.mark.parametrize(
    ("answers", "message"),
    [
        (["short one", "short one"], "Use at least 15 characters. A short phrase works well."),
        (["1q2w3e4r5t6y7u8i9o0p"] * 2, "This password is too common. Choose another one."),
        (["Aliyah.Alharbi2026"] * 2, "Do not build the password from the person's name, email or Jaadah."),
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
        (NAME, "aliyah.ksu.edu.sa", "Enter an email address like name@organization.gov.sa."),
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
