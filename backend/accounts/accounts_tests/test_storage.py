import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from backend.accounts.storage import (
    DEFAULT_DATABASE,
    REPO_ROOT,
    ROLE_ADMIN,
    ROLE_ENGINEER,
    LOGIN_PAUSE,
    MAX_FAILED_LOGINS,
    SESSION_IDLE_LIMIT,
    SESSION_LIFETIME,
    STATUS_ACTIVE,
    AccountStorage,
    DuplicateEmailError,
    token_digest,
)

RIYADH = timezone(timedelta(hours=3))
# Wednesday 09:00 in Riyadh
START = datetime(2026, 11, 18, 9, 0, tzinfo=RIYADH)

# Not real hashes: storage keeps whatever passwords.py gives it
SARA_HASH = "$argon2id$sara"
OMAR_HASH = "$argon2id$omar"


class Clock:
    """A clock the test moves by hand."""

    def __init__(self, moment):
        self.moment = moment

    def __call__(self):
        return self.moment


@pytest.fixture
def clock():
    return Clock(START)


@pytest.fixture
def storage(tmp_path, clock):
    storage = AccountStorage(tmp_path / "accounts" / "accounts.db", now=clock)
    storage.initialize()
    return storage


def add_sara(storage):
    return storage.create_account(
        "Sara Alqahtani", "sara.q@moh.gov.sa", SARA_HASH, ROLE_ENGINEER,
    )


# ============================================================
# DATABASE
# ============================================================

def test_the_database_lives_in_data_accounts():
    assert DEFAULT_DATABASE == REPO_ROOT / "data" / "accounts" / "accounts.db"
    assert (REPO_ROOT / "backend" / "accounts" / "storage.py").exists()


def test_initialize_creates_the_folder_and_can_run_twice(tmp_path, clock):
    storage = AccountStorage(tmp_path / "new" / "accounts.db", now=clock)

    storage.initialize()
    storage.initialize()

    assert (tmp_path / "new" / "accounts.db").exists()


# ============================================================
# ACCOUNTS
# ============================================================

def test_a_new_account_is_active_and_can_be_read_back(storage):
    sara = add_sara(storage)

    assert sara.name == "Sara Alqahtani"
    assert sara.email == "sara.q@moh.gov.sa"
    assert sara.role == ROLE_ENGINEER
    assert sara.status == STATUS_ACTIVE
    # 09:00 Riyadh is 06:00 UTC
    assert sara.created_at == datetime(2026, 11, 18, 6, 0, tzinfo=timezone.utc)
    assert storage.get_account(sara.id) == sara


def test_ids_are_random_and_unique(storage):
    sara = add_sara(storage)
    omar = storage.create_account("Omar", "omar@ksu.edu.sa", OMAR_HASH, ROLE_ENGINEER)

    assert sara.id != omar.id
    assert len(sara.id) == 32


def test_name_spaces_are_trimmed_and_email_is_lowercased(storage):
    sara = storage.create_account(
        "  Sara Alqahtani ", " Sara.Q@MOH.gov.sa ", SARA_HASH, ROLE_ENGINEER,
    )

    assert sara.name == "Sara Alqahtani"
    assert sara.email == "sara.q@moh.gov.sa"


def test_the_same_email_in_another_case_is_a_duplicate(storage):
    add_sara(storage)

    with pytest.raises(DuplicateEmailError):
        storage.create_account("Sara", "SARA.Q@moh.gov.sa", OMAR_HASH, ROLE_ENGINEER)


def test_an_unknown_role_is_refused(storage):
    with pytest.raises(sqlite3.IntegrityError):
        storage.create_account("X", "x@ksu.edu.sa", OMAR_HASH, "superuser")


def test_find_login_returns_the_account_and_its_hash(storage):
    sara = add_sara(storage)

    record = storage.find_login("Sara.Q@moh.gov.sa")

    assert (record.account, record.password_hash) == (sara, SARA_HASH)
    assert record.paused_until is None
    assert storage.find_login("nobody@moh.gov.sa") is None


def test_the_account_itself_never_carries_the_hash(storage):
    sara = add_sara(storage)

    assert SARA_HASH not in repr(sara)


def test_an_unknown_id_gives_none(storage):
    assert storage.get_account("0" * 32) is None


# ============================================================
# FAILED LOGINS
# ============================================================

def test_the_limit_is_5_wrong_passwords_then_30_minutes():
    assert (MAX_FAILED_LOGINS, LOGIN_PAUSE) == (5, timedelta(minutes=30))


def test_the_5th_wrong_password_in_a_row_starts_the_pause(storage):
    sara = add_sara(storage)

    for _ in range(4):
        assert storage.record_failed_login(sara.id) is None
    assert storage.find_login(sara.email).paused_until is None

    # 5th at 09:00 Riyadh (06:00 UTC): paused until 09:30 (06:30 UTC)
    until = storage.record_failed_login(sara.id)
    assert until == START + timedelta(minutes=30)
    assert storage.find_login(sara.email).paused_until == until


def test_after_a_pause_the_count_starts_again(storage, clock):
    sara = add_sara(storage)
    for _ in range(5):
        storage.record_failed_login(sara.id)

    clock.moment = START + timedelta(minutes=31)
    for _ in range(4):
        assert storage.record_failed_login(sara.id) is None
    assert storage.record_failed_login(sara.id) == clock.moment + LOGIN_PAUSE


