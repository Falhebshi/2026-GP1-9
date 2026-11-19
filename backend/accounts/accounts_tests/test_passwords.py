import pytest

from backend.accounts.passwords import (
    COMMON_PASSWORDS,
    MAX_LENGTH,
    MIN_LENGTH,
    context_words,
    hash_password,
    letters_only,
    load_common_passwords,
    made_of_words,
    password_problem,
    verify_password,
)

# An artificial engineer, not a real account
NAME = "Sara Alqahtani"
EMAIL = "sara.q@moh.gov.sa"


def problem(password):
    return password_problem(password, NAME, EMAIL)


# ============================================================
# LENGTH
# ============================================================

def test_length_limits_are_15_and_64():
    assert (MIN_LENGTH, MAX_LENGTH) == (15, 64)


def test_14_characters_are_refused_and_15_are_accepted():
    assert "at least 15" in problem("orbit maple ri")      # 14
    assert problem("orbit maple riv") is None              # 15


def test_64_characters_are_accepted_and_65_are_refused():
    assert problem("a" * 30 + " " + "b" * 33) is None     # 64
    assert "at most 64" in problem("a" * 30 + " " + "b" * 34)  # 65


def test_each_unicode_code_point_counts_as_one_character():
    # 15 Arabic letters (one code point each): long enough
    assert problem("طريقالملكفهدجسر") is None
    # "é" typed as "e" + accent is 15 code points, but 14 after NFC
    assert len("cafe\u0301 orbit map") == 15
    assert "at least 15" in problem("cafe\u0301 orbit map")


# ============================================================
# COMMON PASSWORDS
# ============================================================

def test_the_blocklist_has_the_329_long_ncsc_entries():
    # 331 entries of 15 to 64 characters, 329 after lowercasing
    assert len(COMMON_PASSWORDS) == 329
    assert all(MIN_LENGTH <= len(entry) <= MAX_LENGTH for entry in COMMON_PASSWORDS)
    assert all(entry == entry.casefold() for entry in COMMON_PASSWORDS)


def test_long_common_passwords_are_refused_in_any_case():
    for password in (
        "1q2w3e4r5t6y7u8i9o0p",
        "123456789987654321",
        "1Q2W3E4R5T6Y7U8I9O0P",
    ):
        assert "too common" in problem(password)


def test_the_whole_password_is_compared_not_parts_of_it():
    # Contains a listed password, but is not one
    assert problem("1q2w3e4r5t6y7u8i9o0p river") is None


def test_comment_and_blank_lines_are_not_passwords(tmp_path):
    path = tmp_path / "list.txt"
    path.write_text("# a comment\n\nfirst entry long\r\nsecond entry long\n")

    assert load_common_passwords(path) == {"first entry long", "second entry long"}


# ============================================================
# NAME, EMAIL AND "JAADAH"
# ============================================================

def test_letters_only_drops_digits_spaces_and_symbols():
    assert letters_only("Sara.Alqahtani2026") == "saraalqahtani"


def test_context_words_come_from_name_email_and_service():
    assert context_words(NAME, EMAIL) == {"sara", "alqahtani", "q", "jaadah"}
    # Hyphens, digits and underscores split words too
    assert context_words("Omar Al-Harbi", "omar_h2@ksu.edu.sa") == {
        "omar", "al", "harbi", "h", "jaadah",
    }


@pytest.mark.parametrize(
    ("password", "refused"),
    [
        # The table agreed for this rule
        ("Sara.Alqahtani2026", True),
        ("jaadah-sara-2026!", True),
        ("sara likes long morning walks", False),
        ("orbit maple quiet river jaadah", False),
        # More derivatives
        ("SARAQ-SARAQ-2026", True),
        ("alqahtani jaadah 99", True),
        ("jaadahjaadahjaadah", True),
        # Only digits and symbols: no letters, so not this rule
        ("2026-2026-2026-20", False),
    ],
)
def test_passwords_made_only_of_context_words_are_refused(password, refused):
    result = problem(password)

    if refused:
        assert "name, email or Jaadah" in result
    else:
        assert result is None


def test_made_of_words_needs_a_complete_split():
    words = {"sara", "alqahtani"}

    assert made_of_words("saraalqahtani", words)
    assert made_of_words("alqahtanisara", words)
    assert not made_of_words("saraalqahtanix", words)
    assert not made_of_words("", words)


def test_the_rule_uses_this_engineers_name_only():
    # Sara's name in Omar's password is just a word
    assert password_problem("sara alqahtani 2026", "Omar Alharbi", "omar@ksu.edu.sa") is None


# ============================================================
# HASHING
# ============================================================

def test_a_hash_is_argon2id_with_the_owasp_settings():
    stored = hash_password("orbit maple quiet river")

    assert stored.startswith("$argon2id$v=19$m=19456,t=2,p=1$")
    assert "orbit" not in stored


def test_the_same_password_gets_a_different_salt_each_time():
    first = hash_password("orbit maple quiet river")
    second = hash_password("orbit maple quiet river")

    assert first != second
    assert verify_password(first, "orbit maple quiet river")
    assert verify_password(second, "orbit maple quiet river")


def test_a_wrong_password_does_not_verify():
    stored = hash_password("orbit maple quiet river")

    assert not verify_password(stored, "orbit maple quiet rivers")
    assert not verify_password(stored, "")


def test_a_damaged_stored_hash_does_not_verify():
    assert not verify_password("not a hash", "orbit maple quiet river")


def test_both_ways_of_typing_an_accent_verify():
    stored = hash_password("caf\u00e9 orbit maple river")      # é as one character

    assert verify_password(stored, "cafe\u0301 orbit maple river")  # e + accent
