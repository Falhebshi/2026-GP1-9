import math
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import backend.accounts.server as server
from backend.accounts.passphrase import (
    WORDLIST_SHA256,
    WORDS,
    generate_passphrase,
    wordlist_sha256,
)
from backend.accounts.passwords import hash_password, password_problem, verify_password
from backend.accounts.server import (
    ADMINS_ONLY,
    EMAIL_INVALID,
    EMAIL_TAKEN,
    NAME_MISSING,
    NAME_TOO_LONG,
    NOT_LOGGED_IN,
    create_app,
)
from backend.accounts.storage import ROLE_ADMIN, ROLE_ENGINEER, AccountStorage

RIYADH = timezone(timedelta(hours=3))
START = datetime(2026, 11, 18, 9, 0, tzinfo=RIYADH)

# Artificial accounts, not real people
NOURA = {"email": "noura@ksu.edu.sa", "password": "lantern desert noon falcon"}
SARA = {"email": "sara.q@moh.gov.sa", "password": "orbit maple quiet river"}
NEW = {"name": "Omar Alharbi", "email": "omar@ksu.edu.sa", "password": "copper valley storm lamp"}


@pytest.fixture
def storage(tmp_path):
    storage = AccountStorage(tmp_path / "accounts.db", now=lambda: START)
    storage.initialize()
    storage.create_account(
        "Noura Almutairi", NOURA["email"], hash_password(NOURA["password"]), ROLE_ADMIN,
    )
    return storage


@pytest.fixture
def client(storage):
    with TestClient(create_app(storage)) as client:
        yield client


@pytest.fixture
def admin(client):
    """The client, logged in as the administrator."""

    client.post("/auth/login", json=NOURA)
    return client


def add_engineer(storage, name, email, password="orbit maple quiet river"):
    return storage.create_account(name, email, hash_password(password), ROLE_ENGINEER)


# ============================================================
# ADMINISTRATORS ONLY
# ============================================================

@pytest.mark.parametrize(
    ("method", "path"),
    [("get", "/admin/engineers"), ("post", "/admin/engineers"), ("get", "/admin/passphrase")],
)
def test_without_a_session_admin_endpoints_answer_401(client, method, path):
    response = getattr(client, method)(path, **({"json": NEW} if method == "post" else {}))

    assert response.status_code == 401
    assert response.json()["detail"] == NOT_LOGGED_IN


@pytest.mark.parametrize(
    ("method", "path"),
    [("get", "/admin/engineers"), ("post", "/admin/engineers"), ("get", "/admin/passphrase")],
)
def test_an_engineer_gets_403_from_admin_endpoints(client, storage, method, path):
    add_engineer(storage, "Sara Alqahtani", SARA["email"], SARA["password"])
    client.post("/auth/login", json=SARA)

    response = getattr(client, method)(path, **({"json": NEW} if method == "post" else {}))

    assert response.status_code == 403
    assert response.json()["detail"] == ADMINS_ONLY


def test_an_engineer_cannot_create_an_account(client, storage):
    add_engineer(storage, "Sara Alqahtani", SARA["email"], SARA["password"])
    client.post("/auth/login", json=SARA)

    client.post("/admin/engineers", json=NEW)

    assert storage.find_login(NEW["email"]) is None


# ============================================================
# LIST OF ENGINEERS (ADM-02)
# ============================================================

def test_no_engineers_gives_an_empty_list(admin):
    assert admin.get("/admin/engineers").json() == {"engineers": []}


def test_engineers_are_listed_with_name_email_and_status(admin, storage):
    sara = add_engineer(storage, "Sara Alqahtani", SARA["email"])

    engineer = admin.get("/admin/engineers").json()["engineers"][0]

    assert engineer == {
        "id": sara.id,
        "name": "Sara Alqahtani",
        "email": "sara.q@moh.gov.sa",
        "status": "active",
        "created_at": "2026-11-18T06:00:00+00:00",    # 09:00 Riyadh
    }


def test_administrators_are_not_listed(admin):
    names = [e["name"] for e in admin.get("/admin/engineers").json()["engineers"]]

    assert "Noura Almutairi" not in names


