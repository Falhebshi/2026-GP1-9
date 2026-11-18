import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import backend.accounts.server as server
from backend.accounts.passwords import hash_password
from backend.accounts.server import (
    DEACTIVATED,
    INCORRECT,
    NOT_LOGGED_IN,
    PAUSED,
    SESSION_COOKIE,
    create_app,
)
from backend.accounts.storage import ROLE_ADMIN, ROLE_ENGINEER, AccountStorage

RIYADH = timezone(timedelta(hours=3))
START = datetime(2026, 11, 18, 9, 0, tzinfo=RIYADH)     # Wednesday 09:00

# Artificial accounts, not real people
SARA = {"email": "sara.q@moh.gov.sa", "password": "orbit maple quiet river"}
ALIYAH = {"email": "aliyah@ksu.edu.sa", "password": "lantern desert noon falcon"}


class Clock:
    def __init__(self, moment):
        self.moment = moment

    def __call__(self):
        return self.moment


@pytest.fixture
def clock():
    return Clock(START)


@pytest.fixture
def storage(tmp_path, clock):
    storage = AccountStorage(tmp_path / "accounts.db", now=clock)
    storage.initialize()
    storage.create_account(
        "Sara Alqahtani", SARA["email"], hash_password(SARA["password"]), ROLE_ENGINEER,
    )
    storage.create_account(
        "Aliyah Alharbi", ALIYAH["email"], hash_password(ALIYAH["password"]), ROLE_ADMIN,
    )
    return storage


@pytest.fixture
def client(storage):
    with TestClient(create_app(storage)) as client:
        yield client


def log_in(client, email, password):
    return client.post("/auth/login", json={"email": email, "password": password})


def deactivate(storage, email):
    # Deactivation itself comes with ADM-03; set the status directly here
    with sqlite3.connect(storage.database_path) as connection:
        connection.execute(
            "UPDATE accounts SET status = 'inactive' WHERE email = ?", (email,),
        )


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


# ============================================================
# LOGIN (PBI 31)
# ============================================================

def test_an_engineer_logs_in_and_gets_a_session_cookie(client):
    response = log_in(client, **SARA)

    assert response.status_code == 200
    user = response.json()["user"]
    assert user["name"] == "Sara Alqahtani"
    assert user["email"] == SARA["email"]
    assert user["role"] == "engineer"
    assert set(user) == {"id", "name", "email", "role"}
    assert SESSION_COOKIE in client.cookies


def test_an_admin_logs_in_with_the_admin_role(client):
    response = log_in(client, **ALIYAH)

    assert response.json()["user"]["role"] == "admin"


def test_the_cookie_is_http_only_strict_and_lasts_8_hours(client):
    cookie = log_in(client, **SARA).headers["set-cookie"].lower()

    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert "max-age=28800" in cookie        # 8 x 60 x 60
    assert "path=/" in cookie


def test_the_email_case_does_not_matter(client):
    response = log_in(client, "SARA.Q@MOH.gov.sa", SARA["password"])

    assert response.status_code == 200


def test_the_password_hash_is_never_sent(client, storage):
    stored_hash = storage.find_login(SARA["email"]).password_hash
    response = log_in(client, **SARA)

    assert stored_hash not in response.text
    assert "argon2" not in client.get("/auth/me").text


@pytest.mark.parametrize(
    ("email", "password"),
    [
        (SARA["email"], "orbit maple quiet rivers"),   # wrong password
        ("nobody@moh.gov.sa", SARA["password"]),       # no such account
    ],
)
def test_wrong_details_get_one_message_and_no_cookie(client, email, password):
    response = log_in(client, email, password)

    assert response.status_code == 401
    assert response.json()["detail"] == INCORRECT
    assert SESSION_COOKIE not in client.cookies


def test_an_unknown_email_still_checks_a_password(client, monkeypatch):
    checks = []
    original = server.verify_password
    monkeypatch.setattr(
        server, "verify_password",
        lambda stored, password: checks.append(1) or original(stored, password),
    )

    log_in(client, "nobody@moh.gov.sa", "anything at all here")

    assert checks == [1]


