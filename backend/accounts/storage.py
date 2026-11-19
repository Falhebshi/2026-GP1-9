"""
Store Jaadah accounts and their login sessions in a local SQLite database.

Built like the network map's storage (jaadah/network_congestion/
storage.py): one database file, opened for each operation and closed
afterwards. Two tables:

    accounts  one row per administrator or traffic engineer, with the
              Argon2id string of the password (passwords.py), never
              the password itself
    sessions  one row per logged-in browser: the SHA-256 of its token,
              the account, when it expires, and its last request
    login_attempts
              wrong passwords per email typed at login, whether or not an
              account has that email, and the end of a login pause

The database is not committed (see .gitignore): it holds password
hashes. Why each choice was made is explained in docs/accounts.md.
"""

import hashlib
import re
import secrets
import sqlite3
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE = REPO_ROOT / "data/accounts/accounts.db"

ROLE_ADMIN = "admin"
ROLE_ENGINEER = "engineer"
STATUS_ACTIVE = "active"
STATUS_INACTIVE = "inactive"

# A session ends at whichever comes first: one working day after login,
# or 30 minutes without any request (NFR-03)
SESSION_LIFETIME = timedelta(hours=8)
SESSION_IDLE_LIMIT = timedelta(minutes=30)

# 32 random bytes: 256 bits, written as 43 URL-safe characters
TOKEN_BYTES = 32

# After this many wrong passwords in a row for one email, login with that
# email pauses (NIST asks for a limit of at most 100; these values are
# Jaadah's). The count is kept per email typed, not per account, so an
# email without an account pauses exactly like one with an account. It is
# forgotten after this same time without a wrong password.
MAX_FAILED_LOGINS = 5
LOGIN_PAUSE = timedelta(minutes=30)


# A name or email longer than this is refused. An email address is at most
# 254 characters (RFC 5321); a name of 100 characters is far longer than
# any real one.
MAX_NAME_LENGTH = 100
MAX_EMAIL_LENGTH = 254

# The same simple check as the login page (frontend/src/pages/Login.jsx):
# something, an @, something, a dot, something; no spaces
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def valid_email(email: str) -> bool:
    """True if the email (trimmed) looks like name@organization.gov.sa."""

    email = email.strip()
    return len(email) <= MAX_EMAIL_LENGTH and EMAIL_PATTERN.match(email) is not None


class DuplicateEmailError(ValueError):
    """An account with this email already exists."""


@dataclass(frozen=True)
class LoginRecord:
    """What login needs to know about an account; only for checking a password."""

    account: "Account"
    password_hash: str


@dataclass(frozen=True)
class Account:
    """An account as the rest of the code sees it: no password hash."""

    id: str
    name: str
    email: str
    role: str
    status: str
    created_at: datetime


def normalise_email(email: str) -> str:
    """Emails are compared without spaces or letter case.

    " Sara.Q@MOH.gov.sa " and "sara.q@moh.gov.sa" are the same account.
    """

    return email.strip().casefold()


def token_digest(token: str) -> str:
    """The SHA-256 of a session token, the only form that is stored."""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_text(moment: datetime) -> str:
    """Return a time as UTC text; it must include a timezone.

    Stored in UTC (not Riyadh time) because these times are only
    compared, never shown, and UTC text sorts in time order.
    """

    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError("stored times must include a timezone")

    # Always with microseconds, so every stored time has the same shape
    return moment.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _account(row: tuple) -> Account:
    account_id, name, email, role, status, created_at = row

    return Account(
        id=account_id,
        name=name,
        email=email,
        role=role,
        status=status,
        created_at=datetime.fromisoformat(created_at),
    )


ACCOUNT_COLUMNS = "id, name, email, role, status, created_at"
# The same columns, named through the accounts table (for joins)
ACCOUNT_COLUMNS_JOINED = ", ".join(
    f"accounts.{column}" for column in ACCOUNT_COLUMNS.split(", ")
)