def test_engineers_are_ordered_by_name_ignoring_case(admin, storage):
    # By email the order would be Sara, Omar, bader; with case it would be
    # Omar, Sara, bader (capitals sort before small letters)
    add_engineer(storage, "Sara Alqahtani", "a.sara@moh.gov.sa")
    add_engineer(storage, "Omar Alharbi", "b.omar@ksu.edu.sa")
    add_engineer(storage, "bader Alotaibi", "c.bader@moh.gov.sa")

    names = [e["name"] for e in admin.get("/admin/engineers").json()["engineers"]]

    assert names == ["bader Alotaibi", "Omar Alharbi", "Sara Alqahtani"]


def test_an_inactive_engineer_is_listed_as_inactive(admin, storage):
    add_engineer(storage, "Sara Alqahtani", SARA["email"])
    # Deactivation itself comes with ADM-03; set the status directly here
    with sqlite3.connect(storage.database_path) as connection:
        connection.execute("UPDATE accounts SET status = 'inactive' WHERE role = 'engineer'")

    assert admin.get("/admin/engineers").json()["engineers"][0]["status"] == "inactive"


def test_the_list_never_contains_password_hashes(admin, storage):
    add_engineer(storage, "Sara Alqahtani", SARA["email"])

    assert "argon2" not in admin.get("/admin/engineers").text


# ============================================================
# CREATE AN ENGINEER ACCOUNT (ADM-01)
# ============================================================

def test_a_new_engineer_is_created_with_the_engineer_role(admin, storage):
    response = admin.post("/admin/engineers", json=NEW)

    assert response.status_code == 201
    created = response.json()
    assert (created["name"], created["email"], created["status"]) == (
        "Omar Alharbi", "omar@ksu.edu.sa", "active",
    )
    record = storage.find_login(NEW["email"])
    assert record.account.role == ROLE_ENGINEER


def test_the_response_never_contains_the_password(admin):
    response = admin.post("/admin/engineers", json=NEW)

    assert NEW["password"] not in response.text
    assert "argon2" not in response.text
    assert set(response.json()) == {"id", "name", "email", "status", "created_at"}


def test_the_password_is_stored_as_a_salted_argon2id_hash(admin, storage):
    admin.post("/admin/engineers", json=NEW)

    stored = storage.find_login(NEW["email"]).password_hash
    assert stored.startswith("$argon2id$v=19$m=19456,t=2,p=1$")
    assert NEW["password"] not in stored
    assert verify_password(stored, NEW["password"])


def test_the_new_account_appears_in_the_list(admin):
    admin.post("/admin/engineers", json=NEW)

    emails = [e["email"] for e in admin.get("/admin/engineers").json()["engineers"]]
    assert emails == ["omar@ksu.edu.sa"]


def test_the_new_engineer_can_log_in(admin, storage):
    admin.post("/admin/engineers", json=NEW)

    with TestClient(create_app(storage)) as engineer:
        response = engineer.post(
            "/auth/login", json={"email": NEW["email"], "password": NEW["password"]},
        )

    assert response.status_code == 200
    assert response.json()["user"]["role"] == "engineer"


def test_name_spaces_are_trimmed_and_email_is_lowercased(admin):
    created = admin.post(
        "/admin/engineers",
        json={**NEW, "name": "  Omar Alharbi ", "email": " Omar@KSU.edu.sa "},
    ).json()

    assert (created["name"], created["email"]) == ("Omar Alharbi", "omar@ksu.edu.sa")


