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
    ├── passphrase.py          random passphrases for the Generate button
    ├── eff_large_wordlist.txt the EFF word list the passphrases come from
    ├── storage.py             SQLite storage: accounts and sessions
    ├── server.py              FastAPI service: login, logout, who is logged in,
    │                          and the administrator endpoints
    ├── create_admin.py        command that creates an administrator
    └── accounts_tests/        tests

frontend/src/
├── services/authService.js    login calls to the accounts server
├── services/adminService.js   administrator calls to the accounts server
├── components/RequireRole.jsx which pages each role can open
└── pages/
    ├── AdminDashboard.jsx     the administrator's page
    └── admin/                 its parts: the engineer list, the details
                               panel, the Create account form
```

This document covers the backlog items PBI 31 (log in), PBI 32 (log out), ADM-02 (list engineers), ADM-01 (create engineer accounts), ADM-03 (activate and deactivate), ADM-05 (change an engineer's password), ADM-04 (delete an engineer account) and the account parts of NFR-03 (security). The standards behind each rule are listed under [Sources](#sources).

---

## Running It

The accounts database starts empty and Jaadah has no default login, so create an administrator once:

```bash
python -m backend.accounts.create_admin --name "Noura Almutairi" --email noura@ksu.edu.sa
```

It asks for the password twice without showing it on screen, checks it with the [password rules](#password-rules), and stores only its hash. Run it again for each extra administrator.

To set up your own laptop in one step, add `--engineer-email` to also create your traffic engineer account, with the same name and password:

```bash
python -m backend.accounts.create_admin --name "Noura Almutairi" --email noura.admin@ksu.edu.sa --engineer-email noura@ksu.edu.sa
```

The two emails must differ, the password must not be made of the name or either email, and if either email already has an account nothing is created.

Accounts live in each laptop's own database: an account created on one laptop does not exist on another. Each teammate sets up their own. Engineer accounts are created by an administrator on the [Admin Dashboard](#admin-dashboard).

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

## Admin Dashboard

The Admin Dashboard (`/admin`) has the list of engineer accounts on the left and a **panel** on the right (under the list on a narrow screen).

### The List of Engineers (ADM-02)

Every engineer account, with its name, email and status, ordered by name A to Z ignoring capital letters. Administrators are not listed: they are managed only with `create_admin`.

| Status | Shown as |
|---|---|
| `active` | green "Active" badge |
| `inactive` | grey "Inactive" badge |

With no engineer accounts the page says "No engineer accounts yet" and invites the administrator to create one.

Clicking an engineer selects them (their row turns lavender with an indigo bar) and opens their **details** in the panel: email, status and the date the account was created (in Riyadh time), with the account actions underneath.

### Activating and Deactivating (ADM-03)

| The engineer is | The panel offers | What happens |
|---|---|---|
| Active | **Deactivate** | The panel asks first: "Deactivate Sara Alqahtani? They'll be logged out at once and can't log in until the account is activated again." **Cancel** changes nothing; **Deactivate** makes the account inactive. |
| Inactive | **Activate** | No question: activating harms no one. The account is active again at once. |

Deactivating **ends all of the engineer's sessions at once** on the server, so any request they make is refused from that moment. A page already open on their screen stays visible until their browser next asks the server: on their next page change, or on their first click, key or scroll once 5 minutes have passed since it last asked (see [Sessions](#sessions)). It then sends them to Login, and logging in again answers "Your account is deactivated. Contact the administrator." (see [Login](#login)). Reactivating lets them log in again with the same password. The new status appears in the list and the panel, with a line under the header: "Sara Alqahtani's account is deactivated." or "…is active again."

If another tab deleted the account meanwhile, the action answers "This account no longer exists." and the list refreshes.

### Changing a Password (ADM-05)

**Change password** opens a form in the panel under the engineer's details:

| Field | Checked in the browser | Checked again by the server |
|---|---|---|
| New password | 15 to 64 characters | all the [password rules](#password-rules), with **this engineer's** name and email |
| Confirm new password | the same as the new password | |

Both fields are hidden by default with **Show**/**Hide**; the new password also has **Copy** and **Generate** (a [random passphrase](#generated-passphrases) in both fields). The form says: "Copy the password before you save; it won't be shown again. Sara Alqahtani will be logged out and must use the new password."

**Save password** stores the new password as an Argon2id hash and shows "Password changed for Sara Alqahtani." Then:

- the old password no longer works, and the new one works at once;
- **all of the engineer's sessions end**, as for deactivating;
- any [login pause](#too-many-wrong-passwords) on the engineer's email is cleared, so an engineer who was locked out after 5 wrong passwords can log in with the new one straight away;
- the new password is not shown or kept anywhere;
- the account's status does not change.

**Cancel** closes the form and changes nothing. A refused password (too short, common, made of the engineer's own name or email) shows its message under the field and changes nothing; it is never hashed.

### Deleting an Account (ADM-04)

**Delete account** (the red button) asks first: "Delete Omar Alharbi's account? This can't be undone. They won't be able to log in, and the account is removed from the list." **Cancel** changes nothing; the red **Delete account** under the question deletes the account. Then:

- the account is removed from the database, and from the list, with nothing selected and the line "Omar Alharbi's account was deleted.";
- **all of the engineer's sessions end** with it, as for deactivating;
- logging in with that email and password answers "Email or password is incorrect.", the same as for any email without an account;
- the email can be used again for a new account, which gets a new id and a new password.

Deleting is for an account that should not come back, such as one created with a mistake; **Deactivate** keeps the account for later. Administrators cannot be deleted from the dashboard. If another tab already deleted the account, the action answers "This account no longer exists." and the list refreshes.

### Creating an Engineer Account (ADM-01)

**Create account** opens the form in the panel:

| Field | Checked in the browser | Checked again by the server |
|---|---|---|
| Name | not empty | not empty, at most 100 characters |
| Work email | looks like `name@organization.gov.sa` | the same, at most 254 characters, and no account already has it |
| Password | 15 to 64 characters | all the [password rules](#password-rules) |
| Confirm password | the same as the password | |

The password is hidden by default, with **Show**/**Hide**, **Copy**, and **Generate**, which fills both password fields with a [random passphrase](#generated-passphrases).

**Create account** on the form opens a **confirmation** step showing the name, email, role ("Traffic engineer") and the password, hidden unless the administrator selects Show. **Back** returns to the form with everything kept; **Confirm** creates the account. If the server refuses something (the email already has an account, a common password, a password made of the person's name), the form comes back with the message under that field.

After the account is created, the new engineer appears in the list, selected, with "Account created for Omar Alharbi." The password is then **not shown or kept anywhere**: only its Argon2id hash is stored. The form says so before confirming: "Copy the password before you confirm; it won't be shown again." A name or email cannot be edited afterwards; a forgotten password is replaced with Change password (ADM-05).

The new engineer can log in at once and lands on Network Traffic Overview.

### Generated Passphrases

**Generate** asks the server for five words picked at random from the **EFF large word list** (7,776 words) with Python's `secrets` module, joined by hyphens:

```text
lantern-orbit-maple-quiet-river
```

Each word adds log2(7,776) = 12.9 bits of randomness, so five words give about 65 bits. The words have 3 to 9 letters, so a passphrase is always 19 to 49 characters, inside the 15 to 64 rule. The server still checks it like any password. NIST allows a password either chosen by the user or "assigned randomly by the CSP"; a five-word phrase is far easier to type and hand over than a random string of the same strength.

`eff_large_wordlist.txt` is kept exactly as EFF publishes it, so its SHA-256 can be compared with EFF's file at https://www.eff.org/files/2016/07/18/eff_large_wordlist.txt:

```text
addd35536511597a02fa0a9ff1e5284677b8883b83e986e43f15a3db996b903e
```

The EFF Large Wordlist for Passphrases is by Joseph Bonneau and the Electronic Frontier Foundation (2016), https://www.eff.org/dice, licensed under Creative Commons Attribution 3.0 United States (CC BY 3.0 US). The copy comes from EFF's repository `EFForg/eff_diceware`.

---

## Password Rules

`password_problem(password, name, email)` returns why a new password is refused, or `None`. The same rules apply to every account and to `create_admin`. They follow NIST SP 800-63B-4, which applies when a password is the only login factor, as in Jaadah.

The same rules apply to passwords typed by an administrator, generated passphrases and `create_admin`. The password is first normalised to Unicode NFC, so "é" typed as one character or as "e" plus an accent is the same password. Then, in order:

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

The cookie is HttpOnly, so only the server can remove it. If the server cannot be reached, the session is still open: the user stays on the page and a notice under the nav bar says "Could not log out: the login service is not responding. Try again." The notice belongs to that page and is not shown after moving to another one. They are never shown the Login page while still logged in.

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

### Administrator Endpoints

Without a session these answer `401` `{"detail": "Log in to continue."}`; for an engineer, `403` `{"detail": "Only administrators can do this."}`.

#### `GET /admin/engineers`

```json
{"engineers": [
  {"id": "3f9a…", "name": "Omar Alharbi", "email": "omar@ksu.edu.sa",
   "status": "active", "created_at": "2026-11-18T06:00:00+00:00"}
]}
```

Ordered by name, ignoring capital letters. `created_at` is in UTC.

#### `POST /admin/engineers`

Request:

```json
{"name": "Omar Alharbi", "email": "omar@ksu.edu.sa", "password": "copper valley storm lamp"}
```

Response `201`: the new engineer, in the shape above. A refused field answers `400` (or `409` for an email that already has an account) with the field and a message to show under it:

```json
{"detail": {"field": "password", "message": "This password is too common. Choose another one."}}
```

| Field | Messages |
|---|---|
| `name` | Enter the engineer's name. · Use at most 100 characters. |
| `email` | Enter an email address like name@organization.gov.sa. · An account with this email already exists. (409) |
| `password` | any [password rule](#password-rules) message |

A refused password is never hashed.

#### `POST /admin/engineers/{id}/status`

Request: `{"status": "inactive"}` or `{"status": "active"}`. Response `200`: the engineer, with the new status. Making an account inactive ends all its sessions. An unknown id, or an administrator's, answers `404` `{"detail": "This account no longer exists."}`; any other status answers `422`.

#### `POST /admin/engineers/{id}/password`

Request: `{"password": "silver harbor quiet lamp"}`. Response `200`: the engineer (never the password). The engineer's sessions end and any login pause on their email is cleared. A refused password answers `400` `{"detail": {"field": "password", "message": "…"}}`; an unknown id, or an administrator's, answers `404` `{"detail": "This account no longer exists."}`.

#### `DELETE /admin/engineers/{id}`

Response `204` with no body. The account and all its sessions are deleted. An unknown id (including one already deleted), or an administrator's, answers `404` `{"detail": "This account no longer exists."}`.

#### `GET /admin/passphrase`

```json
{"passphrase": "lantern-orbit-maple-quiet-river"}
```

A new one on every request.

The password hash is never sent by any endpoint.

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

189 tests, all with artificial accounts and temporary databases:

| File | Tests | Covers |
|---|---|---|
| `test_passwords.py` | 25 | length limits and code points, NFC, the common-password list (whole password, any case), the name, email and "jaadah" rule, Argon2id settings, salts, wrong and damaged hashes |
| `test_storage.py` | 34 | accounts (random ids, lowercase unique emails, roles), the pause per email with and without an account, forgetting old counts, made-up emails not piling up, sessions (SHA-256 only, 8 hours, 30 minutes idle, logout, inactive and deleted accounts) |
| `test_server.py` | 39 | login for both roles, cookie settings and `JAADAH_SECURE_COOKIE`, the same answers and one password check per attempt for real and unknown emails (also over 6 attempts and while paused), input length limits, the deactivated message only with the right password, the 30-minute pause, logging in again, logout, both session limits, the hash never sent |
| `test_admin.py` | 72 | administrators only (401 and 403 on every admin endpoint), the list (fields, empty, no administrators, order by name ignoring case, inactive status), creating an engineer (role, Argon2id hash, appears in the list, can log in, trimmed and lowercased, every refused field and its message, duplicate emails including an administrator's, refused passwords never hashed), the word list's SHA-256, passphrase shape, strength and length; deactivating (status, sessions ended at once, login refused, other engineers and the admin unaffected), reactivating (can log in again), unknown and administrator ids (404), invalid statuses, engineers refused; changing a password (new one works, old one refused, new Argon2id hash, never sent back, sessions ended, login pause cleared, other engineers and the status unaffected, every refused password with its message and never hashed, the name rule using that engineer's name, unknown and administrator ids, engineers refused); deleting (removed from the list, cannot log in, sessions ended, the email reusable, a second delete 404, other engineers unaffected, administrators cannot be deleted, engineers refused) |
| `test_create_admin.py` | 19 | creating an administrator who can then log in, refused passwords, names, emails and duplicates, running as a module; with `--engineer-email`, both accounts with the same password and their own salts, both able to log in, different emails required, nothing created if either email is taken, the engineer email in the password rule |

For the website, `npm run lint` and `npm run build` in `frontend/`.

---

## Sources

- NIST SP 800-63B-4, *Digital Identity Guidelines: Authentication and Authenticator Management* (2025), https://doi.org/10.6028/NIST.SP.800-63B-4: password length, no composition rules, blocklist and whole-password comparison, NFC normalisation, limits on failed attempts, reauthentication and inactivity timeouts.
- OWASP Password Storage Cheat Sheet, https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html: Argon2id and its minimum settings.
- OWASP Session Management Cheat Sheet, https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html: idle timeout ranges.
- UK National Cyber Security Centre, list of the 100,000 most used passwords (2019), with Have I Been Pwned; copy from SecLists, MIT License.
- Joseph Bonneau and the Electronic Frontier Foundation, EFF Large Wordlist for Passphrases (2016), https://www.eff.org/dice, CC BY 3.0 US.
- Jaadah Product Backlog: PBI 31, PBI 32, ADM-01, ADM-02, ADM-03, ADM-04, ADM-05 and NFR-03.
