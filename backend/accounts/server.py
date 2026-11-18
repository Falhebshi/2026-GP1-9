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

The rules (messages, the pause after wrong passwords, the session
cookie) are explained in docs/accounts.md.
"""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from pydantic import BaseModel

from backend.accounts.passwords import hash_password, verify_password
from backend.accounts.storage import (
    LOGIN_PAUSE,
    SESSION_LIFETIME,
    STATUS_ACTIVE,
    Account,
    AccountStorage,
)

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

# Checked when the email has no account, so an unknown email takes
# about as long as a wrong password and the time does not reveal
# which emails have accounts
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


def user_of(account: Account) -> User:
    return User(
        id=account.id,
        name=account.name,
        email=account.email,
        role=account.role,
    )


def create_app(storage: AccountStorage | None = None) -> FastAPI:
    """Create the accounts server."""

    accounts = storage if storage is not None else AccountStorage()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        accounts.initialize()
        accounts.delete_expired_sessions()
        yield

    app = FastAPI(title="Jaadah accounts", lifespan=lifespan)

    def current_account(request: Request) -> Account:
        """The account of this request's session; 401 without a valid one."""

        token = request.cookies.get(SESSION_COOKIE)
        account = accounts.get_session_account(token) if token else None

        if account is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, NOT_LOGGED_IN)

        return account

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/auth/login")
    def login(details: LoginRequest, response: Response) -> LoginResponse:
        record = accounts.find_login(details.email)

        if record is None:
            verify_password(UNKNOWN_EMAIL_HASH, details.password)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, INCORRECT)

        account = record.account

        # While paused, the password is not even checked
        if record.paused_until is not None and accounts.now() < record.paused_until:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, PAUSED)

        if not verify_password(record.password_hash, details.password):
            if accounts.record_failed_login(account.id) is not None:
                raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, PAUSED)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, INCORRECT)

        accounts.record_successful_login(account.id)

        # Only someone with the right password learns that the account
        # is deactivated
        if account.status != STATUS_ACTIVE:
            raise HTTPException(status.HTTP_403_FORBIDDEN, DEACTIVATED)

        token = accounts.create_session(account.id)
        response.set_cookie(
            SESSION_COOKIE,
            token,
            max_age=int(SESSION_LIFETIME.total_seconds()),
            httponly=True,          # page scripts cannot read it
            samesite="strict",      # not sent when another site links here
            path="/",
            # The local website runs on http://localhost, where a Secure
            # cookie is not needed; a deployment behind HTTPS sets True
            secure=False,
        )

        return LoginResponse(user=user_of(account))

    @app.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
    def logout(request: Request, response: Response) -> None:
        token = request.cookies.get(SESSION_COOKIE)
        if token:
            accounts.delete_session(token)

        response.delete_cookie(SESSION_COOKIE, path="/")

    @app.get("/auth/me")
    def me(account: Account = Depends(current_account)) -> LoginResponse:
        return LoginResponse(user=user_of(account))

    return app


app = create_app()
