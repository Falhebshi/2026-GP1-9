# Accounts and Login

## Overview

Jaadah has two kinds of account: **traffic engineers**, who use the traffic pages, and **administrators**, who manage engineer accounts. Every page except Login needs a logged-in account of the right role.

Accounts are handled by the **accounts server**, a small FastAPI service with its own SQLite database, built like the [network map server](../jaadah/network_congestion/server.py). It does not depend on any traffic data, so login works on a machine without the private RCRC files. The website reaches it through the Vite proxy at `/api/auth`.

The implementation is in:

```text
backend/
└── accounts/
    ├── passwords.py           password rules, hashing and checking
    ├── common_passwords.txt   common passwords that are refused
    ├── storage.py             SQLite storage: accounts and sessions
    ├── server.py              FastAPI service: login, logout, who is logged in
    ├── create_admin.py        command that creates an administrator
    └── accounts_tests/        tests

frontend/src/
├── services/authService.js    calls to the accounts server
├── components/RequireRole.jsx which pages each role can open
└── pages/AdminDashboard.jsx   the administrator's first page
```

This document covers the backlog items PBI 31 (log in), PBI 32 (log out) and the account parts of NFR-03 (security). The standards behind each rule are listed under [Sources](#sources).

---

## Running It

The accounts database starts empty and Jaadah has no default login, so create an administrator once:

```bash
python -m backend.accounts.create_admin --name "Aliyah Alharbi" --email aliyah@ksu.edu.sa
```

It asks for the password twice without showing it on screen, checks it with the [password rules](#password-rules), and stores only its hash. Run it again for each extra administrator.

Then start the accounts server next to the website:

```bash
uvicorn backend.accounts.server:app --port 8003
```

The database is created at `data/accounts/accounts.db`. It holds password hashes, so it is listed in `.gitignore` and never committed. Deleting it removes every account and session.

When Jaadah is reached over HTTPS, start the server with `JAADAH_SECURE_COOKIE=true` so the session cookie is only sent over HTTPS (see [Sessions](#sessions)). On the local `http://localhost` website leave it unset.

---

## Roles and Pages

| Role | First page after login | Can open |
|---|---|---|
| Traffic engineer | Network Traffic Overview (`/overview`) | the traffic pages |
| Administrator | Admin Dashboard (`/admin`) | the Admin Dashboard only |

`RequireRole` (in `App.jsx`) asks the accounts server who is logged in every time the page address changes:

| Who opens a page | Result |
|---|---|
| Nobody logged in | sent to Login |
| The page's own role | the page opens |
| The other role | sent to their own first page |

Each role sees only what its job needs: an administrator's password gives no access to the traffic analysis, and an engineer's gives no access to account management. Administrators are created only by `create_admin`; the Admin Dashboard manages engineer accounts, never administrators.

Someone already logged in who opens `/login` goes straight to their own first page.

The component gallery (`/preview`) is for development and needs no login.

These checks are in the website. The traffic servers (ports 8000 to 8002) do not check logins.

---

## Password Rules

`password_problem(password, name, email)` returns why a new password is refused, or `None`. The same rules apply to every account and to `create_admin`. They follow NIST SP 800-63B-4, which applies when a password is the only login factor, as in Jaadah.

The password is first normalised to Unicode NFC, so "é" typed as one character or as "e" plus an accent is the same password. Then, in order:

| Rule | Refused example | Message |
|---|---|---|
| 15 to 64 characters, each Unicode code point counted as one | `orbit maple ri` (14) | Use at least 15 characters. A short phrase works well. |
| The whole password, lowercased, is not a [common password](#common-passwords) | `1Q2W3E4R5T6Y7U8I9O0P` | This password is too common. Choose another one. |
| It is not made only of the person's own name, email or "jaadah" | `Sara.Alqahtani2026` | Do not build the password from the person's name, email or Jaadah. |

There are **no composition rules** (such as "must contain a number or a symbol"): NIST forbids them, because they reject strong long phrases and accept weak short ones. `sara likes long morning walks` is accepted; `P@ssw0rd!` is not (too short).

### Name, Email and "jaadah"

NIST allows refusing "context-specific words, such as the name of the service, the username, and derivatives thereof", and requires the **whole** password to be compared, not parts of it. Jaadah applies this as follows:

1. The **context words** are the parts of the person's name, the parts of the email before the @, and `jaadah`.
2. The password is lowercased and its digits, spaces and symbols are removed.
3. It is refused if what is left splits completely into context words.

For Sara Alqahtani, `sara.q@moh.gov.sa`, the context words are `sara`, `alqahtani`, `q` and `jaadah`:

| Password | Letters left | Splits into context words? | Result |
|---|---|---|---|
| `Sara.Alqahtani2026` | `saraalqahtani` | sara + alqahtani | refused |
| `jaadah-sara-2026!` | `jaadahsara` | jaadah + sara | refused |
| `sara likes long morning walks` | `saralikeslongmorningwalks` | no | accepted |
| `orbit maple quiet river jaadah` | `orbitmaplequietriverjaadah` | no | accepted |
| `2026-2026-2026-20` | (none) | no | accepted by this rule |

### Common Passwords

`common_passwords.txt` holds the entries of 15 to 64 characters from the UK National Cyber Security Centre's list of the 100,000 most used passwords, built with Troy Hunt's Have I Been Pwned (2019), lowercased and without duplicates: **329 entries**. With the 15-character minimum, every one of the 100,000 is refused: 99,509 by length and the rest by the list. NIST notes that very large lists add little.

The copy comes from SecLists (`Passwords/Common-Credentials/100k-most-used-passwords-NCSC.txt`, https://github.com/danielmiessler/SecLists), MIT License, Copyright (c) 2018 Daniel Miessler. The file's header repeats this.

---

## Password Storage

Passwords are never stored. `hash_password()` stores an **Argon2id** hash made by the `argon2-cffi` package with the OWASP minimum settings:

| Setting | Value |
|---|---|
| Memory | 19 MiB (`memory_cost=19456` KiB) |
| Iterations | 2 (`time_cost`) |
| Parallelism | 1 |

The package adds a random 16-byte salt to every hash and stores the algorithm, settings, salt and hash in one string:

```text
$argon2id$v=19$m=19456,t=2,p=1$<salt>$<hash>
```

The same password hashed twice gives two different strings, so a copy of the database does not show who shares a password. `verify_password(stored, password)` returns `True` or `False`, including for a damaged stored string.

---

## Login

`POST /auth/login` checks, in this order, and stops at the first failure:

| Step | Check | If it fails |
|---|---|---|
| 1 | The email is at most 254 characters and the password at most 256 | 401 Email or password is incorrect. (not hashed) |
| 2 | Login with this email is not [paused](#too-many-wrong-passwords) | 429 Too many attempts. Try again in 30 minutes. |
| 3 | The email has an account and the password is right | 401 Email or password is incorrect. (the 5th wrong one in a row: 429) |
| 4 | The account is active | 403 Your account is deactivated. Contact the administrator. |
| 5 | | a session starts and the response is `{"user": {"id", "name", "email", "role"}}` |

Emails are compared trimmed and lowercased. Step 1 stops a multi-megabyte "password" from being hashed; no real login is affected, because passwords are at most 64 characters and an email address at most 254 (RFC 5321).

**Nothing in the answers reveals which emails have accounts.** A wrong password and an unknown email get the same message; every answer after step 1 runs exactly one password check (against a stored dummy hash when the email has no account, and while paused), so it takes about as long; and the pause works per email typed, the same with or without an account.

A deactivated account is told so **only after the correct password**. The real engineer learns why login fails; someone guessing learns nothing:

| Who tries Sara's deactivated account | Message |
|---|---|
| Sara, correct password | Your account is deactivated. Contact the administrator. |
| Anyone, wrong password | Email or password is incorrect. |

### Too Many Wrong Passwords

NIST requires limiting failed attempts, to no more than 100 in a row. In Jaadah, **5 wrong passwords in a row for one email pause login with that email for 30 minutes**. During the pause even the correct password is refused; a correct password afterwards sets the count back to 0. The values are Jaadah's choice within the NIST limit.

The count is kept **per email typed**, not per account, so an email without an account behaves exactly like one with an account. Otherwise "Too many attempts" would appear only for real accounts and tell anyone which emails are Jaadah users:

| Attempt | `sara.q@moh.gov.sa` (has an account) | `nobody@moh.gov.sa` (no account) |
|---|---|---|
| 1 to 4, wrong password | 401 Email or password is incorrect. | 401 Email or password is incorrect. |
| 5, wrong password | 429 Too many attempts… | 429 Too many attempts… |
| 6, any password, within 30 minutes | 429 Too many attempts… | 429 Too many attempts… |

For Sara's account:

| Time | Attempt | Result |
|---|---|---|
| 09:00 | wrong password, four times | 401 each time |
| 09:00 | 5th wrong password | 429, paused until 09:30 |
| 09:29:59 | correct password | 429 |
| 09:30 | correct password | logged in, count back to 0 |

A count is **forgotten after 30 minutes without a wrong password** (once any pause is over). This applies to every email alike, and stops someone from filling the database by typing many made-up emails: the old rows are deleted before each new wrong password is counted, and when the server starts.

This allows at most 240 guesses a day on one email. A stranger who knows an email can delay that engineer by 30 minutes, but cannot lock them out until an administrator acts.

---

## Sessions

After login the server creates a **session**: a random 256-bit token sent to the browser in the `jaadah_session` cookie.

| Cookie setting | Effect |
|---|---|
| `HttpOnly` | page scripts cannot read it |
| `SameSite=Strict` | not sent when another site links to Jaadah |
| `Path=/` | sent with every request to the website |
| `Max-Age=28800` | the browser forgets it after 8 hours |
| `Secure` (when `JAADAH_SECURE_COOKIE=true`) | sent over HTTPS only |

The server stores only the token's SHA-256, so a copy of the database cannot be used to log in. The website keeps nothing about the session itself; it asks the server.

A session ends at **whichever comes first**:

| Limit | Value | Reason |
|---|---|---|
| Overall | 8 hours after login | one working day |
| Inactivity | 30 minutes without a request | NFR-03: "If a user is inactive for 30 minutes, then the session is terminated" |

Every request with the cookie checks that the session exists, has not ended and belongs to an active account, and counts as activity. Requests come from:

- **every page change**: `RequireRole` asks `GET /auth/me`;
- **interaction on a page**: while the user clicks, types, scrolls or touches the page, `RequireRole` sends a "still here" `GET /auth/me`, **at most once every 5 minutes**.

So an engineer working on one page, such as the simulation, stays logged in, while a tab left untouched ends **30 to 35 minutes** after the last interaction (a "still here" can be up to 5 minutes old). Watching a page without any click, key or scroll counts as inactive. When a session has ended, the next page change or interaction goes to Login.

| Time | Sara | Requests |
|---|---|---|
| 09:00 | opens Current Traffic | 1 |
| 09:00 to 09:40 | plays the simulation, moves the slider | about one every 5 minutes |
| 09:40 | leaves the tab open | none |
| about 10:10 | | the server ends the session |
| 13:00 | clicks anything | sent to Login |

The 30 minutes is the top of OWASP's 15 to 30 minute range for low-risk applications, and stricter than NIST asks for a password-only login (an inactivity timeout is optional; the overall limit at most 30 days).

Logging in again in the same browser ends that browser's previous session, so its old token stops working at once.

**Logout** (`POST /auth/logout`) deletes the session on the server and removes the cookie, so the old token no longer works even if sent again (PBI 32). Logging out twice, or without a session, does nothing.

The cookie is HttpOnly, so only the server can remove it. If the server cannot be reached, the session is still open: the user stays on the page and a notice under the nav bar says "Could not log out: the login service is not responding. Try again." They are never shown the Login page while still logged in.

Sessions are removed at once when an account is deleted (the database deletes them with the account) and stop working at once when an account is not active.

---

## API

### `GET /health`

```json
{"status": "ok"}
```

### `POST /auth/login`

Request:

```json
{"email": "sara.q@moh.gov.sa", "password": "orbit maple quiet river"}
```

Response `200`, with the `jaadah_session` cookie:

```json
{"user": {"id": "3f9a…", "name": "Sara Alqahtani", "email": "sara.q@moh.gov.sa", "role": "engineer"}}
```

Errors are `{"detail": "<message>"}` with `401`, `403` or `429`, as listed under [Login](#login). The messages are written to be shown to the user as they are.

### `POST /auth/logout`

`204`, no body. Removes the session and the cookie.

### `GET /auth/me`

The logged-in user, in the same shape as the login response, or `401` `{"detail": "Log in to continue."}`.

The password hash is never sent.

---

## Storage

`AccountStorage` is the only code that touches the database. Its clock can be replaced, which the tests use to move time.

**accounts**: one row per account.

| Column | Meaning |
|---|---|
| `id` | random 32-character id; never given to a second account after a delete |
| `name`, `email` | the email is stored trimmed and lowercased, and is unique |
| `role` | `admin` or `engineer` |
| `status` | `active` or `inactive` |
| `password_hash` | the Argon2id string |
| `created_at` | when the account was created |

**sessions**: one row per logged-in browser.

| Column | Meaning |
|---|---|
| `token_digest` | SHA-256 of the session token |
| `account_id` | the account; the row is deleted with the account |
| `expires_at` | 8 hours after login |
| `last_seen_at` | the latest request |

**login_attempts**: one row per email with recent wrong passwords, whether or not an account has that email.

| Column | Meaning |
|---|---|
| `email` | as typed, trimmed and lowercased |
| `failed_logins` | wrong passwords in a row |
| `last_failed_at` | the latest wrong password |
| `paused_until` | the end of a login pause, if any |

Times are stored in UTC: they are only compared, never shown. A session started at 09:00 Riyadh time is stored as 06:00 UTC.

---

## Security Limits

- **HTTPS.** The local website runs on `http://localhost`, so the cookie is sent without the `Secure` flag. NFR-03 requires HTTPS when Jaadah is reached over a network; start the accounts server with `JAADAH_SECURE_COOKIE=true` there.
- **Traffic servers.** Only the website checks the role; the traffic servers answer without a session.
- **Passwords set by an administrator.** The administrator knows an engineer's password when handing it over, and engineers cannot change their own password.

---

## Testing

```bash
python -m pytest backend/accounts
```

109 tests, all with artificial accounts and temporary databases:

| File | Tests | Covers |
|---|---|---|
| `test_passwords.py` | 25 | length limits and code points, NFC, the common-password list (whole password, any case), the name, email and "jaadah" rule, Argon2id settings, salts, wrong and damaged hashes |
| `test_storage.py` | 34 | accounts (random ids, lowercase unique emails, roles), the pause per email with and without an account, forgetting old counts, made-up emails not piling up, sessions (SHA-256 only, 8 hours, 30 minutes idle, logout, inactive and deleted accounts) |
| `test_server.py` | 39 | login for both roles, cookie settings and `JAADAH_SECURE_COOKIE`, the same answers and one password check per attempt for real and unknown emails (also over 6 attempts and while paused), input length limits, the deactivated message only with the right password, the 30-minute pause, logging in again, logout, both session limits, the hash never sent |
| `test_create_admin.py` | 11 | creating an administrator who can then log in, refused passwords, names, emails and duplicates, running as a module |

For the website, `npm run lint` and `npm run build` in `frontend/`.

---

## Sources

- NIST SP 800-63B-4, *Digital Identity Guidelines: Authentication and Authenticator Management* (2025), https://doi.org/10.6028/NIST.SP.800-63B-4: password length, no composition rules, blocklist and whole-password comparison, NFC normalisation, limits on failed attempts, reauthentication and inactivity timeouts.
- OWASP Password Storage Cheat Sheet, https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html: Argon2id and its minimum settings.
- OWASP Session Management Cheat Sheet, https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html: idle timeout ranges.
- UK National Cyber Security Centre, list of the 100,000 most used passwords (2019), with Have I Been Pwned; copy from SecLists, MIT License.
- Jaadah Product Backlog: PBI 31, PBI 32 and NFR-03.
