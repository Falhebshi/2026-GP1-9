"""
The accounts server: login, logout and "who is logged in".

Built like the network map server (jaadah/network_congestion/
server.py): a small FastAPI app made by create_app(), with a local
SQLite database (storage.py). The website reaches it through the Vite
proxy: /api/auth/login goes to /auth/login (frontend/vite.config.js).

Run it next to the website:

    uvicorn backend.accounts.server:app --port 8003

Endpoints:

    GET  /health        status
    POST /auth/login    check email and password; start a session and
                        set its cookie
    POST /auth/logout   end the session and remove its cookie
    GET  /auth/me       the logged-in account, or 401

Administrators only (401 without a session, 403 for engineers):

    GET  /admin/engineers    every engineer account (ADM-02)
    POST /admin/engineers    create an engineer account (ADM-01)
    GET  /admin/passphrase   a random passphrase for the Generate button
    POST /admin/engineers/{id}/status
                             activate or deactivate an engineer (ADM-03)

The rules (messages, the pause after wrong passwords, the session
cookie) are explained in docs/accounts.md.

Setting: JAADAH_SECURE_COOKIE=true marks the session cookie Secure (sent
over HTTPS only). Set it whenever Jaadah is reached over HTTPS; leave it
unset for the local http://localhost website.
"""

import os
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from pydantic import BaseModel

from backend.accounts.passphrase import generate_passphrase
from backend.accounts.passwords import (
    hash_password,
    password_problem,
    verify_password,
)
from backend.accounts.storage import (
    LOGIN_PAUSE,
    MAX_NAME_LENGTH,
    ROLE_ADMIN,
    ROLE_ENGINEER,
    SESSION_LIFETIME,
    STATUS_ACTIVE,
    Account,
    AccountStorage,
    DuplicateEmailError,
    normalise_email,
    valid_email,
)

# The website and the accounts server run on the same address, so the
# cookie only needs Secure when that address is HTTPS
SECURE_COOKIE_SETTING = "JAADAH_SECURE_COOKIE"

# Login input longer than this is refused without being hashed. Passwords
# are at most 64 characters (passwords.py) and an email at most 254
# (RFC 5321), so no real login is affected.
MAX_LOGIN_EMAIL = 254
MAX_LOGIN_PASSWORD = 256

# The browser keeps the session token in this cookie
SESSION_COOKIE = "jaadah_session"

# Messages the login page shows as they are
INCORRECT = "Email or password is incorrect."
DEACTIVATED = "Your account is deactivated. Contact the administrator."
PAUSED = (
    "Too many attempts. Try again in "
    f"{int(LOGIN_PAUSE.total_seconds() // 60)} minutes."
)
NOT_LOGGED_IN = "Log in to continue."
ADMINS_ONLY = "Only administrators can do this."

# Messages for the Create account form, each for one field
NAME_MISSING = "Enter the engineer's name."
NAME_TOO_LONG = f"Use at most {MAX_NAME_LENGTH} characters."
EMAIL_INVALID = "Enter an email address like name@organization.gov.sa."
EMAIL_TAKEN = "An account with this email already exists."

# For an action on an account another tab deleted (or an administrator's id)
ACCOUNT_GONE = "This account no longer exists."

# Checked when the email has no account, and while login is paused, so
# every answer takes about one password check and the time does not
# reveal which emails have accounts
UNKNOWN_EMAIL_HASH = hash_password("no account has this password at all")


class LoginRequest(BaseModel):
    email: str
    password: str


class User(BaseModel):
    """An account as the website sees it."""

    id: str
    name: str
    email: str
    role: str


class LoginResponse(BaseModel):
    user: User


class Engineer(BaseModel):
    """An engineer account as the Admin Dashboard sees it."""

    id: str
    name: str
    email: str
    status: str
    created_at: str          # ISO 8601, UTC


class EngineerList(BaseModel):
    engineers: list[Engineer]


class NewEngineer(BaseModel):
    name: str
    email: str
    password: str


class Passphrase(BaseModel):
    passphrase: str


class NewStatus(BaseModel):
    status: Literal["active", "inactive"]


def engineer_of(account: Account) -> Engineer:
    return Engineer(
        id=account.id,
        name=account.name,
        email=account.email,
        status=account.status,
        created_at=account.created_at.isoformat(),
    )


def field_error(code: int, field: str, message: str) -> HTTPException:
    """An error the form shows under one field: {"detail": {"field", "message"}}."""

    return HTTPException(code, {"field": field, "message": message})


def user_of(account: Account) -> User:
    return User(
        id=account.id,
        name=account.name,
        email=account.email,
        role=account.role,
    )


def secure_cookie_from_environment() -> bool:
    """True when JAADAH_SECURE_COOKIE is set to true, 1 or yes."""

    return os.environ.get(SECURE_COOKIE_SETTING, "").strip().lower() in {"true", "1", "yes"}