def test_a_correct_password_resets_the_count(storage):
    sara = add_sara(storage)
    for _ in range(4):
        storage.record_failed_login(sara.id)

    storage.record_successful_login(sara.id)

    # 4 more wrong ones are not enough for a pause
    for _ in range(4):
        assert storage.record_failed_login(sara.id) is None


def test_failed_logins_of_one_account_do_not_touch_another(storage):
    sara = add_sara(storage)
    omar = storage.create_account("Omar", "omar@ksu.edu.sa", OMAR_HASH, ROLE_ENGINEER)

    for _ in range(5):
        storage.record_failed_login(sara.id)

    assert storage.find_login(omar.email).paused_until is None


# ============================================================
# SESSIONS
# ============================================================

def test_a_session_token_gives_back_its_account(storage):
    sara = add_sara(storage)
    token = storage.create_session(sara.id)

    assert storage.get_session_account(token) == sara


def test_tokens_are_long_and_different_each_time(storage):
    sara = add_sara(storage)
    first = storage.create_session(sara.id)
    second = storage.create_session(sara.id)

    # 32 random bytes are 43 URL-safe characters
    assert len(first) == len(second) == 43
    assert first != second


def test_only_the_sha256_of_a_token_is_stored(storage):
    sara = add_sara(storage)
    token = storage.create_session(sara.id)

    with sqlite3.connect(storage.database_path) as connection:
        stored = connection.execute("SELECT token_digest FROM sessions").fetchall()

    assert stored == [(token_digest(token),)]
    assert token not in stored[0][0]
    # SHA-256 written in hexadecimal: 64 characters
    assert len(stored[0][0]) == 64


def test_an_unknown_token_gives_none(storage):
    assert storage.get_session_account("not-a-token") is None


def test_a_busy_session_lasts_8_hours(storage, clock):
    sara = add_sara(storage)
    token = storage.create_session(sara.id)               # 09:00

    assert SESSION_LIFETIME == timedelta(hours=8)

    # A request every 20 minutes keeps it from going idle
    for minutes in range(20, 8 * 60, 20):
        clock.moment = START + timedelta(minutes=minutes)
        assert storage.get_session_account(token) == sara, minutes

    clock.moment = START + timedelta(hours=8)              # 17:00
    assert storage.get_session_account(token) is None


def test_30_minutes_without_a_request_end_a_session(storage, clock):
    sara = add_sara(storage)
    token = storage.create_session(sara.id)               # 09:00

    assert SESSION_IDLE_LIMIT == timedelta(minutes=30)

    # 09:29:59: 29:59 idle, still on; this request resets the idle time
    clock.moment = START + timedelta(minutes=29, seconds=59)
    assert storage.get_session_account(token) == sara

    # 09:59:58: 29:59 after the last request, still on
    clock.moment = START + timedelta(minutes=59, seconds=58)
    assert storage.get_session_account(token) == sara

    # 10:29:58: exactly 30:00 after the last request, ended
    clock.moment = START + timedelta(minutes=89, seconds=58)
    assert storage.get_session_account(token) is None


def test_an_expired_session_is_deleted_when_used(storage, clock):
    sara = add_sara(storage)
    token = storage.create_session(sara.id)

    clock.moment = START + timedelta(hours=9)
    storage.get_session_account(token)

    with sqlite3.connect(storage.database_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM sessions").fetchone() == (0,)


def test_logout_ends_only_that_session(storage):
    sara = add_sara(storage)
    laptop = storage.create_session(sara.id)
    office = storage.create_session(sara.id)

    storage.delete_session(laptop)
    storage.delete_session(laptop)          # a second logout does nothing

    assert storage.get_session_account(laptop) is None
    assert storage.get_session_account(office) == sara


def test_delete_expired_sessions_keeps_the_valid_ones(storage, clock):
    sara = add_sara(storage)
    storage.create_session(sara.id)                       # last request 09:00

    clock.moment = START + timedelta(minutes=20)
    recent = storage.create_session(sara.id)              # last request 09:20

    clock.moment = START + timedelta(minutes=30)          # 09:30
    assert storage.delete_expired_sessions() == 1
    assert storage.get_session_account(recent) == sara


def test_an_inactive_account_has_no_valid_session(storage):
    sara = add_sara(storage)
    token = storage.create_session(sara.id)

    # Deactivation itself comes with ADM-03; set the status directly here
    with sqlite3.connect(storage.database_path) as connection:
        connection.execute("UPDATE accounts SET status = 'inactive'")

    assert storage.get_session_account(token) is None


def test_deleting_an_account_deletes_its_sessions(storage):
    sara = add_sara(storage)
    storage.create_session(sara.id)

    # Deletion itself comes with ADM-04; delete the row directly here
    with sqlite3.connect(storage.database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("DELETE FROM accounts")
        count = connection.execute("SELECT COUNT(*) FROM sessions").fetchone()

    assert count == (0,)


def test_admin_and_engineer_sessions_both_work(storage):
    admin = storage.create_account("Aliyah", "aliyah@ksu.edu.sa", OMAR_HASH, ROLE_ADMIN)
    token = storage.create_session(admin.id)

    assert storage.get_session_account(token).role == ROLE_ADMIN


def test_times_without_a_timezone_are_refused(tmp_path):
    storage = AccountStorage(
        tmp_path / "accounts.db", now=lambda: datetime(2026, 11, 18, 9, 0),
    )
    storage.initialize()

    with pytest.raises(ValueError, match="timezone"):
        storage.create_account("Sara", "sara@moh.gov.sa", SARA_HASH, ROLE_ENGINEER)