@pytest.mark.parametrize(
    ("changes", "field", "message"),
    [
        ({"name": "   "}, "name", NAME_MISSING),
        ({"name": "x" * 101}, "name", NAME_TOO_LONG),
        ({"email": ""}, "email", EMAIL_INVALID),
        ({"email": "omar.ksu.edu.sa"}, "email", EMAIL_INVALID),
        ({"email": "omar@ksu"}, "email", EMAIL_INVALID),
        ({"email": "a" * 245 + "@ksu.edu.sa"}, "email", EMAIL_INVALID),      # 256
        ({"password": "short one"}, "password",
         "Use at least 15 characters. A short phrase works well."),
        ({"password": "1q2w3e4r5t6y7u8i9o0p"}, "password",
         "This password is too common. Choose another one."),
        ({"password": "Omar.Alharbi.2026"}, "password",
         "Do not build the password from the person's name, email or Jaadah."),
        ({"password": "x" * 65}, "password", "Use at most 64 characters."),
    ],
)
def test_invalid_details_are_refused_with_a_message_for_that_field(
    admin, storage, changes, field, message,
):
    response = admin.post("/admin/engineers", json={**NEW, **changes})

    assert response.status_code == 400
    assert response.json()["detail"] == {"field": field, "message": message}
    assert admin.get("/admin/engineers").json() == {"engineers": []}


