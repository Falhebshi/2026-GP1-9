"""
Random passphrases for the Generate button (ADM-01 and ADM-05).

Five words picked at random from the EFF large word list (7,776 words)
with Python's secrets module, joined by hyphens, e.g.
"lantern-orbit-maple-quiet-river". Each word adds log2(7776) = 12.9 bits,
so five words give about 65 bits. Words are 3 to 9 letters, so a
passphrase is 19 to 49 characters: always inside the 15 to 64 character
rule (passwords.py). The server still checks it like any password.

Word list: eff_large_wordlist.txt, the EFF Large Wordlist for
Passphrases by Joseph Bonneau and the Electronic Frontier Foundation
(2016), https://www.eff.org/dice, licensed under Creative Commons
Attribution 3.0 United States (CC BY 3.0 US). The file is kept exactly
as published (SHA-256 below), so it can be checked against EFF's copy.
"""

import hashlib
import secrets
from pathlib import Path

WORDLIST_FILE = Path(__file__).with_name("eff_large_wordlist.txt")

# The SHA-256 of eff.org/files/2016/07/18/eff_large_wordlist.txt
WORDLIST_SHA256 = "addd35536511597a02fa0a9ff1e5284677b8883b83e986e43f15a3db996b903e"

WORD_COUNT = 5
SEPARATOR = "-"


def load_words(path: Path = WORDLIST_FILE) -> tuple[str, ...]:
    """The words of the list, in order: each line is a dice number, a tab, a word."""

    with open(path, encoding="utf-8") as file:
        return tuple(line.rstrip("\r\n").split("\t")[1] for line in file if line.strip())


WORDS = load_words()


def generate_passphrase() -> str:
    """Five random words from the EFF list, joined by hyphens."""

    return SEPARATOR.join(secrets.choice(WORDS) for _ in range(WORD_COUNT))


def wordlist_sha256(path: Path = WORDLIST_FILE) -> str:
    """The SHA-256 of the word list file, to check it is EFF's exact file."""

    return hashlib.sha256(path.read_bytes()).hexdigest()
