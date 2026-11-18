"""
Password rules, hashing and checking for Jaadah accounts.

The rules follow NIST SP 800-63B-4 (section 3.1.1.2, password
verifiers); the hashing follows the OWASP Password Storage Cheat
Sheet. Why each rule was chosen is explained in docs/accounts.md.

    password_problem(password, name, email)  why a new password is
                                             refused, or None
    hash_password(password)                  the string to store
    verify_password(stored, password)        True if they match
"""

import re
import unicodedata
from pathlib import Path

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError


# ============================================================
# RULES (NIST SP 800-63B-4)
# ============================================================

# A password is the only login factor, so at least 15 characters.
# NIST asks to allow at least 64; Jaadah allows exactly 64.
MIN_LENGTH = 15
MAX_LENGTH = 64

# The service name: like the engineer's name and email, a password
# made only of these words is refused
SERVICE_WORDS = ("jaadah",)

# Common passwords of 15 to 64 characters (UK NCSC list, see the
# file's header for the source and licence)
COMMON_PASSWORDS_FILE = Path(__file__).with_name("common_passwords.txt")


# ============================================================
# HASHING (OWASP minimum for Argon2id)
# ============================================================

# 19 MiB of memory, 2 iterations, 1 degree of parallelism. The
# package adds a random 16-byte salt to every hash and stores the
# algorithm, settings, salt and hash in one string.
HASHER = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)


def load_common_passwords(path: Path = COMMON_PASSWORDS_FILE) -> frozenset[str]:
    """Read the blocklist: one lowercase password per line, # for comments."""

    with open(path, encoding="utf-8") as file:
        return frozenset(
            line.rstrip("\r\n")
            for line in file
            if line.strip() and not line.startswith("#")
        )


COMMON_PASSWORDS = load_common_passwords()


def letters_only(text: str) -> str:
    """Lowercase letters of a text, without digits, spaces or symbols.

    "Sara.Alqahtani2026" becomes "saraalqahtani".
    """

    return "".join(char for char in text.casefold() if char.isalpha())


def context_words(name: str, email: str) -> set[str]:
    """The words an engineer's own password must not be made of.

    The parts of the name, the parts of the email before the @, and the
    service name. "Sara Alqahtani", "sara.q@moh.gov.sa" gives
    {"sara", "alqahtani", "q", "jaadah"}.
    """

    local_part = email.split("@", 1)[0]
    parts = re.split(r"[^\w]|[\d_]", f"{name} {local_part}".casefold())
    words = {letters_only(part) for part in parts}
    words.update(SERVICE_WORDS)
    words.discard("")

    return words


def made_of_words(letters: str, words: set[str]) -> bool:
    """True if the letters split completely into the given words.

    "saraalqahtani" splits into "sara" + "alqahtani";
    "saralikeslongmorningwalks" does not split.
    """

    if not letters:
        return False

    # can_end[i]: the first i letters split completely into words
    can_end = [True] + [False] * len(letters)
    for end in range(1, len(letters) + 1):
        can_end[end] = any(
            can_end[end - len(word)] and letters.endswith(word, 0, end)
            for word in words
            if len(word) <= end
        )

    return can_end[-1]


def password_problem(password: str, name: str, email: str) -> str | None:
    """Why a new password for this engineer is refused, or None if it is accepted.

    The message can be shown to the administrator as it is.
    """

    # Each Unicode code point counts as one character (NIST)
    password = normalise(password)
    length = len(password)
    if length < MIN_LENGTH:
        return f"Use at least {MIN_LENGTH} characters. A short phrase works well."
    if length > MAX_LENGTH:
        return f"Use at most {MAX_LENGTH} characters."

    # The whole password is compared, not parts of it (NIST)
    if password.casefold() in COMMON_PASSWORDS:
        return "This password is too common. Choose another one."

    if made_of_words(letters_only(password), context_words(name, email)):
        return "Do not build the password from the engineer's name, email or Jaadah."

    return None


def normalise(password: str) -> str:
    """The same password typed on different devices gives the same text.

    NIST asks for NFC normalisation before hashing: "é" typed as one
    character or as "e" + accent becomes the same single character.
    """

    return unicodedata.normalize("NFC", password)


def hash_password(password: str) -> str:
    """The Argon2id string to store for a password."""

    return HASHER.hash(normalise(password))


def verify_password(stored: str, password: str) -> bool:
    """True if the password matches the stored Argon2id string."""

    try:
        return HASHER.verify(stored, normalise(password))
    except (VerificationError, InvalidHashError):
        return False