def test_an_email_that_already_has_an_account_is_refused(admin):
    admin.post("/admin/engineers", json=NEW)

    response = admin.post(
        "/admin/engineers",
        json={**NEW, "name": "Someone Else", "email": "OMAR@ksu.edu.sa"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == {"field": "email", "message": EMAIL_TAKEN}
    assert len(admin.get("/admin/engineers").json()["engineers"]) == 1


def test_an_administrator_email_cannot_be_reused_for_an_engineer(admin):
    response = admin.post("/admin/engineers", json={**NEW, "email": NOURA["email"]})

    assert response.status_code == 409


def test_a_refused_password_is_never_hashed(admin, monkeypatch):
    hashed = []
    monkeypatch.setattr(server, "hash_password", lambda p: hashed.append(p) or "x")

    admin.post("/admin/engineers", json={**NEW, "password": "short one"})

    assert hashed == []


# ============================================================
# PASSPHRASE (Generate button)
# ============================================================

def test_the_word_list_is_eff_s_exact_file():
    assert wordlist_sha256() == WORDLIST_SHA256
    assert len(WORDS) == 7776
    assert len(set(WORDS)) == 7776
    assert (WORDS[0], WORDS[-1]) == ("abacus", "zoom")


def test_a_passphrase_is_five_list_words_joined_by_hyphens(monkeypatch):
    picks = iter(["lantern", "orbit", "maple", "quiet", "river"])
    monkeypatch.setattr("backend.accounts.passphrase.secrets.choice", lambda words: next(picks))

    assert generate_passphrase() == "lantern-orbit-maple-quiet-river"


def test_five_words_give_about_65_bits():
    assert round(5 * math.log2(len(WORDS)), 1) == 64.6


def test_passphrases_always_fit_the_length_rule():
    shortest = min(len(w) for w in WORDS)
    longest = max(len(w) for w in WORDS)

    # 5 words and 4 hyphens
    assert 5 * shortest + 4 == 19 >= 15
    assert 5 * longest + 4 == 49 <= 64


def test_generated_passphrases_are_accepted_and_differ():
    phrases = {generate_passphrase() for _ in range(200)}

    assert len(phrases) == 200
    for phrase in phrases:
        assert password_problem(phrase, NEW["name"], NEW["email"]) is None


def test_the_passphrase_endpoint_gives_a_new_one_each_time(admin):
    first = admin.get("/admin/passphrase").json()["passphrase"]
    second = admin.get("/admin/passphrase").json()["passphrase"]

    assert first != second
    assert len(first.split("-")) >= 5


# ============================================================
# ACTIVATE AND DEACTIVATE (ADM-03)
# ============================================================

def set_status(client, account_id, new_status):
    return client.post(f"/admin/engineers/{account_id}/status", json={"status": new_status})


def logged_in_engineer(storage, email=SARA["email"], password=SARA["password"]):
    """A second browser, logged in as the engineer."""

    engineer = TestClient(create_app(storage))
    engineer.__enter__()
    engineer.post("/auth/login", json={"email": email, "password": password})
    return engineer


def test_deactivating_makes_the_status_inactive(admin, storage):
    sara = add_engineer(storage, "Sara Alqahtani", SARA["email"], SARA["password"])

    response = set_status(admin, sara.id, "inactive")

    assert response.status_code == 200
    assert response.json()["status"] == "inactive"
    assert admin.get("/admin/engineers").json()["engineers"][0]["status"] == "inactive"


def test_deactivating_ends_the_engineer_s_session_at_once(admin, storage):
    sara = add_engineer(storage, "Sara Alqahtani", SARA["email"], SARA["password"])
    engineer = logged_in_engineer(storage)
    assert engineer.get("/auth/me").status_code == 200

    set_status(admin, sara.id, "inactive")

    assert engineer.get("/auth/me").status_code == 401
    with sqlite3.connect(storage.database_path) as connection:
        sessions = connection.execute(
            "SELECT COUNT(*) FROM sessions WHERE account_id = ?", (sara.id,),
        ).fetchone()
    assert sessions == (0,)
    engineer.__exit__(None, None, None)


def test_a_deactivated_engineer_cannot_log_in(admin, storage):
    sara = add_engineer(storage, "Sara Alqahtani", SARA["email"], SARA["password"])
    set_status(admin, sara.id, "inactive")

    with TestClient(create_app(storage)) as engineer:
        response = engineer.post("/auth/login", json=SARA)

    assert response.status_code == 403


def test_reactivating_lets_the_engineer_log_in_again(admin, storage):
    sara = add_engineer(storage, "Sara Alqahtani", SARA["email"], SARA["password"])
    set_status(admin, sara.id, "inactive")

    response = set_status(admin, sara.id, "active")

    assert response.json()["status"] == "active"
    with TestClient(create_app(storage)) as engineer:
        assert engineer.post("/auth/login", json=SARA).status_code == 200


def test_reactivating_does_not_end_other_sessions(admin, storage):
    sara = add_engineer(storage, "Sara Alqahtani", SARA["email"], SARA["password"])
    engineer = logged_in_engineer(storage)

    set_status(admin, sara.id, "active")          # already active

    assert engineer.get("/auth/me").status_code == 200
    engineer.__exit__(None, None, None)


def test_deactivating_one_engineer_leaves_the_others(admin, storage):
    sara = add_engineer(storage, "Sara Alqahtani", SARA["email"], SARA["password"])
    add_engineer(storage, "Omar Alharbi", NEW["email"], NEW["password"])
    omar = logged_in_engineer(storage, NEW["email"], NEW["password"])

    set_status(admin, sara.id, "inactive")

    assert omar.get("/auth/me").status_code == 200
    statuses = {e["name"]: e["status"] for e in admin.get("/admin/engineers").json()["engineers"]}
    assert statuses == {"Sara Alqahtani": "inactive", "Omar Alharbi": "active"}
    omar.__exit__(None, None, None)


def test_the_admin_s_own_session_is_not_affected(admin, storage):
    sara = add_engineer(storage, "Sara Alqahtani", SARA["email"])

    set_status(admin, sara.id, "inactive")

    assert admin.get("/auth/me").status_code == 200


def test_an_unknown_account_answers_no_longer_exists(admin):
    response = set_status(admin, "0" * 32, "inactive")

    assert response.status_code == 404
    assert response.json()["detail"] == "This account no longer exists."


def test_an_administrator_cannot_be_deactivated(admin, storage):
    noura = storage.find_login(NOURA["email"]).account

    response = set_status(admin, noura.id, "inactive")

    assert response.status_code == 404
    assert storage.get_account(noura.id).status == "active"


def test_only_active_or_inactive_are_accepted(admin, storage):
    sara = add_engineer(storage, "Sara Alqahtani", SARA["email"])

    response = set_status(admin, sara.id, "suspended")

    assert response.status_code == 422
    assert storage.get_account(sara.id).status == "active"


def test_an_engineer_cannot_change_a_status(client, storage):
    sara = add_engineer(storage, "Sara Alqahtani", SARA["email"], SARA["password"])
    omar = add_engineer(storage, "Omar Alharbi", NEW["email"], NEW["password"])
    client.post("/auth/login", json=SARA)

    assert set_status(client, omar.id, "inactive").status_code == 403
    assert storage.get_account(omar.id).status == "active"