# ============================================================
# DEACTIVATED ACCOUNTS (PBI 31, ADM-03)
# ============================================================

def test_deactivated_with_the_right_password_is_told_why(client, storage):
    deactivate(storage, SARA["email"])

    response = log_in(client, **SARA)

    assert response.status_code == 403
    assert response.json()["detail"] == DEACTIVATED
    assert SESSION_COOKIE not in client.cookies


def test_deactivated_with_a_wrong_password_sees_the_usual_message(client, storage):
    deactivate(storage, SARA["email"])

    response = log_in(client, SARA["email"], "a stranger guessing here")

    assert response.status_code == 401
    assert response.json()["detail"] == INCORRECT


def test_deactivation_ends_a_session_already_open(client, storage):
    log_in(client, **SARA)
    assert client.get("/auth/me").status_code == 200

    deactivate(storage, SARA["email"])

    assert client.get("/auth/me").status_code == 401


# ============================================================
# TOO MANY WRONG PASSWORDS
# ============================================================

def wrong(client):
    return log_in(client, SARA["email"], "not the right password")


def test_the_5th_wrong_password_pauses_login_for_30_minutes(client, clock):
    for _ in range(4):
        assert wrong(client).status_code == 401

    fifth = wrong(client)
    assert fifth.status_code == 429
    assert fifth.json()["detail"] == PAUSED == "Too many attempts. Try again in 30 minutes."

    # Even the right password waits until the pause ends
    clock.moment = START + timedelta(minutes=29, seconds=59)
    assert log_in(client, **SARA).status_code == 429

    clock.moment = START + timedelta(minutes=30)
    assert log_in(client, **SARA).status_code == 200


def test_the_right_password_resets_the_count(client):
    for _ in range(4):
        wrong(client)
    assert log_in(client, **SARA).status_code == 200

    for _ in range(4):
        assert wrong(client).status_code == 401


def test_a_pause_on_one_account_does_not_affect_another(client):
    for _ in range(5):
        wrong(client)

    assert log_in(client, **ALIYAH).status_code == 200


# ============================================================
# WHO IS LOGGED IN, AND LOGOUT (PBI 32)
# ============================================================

def test_me_needs_a_session(client):
    response = client.get("/auth/me")

    assert response.status_code == 401
    assert response.json()["detail"] == NOT_LOGGED_IN


def test_me_returns_the_logged_in_user(client):
    login_user = log_in(client, **SARA).json()["user"]

    assert client.get("/auth/me").json()["user"] == login_user


def test_logout_ends_the_session_and_removes_the_cookie(client):
    log_in(client, **SARA)
    token = client.cookies[SESSION_COOKIE]

    response = client.post("/auth/logout")

    assert response.status_code == 204
    assert SESSION_COOKIE not in client.cookies
    # The old token no longer works, even if sent again
    client.cookies.set(SESSION_COOKIE, token)
    assert client.get("/auth/me").status_code == 401


def test_logout_without_a_session_is_harmless(client):
    assert client.post("/auth/logout").status_code == 204


def test_a_busy_session_ends_after_8_hours(client, clock):
    log_in(client, **SARA)

    # The website asks /auth/me on every page change; here every 20 minutes
    for minutes in range(20, 8 * 60, 20):
        clock.moment = START + timedelta(minutes=minutes)
        assert client.get("/auth/me").status_code == 200, minutes

    clock.moment = START + timedelta(hours=8)
    assert client.get("/auth/me").status_code == 401


def test_30_minutes_without_a_request_end_the_session(client, clock):
    log_in(client, **SARA)                                  # 09:00

    clock.moment = START + timedelta(minutes=29, seconds=59)
    assert client.get("/auth/me").status_code == 200

    clock.moment = START + timedelta(minutes=59, seconds=59)  # 30:00 later
    response = client.get("/auth/me")
    assert response.status_code == 401
    assert response.json()["detail"] == NOT_LOGGED_IN


def test_a_made_up_token_is_refused(client):
    client.cookies.set(SESSION_COOKIE, "made-up-token")

    assert client.get("/auth/me").status_code == 401
