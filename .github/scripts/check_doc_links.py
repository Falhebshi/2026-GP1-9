"""
Check the relative links in the README and the docs.

Every link to a file in the repository must point to a file that
exists, and every link to a heading (#anchor) must point to a heading
that exists in that file, named as GitHub names it. Links to websites
are not checked. Exits with code 1 and lists every broken link.

    python .github/scripts/check_doc_links.py
"""

import re
import sys
from pathlib import Path
from urllib.parse import unquote

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKED = ["README.md", "docs/**/*.md", "simulation/scene_3d/README.md", ".github/CONTRIBUTING.md"]

LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)")
HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
FENCE = re.compile(r"^\s*(```|~~~)")


def without_code(text: str) -> list[str]:
    """The file's lines, with fenced code blocks and inline code blanked out."""

    lines, in_fence = [], False
    for line in text.splitlines():
        if FENCE.match(line):
            in_fence = not in_fence
            lines.append("")
            continue
        lines.append("" if in_fence else re.sub(r"`[^`]*`", "", line))
    return lines


def anchors(path: Path) -> set[str]:
    """The #anchors GitHub gives the file's headings."""

    seen: dict[str, int] = {}
    found = set()
    for line in without_code(path.read_text(encoding="utf-8")):
        match = HEADING.match(line)
        if not match:
            continue
        text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", match.group(2))
        slug = re.sub(r"[^\w\- ]", "", text.strip().lower()).replace(" ", "-")
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        found.add(slug if count == 0 else f"{slug}-{count}")
    return found


def broken_links(path: Path) -> list[str]:
    problems = []
    for number, line in enumerate(without_code(path.read_text(encoding="utf-8")), start=1):
        for target in LINK.findall(line):
            if re.match(r"^[a-z]+:", target):
                continue  # a website or mailto link

            file_part, _, anchor = target.partition("#")
            linked = (path.parent / unquote(file_part)).resolve() if file_part else path

            where = f"{path.relative_to(REPO_ROOT)}:{number}"
            if not linked.exists():
                problems.append(f"{where}: {target} (no such file)")
            elif anchor and linked.suffix == ".md" and anchor not in anchors(linked):
                problems.append(f"{where}: {target} (no such heading)")
    return problems


def main() -> int:
    files = sorted({file for pattern in CHECKED for file in REPO_ROOT.glob(pattern)})
    problems = [problem for file in files for problem in broken_links(file)]

    for problem in problems:
        print(problem)
    print(f"{len(files)} files checked, {len(problems)} broken links")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