class AccountStorage:
    """Store and read accounts and sessions."""

    def __init__(
        self,
        database_path: Path = DEFAULT_DATABASE,
        now: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.database_path = database_path
        # The clock, replaceable in tests
        self.now = now

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Open and safely close a database connection."""

        connection = sqlite3.connect(self.database_path)
        # SQLite only follows ON DELETE CASCADE when this is on
        connection.execute("PRAGMA foreign_keys = ON")

        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        """Create the database folder and tables if needed."""

        self.database_path.parent.mkdir(parents=True, exist_ok=True)

        with self._connect() as connection:
            connection.execute(
                f"""
                CREATE TABLE IF NOT EXISTS accounts (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    role TEXT NOT NULL
                        CHECK (role IN ('{ROLE_ADMIN}', '{ROLE_ENGINEER}')),
                    status TEXT NOT NULL
                        CHECK (status IN ('{STATUS_ACTIVE}', '{STATUS_INACTIVE}')),
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    token_digest TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL
                        REFERENCES accounts (id) ON DELETE CASCADE,
                    expires_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS login_attempts (
                    email TEXT PRIMARY KEY,
                    failed_logins INTEGER NOT NULL,
                    last_failed_at TEXT NOT NULL,
                    paused_until TEXT
                )
                """
            )

    # ============================================================
    # ACCOUNTS
    # ============================================================

    def create_account(
        self,
        name: str,
        email: str,
        password_hash: str,
        role: str,
    ) -> Account:
        """Store a new active account and return it.

        The id is random, so an id is never given to a second account
        after the first is deleted.
        """

        created_at = _utc_text(self.now())
        account = Account(
            id=uuid.uuid4().hex,
            name=name.strip(),
            email=normalise_email(email),
            role=role,
            status=STATUS_ACTIVE,
            created_at=datetime.fromisoformat(created_at),
        )

        try:
            with self._connect() as connection:
                connection.execute(
                    f"""
                    INSERT INTO accounts ({ACCOUNT_COLUMNS}, password_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        account.id,
                        account.name,
                        account.email,
                        account.role,
                        account.status,
                        created_at,
                        password_hash,
                    ),
                )
        except sqlite3.IntegrityError as error:
            if "accounts.email" in str(error):
                raise DuplicateEmailError(account.email) from error
            raise

        return account

    def get_account(self, account_id: str) -> Account | None:
        """Return the account with this id, or None."""

        with self._connect() as connection:
            row = connection.execute(
                f"SELECT {ACCOUNT_COLUMNS} FROM accounts WHERE id = ?",
                (account_id,),
            ).fetchone()

        return None if row is None else _account(row)

    def list_engineers(self) -> list[Account]:
        """Every engineer account, ordered by name (A to Z, ignoring case), then email."""

        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT {ACCOUNT_COLUMNS}
                FROM accounts
                WHERE role = ?
                ORDER BY name COLLATE NOCASE, email
                """,
                (ROLE_ENGINEER,),
            ).fetchall()

        return [_account(row) for row in rows]

    def get_engineer(self, account_id: str) -> Account | None:
        """The engineer account with this id, or None (also for an administrator's id)."""

        account = self.get_account(account_id)

        return account if account is not None and account.role == ROLE_ENGINEER else None

    def set_status(self, account_id: str, status: str) -> Account | None:
        """Set an engineer's status; return the account, or None if no such engineer.

        Making an account inactive also ends all its sessions at once, so
        the engineer loses access immediately (ADM-03).
        """

        if status not in (STATUS_ACTIVE, STATUS_INACTIVE):
            raise ValueError(f"unknown status: {status}")

        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE accounts SET status = ? WHERE id = ? AND role = ?",
                (status, account_id, ROLE_ENGINEER),
            )
            if cursor.rowcount == 0:
                return None

            if status == STATUS_INACTIVE:
                connection.execute(
                    "DELETE FROM sessions WHERE account_id = ?", (account_id,),
                )

        return self.get_account(account_id)

    def find_login(self, email: str) -> LoginRecord | None:
        """Return what login needs for the account with this email, or None."""

        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT {ACCOUNT_COLUMNS}, password_hash
                FROM accounts
                WHERE email = ?
                """,
                (normalise_email(email),),
            ).fetchone()

        if row is None:
            return None

        return LoginRecord(account=_account(row[:-1]), password_hash=row[-1])

    # ============================================================
    # WRONG PASSWORDS (per email typed)
    # ============================================================

    def login_paused_until(self, email: str) -> datetime | None:
        """When the login pause for this email ends, or None if it is not paused."""

        with self._connect() as connection:
            row = connection.execute(
                "SELECT paused_until FROM login_attempts WHERE email = ?",
                (normalise_email(email),),
            ).fetchone()

        if row is None or row[0] is None:
            return None

        paused_until = datetime.fromisoformat(row[0])

        return paused_until if self.now() < paused_until else None

    def record_failed_login(self, email: str) -> datetime | None:
        """Count one wrong password for an email; return when the pause ends if this one starts it.

        The 5th wrong password in a row pauses login with that email for
        30 minutes and starts the count again from 0. Works the same for
        an email that has no account.
        """

        key = normalise_email(email)
        now = self.now()

        with self._connect() as connection:
            self._forget_old_attempts(connection, now)

            connection.execute(
                """
                INSERT INTO login_attempts (email, failed_logins, last_failed_at)
                VALUES (?, 1, ?)
                ON CONFLICT (email) DO UPDATE SET
                    failed_logins = failed_logins + 1,
                    last_failed_at = excluded.last_failed_at
                """,
                (key, _utc_text(now)),
            )
            count = connection.execute(
                "SELECT failed_logins FROM login_attempts WHERE email = ?",
                (key,),
            ).fetchone()[0]

            if count < MAX_FAILED_LOGINS:
                return None

            paused_until = now + LOGIN_PAUSE
            connection.execute(
                """
                UPDATE login_attempts
                SET failed_logins = 0, paused_until = ?
                WHERE email = ?
                """,
                (_utc_text(paused_until), key),
            )

        return paused_until

    def record_successful_login(self, email: str) -> None:
        """A correct password: the count of wrong ones for this email starts again."""

        with self._connect() as connection:
            connection.execute(
                "DELETE FROM login_attempts WHERE email = ?",
                (normalise_email(email),),
            )

    def forget_old_attempts(self) -> int:
        """Delete the counts that no longer matter; return how many."""

        with self._connect() as connection:
            return self._forget_old_attempts(connection, self.now())

    @staticmethod
    def _forget_old_attempts(connection: sqlite3.Connection, now: datetime) -> int:
        """A count is forgotten once its pause is over and 30 minutes passed
        without a wrong password, so typing many made-up emails cannot fill
        the table.
        """

        cursor = connection.execute(
            """
            DELETE FROM login_attempts
            WHERE (paused_until IS NULL OR paused_until <= ?)
              AND last_failed_at <= ?
            """,
            (_utc_text(now), _utc_text(now - LOGIN_PAUSE)),
        )

        return cursor.rowcount

    # ============================================================
    # SESSIONS
    # ============================================================

    def create_session(self, account_id: str) -> str:
        """Start a session for an account and return its token.

        The token goes to the browser; only its SHA-256 is stored, so
        a copy of the database cannot be used to log in.
        """

        token = secrets.token_urlsafe(TOKEN_BYTES)
        now = self.now()

        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sessions
                    (token_digest, account_id, expires_at, last_seen_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    token_digest(token),
                    account_id,
                    _utc_text(now + SESSION_LIFETIME),
                    _utc_text(now),
                ),
            )

        return token

    def get_session_account(self, token: str) -> Account | None:
        """Return the account of a valid session, or None.

        Valid means: the session exists, is less than 8 hours old, had a
        request in the last 30 minutes, and its account is active. A
        valid session counts this call as its latest request; an
        expired one is deleted.
        """

        digest = token_digest(token)
        now = self.now()

        with self._connect() as connection:
            row = connection.execute(
                f"""
                SELECT sessions.expires_at, sessions.last_seen_at,
                       {ACCOUNT_COLUMNS_JOINED}
                FROM sessions
                JOIN accounts ON accounts.id = sessions.account_id
                WHERE sessions.token_digest = ?
                """,
                (digest,),
            ).fetchone()

            if row is None:
                return None

            expires_at = datetime.fromisoformat(row[0])
            last_seen_at = datetime.fromisoformat(row[1])

            if now >= expires_at or now - last_seen_at >= SESSION_IDLE_LIMIT:
                connection.execute(
                    "DELETE FROM sessions WHERE token_digest = ?",
                    (digest,),
                )
                return None

            account = _account(row[2:])
            if account.status != STATUS_ACTIVE:
                return None

            connection.execute(
                "UPDATE sessions SET last_seen_at = ? WHERE token_digest = ?",
                (_utc_text(now), digest),
            )

        return account

    def delete_session(self, token: str) -> None:
        """End one session (logout). Nothing happens if it does not exist."""

        with self._connect() as connection:
            connection.execute(
                "DELETE FROM sessions WHERE token_digest = ?",
                (token_digest(token),),
            )

    def delete_expired_sessions(self) -> int:
        """Delete every expired or idle session; return how many."""

        now = self.now()

        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM sessions WHERE expires_at <= ? OR last_seen_at <= ?",
                (_utc_text(now), _utc_text(now - SESSION_IDLE_LIMIT)),
            )

        return cursor.rowcount