def create_app(
    storage: AccountStorage | None = None,
    secure_cookie: bool | None = None,
) -> FastAPI:
    """Create the accounts server.

    secure_cookie: mark the session cookie Secure; by default read from
    JAADAH_SECURE_COOKIE.
    """

    accounts = storage if storage is not None else AccountStorage()
    cookie_secure = (
        secure_cookie_from_environment() if secure_cookie is None else secure_cookie
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        accounts.initialize()
        accounts.delete_expired_sessions()
        accounts.forget_old_attempts()
        yield

    app = FastAPI(title="Jaadah accounts", lifespan=lifespan)

    def current_account(request: Request) -> Account:
        """The account of this request's session; 401 without a valid one."""

        token = request.cookies.get(SESSION_COOKIE)
        account = accounts.get_session_account(token) if token else None

        if account is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, NOT_LOGGED_IN)

        return account

    def current_admin(account: Account = Depends(current_account)) -> Account:
        """The logged-in administrator; 403 for an engineer."""

        if account.role != ROLE_ADMIN:
            raise HTTPException(status.HTTP_403_FORBIDDEN, ADMINS_ONLY)

        return account

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/auth/login")
    def login(details: LoginRequest, request: Request, response: Response) -> LoginResponse:
        email, password = details.email, details.password

        # Far too long to be a real login: refused without hashing it
        if len(email) > MAX_LOGIN_EMAIL or len(password) > MAX_LOGIN_PASSWORD:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, INCORRECT)

        # The pause is kept per email typed, so an email without an
        # account pauses exactly like one with an account. While paused,
        # one password check still runs so the answer takes as long as usual.
        if accounts.login_paused_until(email) is not None:
            verify_password(UNKNOWN_EMAIL_HASH, password)
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, PAUSED)

        record = accounts.find_login(email)

        # Exactly one password check, with or without an account
        stored = record.password_hash if record is not None else UNKNOWN_EMAIL_HASH
        correct = verify_password(stored, password) and record is not None

        if not correct:
            if accounts.record_failed_login(email) is not None:
                raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, PAUSED)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, INCORRECT)

        accounts.record_successful_login(email)
        account = record.account

        # Only someone with the right password learns that the account
        # is deactivated
        if account.status != STATUS_ACTIVE:
            raise HTTPException(status.HTTP_403_FORBIDDEN, DEACTIVATED)

        # Logging in again in the same browser ends its previous session
        old_token = request.cookies.get(SESSION_COOKIE)
        if old_token:
            accounts.delete_session(old_token)

        token = accounts.create_session(account.id)
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=int(SESSION_LIFETIME.total_seconds()),
            httponly=True,          # page scripts cannot read it
            samesite="strict",      # not sent when another site links here
            path="/",
            secure=cookie_secure,   # HTTPS only, when JAADAH_SECURE_COOKIE is set
        )

        return LoginResponse(user=user_of(account))

    @app.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
    def logout(request: Request, response: Response) -> None:
        token = request.cookies.get(SESSION_COOKIE)
        if token:
            accounts.delete_session(token)

        response.delete_cookie(SESSION_COOKIE, path="/", secure=cookie_secure, httponly=True, samesite="strict")

    @app.get("/auth/me")
    def me(account: Account = Depends(current_account)) -> LoginResponse:
        return LoginResponse(user=user_of(account))

    # ============================================================
    # ADMINISTRATORS (ADM-01, ADM-02)
    # ============================================================

    @app.get("/admin/engineers")
    def list_engineers(admin: Account = Depends(current_admin)) -> EngineerList:
        return EngineerList(engineers=[engineer_of(a) for a in accounts.list_engineers()])

    @app.post("/admin/engineers", status_code=status.HTTP_201_CREATED)
    def create_engineer(
        details: NewEngineer,
        admin: Account = Depends(current_admin),
    ) -> Engineer:
        name = details.name.strip()
        email = normalise_email(details.email)

        if not name:
            raise field_error(400, "name", NAME_MISSING)
        if len(name) > MAX_NAME_LENGTH:
            raise field_error(400, "name", NAME_TOO_LONG)
        if not valid_email(email):
            raise field_error(400, "email", EMAIL_INVALID)

        # A refused password is never hashed
        problem = password_problem(details.password, name, email)
        if problem:
            raise field_error(400, "password", problem)

        try:
            account = accounts.create_account(
                name, email, hash_password(details.password), ROLE_ENGINEER,
            )
        except DuplicateEmailError:
            raise field_error(409, "email", EMAIL_TAKEN) from None

        return engineer_of(account)

    @app.post("/admin/engineers/{account_id}/status")
    def set_status(
        account_id: str,
        change: NewStatus,
        admin: Account = Depends(current_admin),
    ) -> Engineer:
        # Deactivating also ends the engineer's sessions (storage.set_status)
        account = accounts.set_status(account_id, change.status)
        if account is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, ACCOUNT_GONE)

        return engineer_of(account)

    @app.get("/admin/passphrase")
    def passphrase(admin: Account = Depends(current_admin)) -> Passphrase:
        return Passphrase(passphrase=generate_passphrase())

    return app


app = create_app()
