"""Guards against a source file going invisible to tooling.

An unanchored .gitignore pattern (`models/` rather than `/models/`) once
silently matched packages/core/src/cip/core/models/. Ruff, mypy and
import-linter all respect .gitignore by default, so an entire package went
unchecked for a full story while every run reported success - there was
nothing wrong to see, because there was nothing left to look at.

Two independent checks: the first asks git directly whether any real
source file is ignored right now, which is the actual failure mode.  The
second audits .gitignore's own patterns so the same mistake cannot be
reintroduced by a future line that looks as innocuous as `models/` did.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Patterns we have deliberately chosen to match at any depth, because they
# name build/tool artefacts that legitimately appear inside every package,
# not just at the repository root.
DELIBERATE_DEEP_MATCHES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


def _source_python_files() -> list[str]:
    files = [*(ROOT / "packages").rglob("*.py"), *(ROOT / "tests").rglob("*.py")]
    return sorted(p.relative_to(ROOT).as_posix() for p in files)


def test_no_python_source_file_is_gitignored():
    """The real guard: ask git, right now, whether anything under
    packages/ or tests/ is invisible to it - and therefore to ruff, mypy
    and import-linter, which all skip whatever git ignores.
    """
    files = _source_python_files()
    assert files, "no .py files found under packages/ or tests/ - something is very wrong"

    # --no-index matters: without it, git check-ignore silently exempts
    # any path already in the index, so a file that is tracked today
    # would never trip this guard even if a new pattern started matching
    # it - exactly the blind spot this test exists to close. Bytes in,
    # bytes out because subprocess's text mode translates "\n" to the
    # platform line ending on write, which on Windows leaves a trailing
    # "\r" on every path git echoes back; encoding by hand avoids that.
    result = subprocess.run(
        ["git", "check-ignore", "--verbose", "--no-index", "--stdin"],
        input=("\n".join(files) + "\n").encode("utf-8"),
        capture_output=True,
        cwd=ROOT,
        check=False,
    )

    ignored = [line for line in result.stdout.decode("utf-8").splitlines() if line.strip()]
    assert ignored == [], (
        "these source files are matched by .gitignore and therefore invisible "
        "to ruff, mypy and import-linter (pattern -> file):\n" + "\n".join(ignored)
    )


def _is_wildcard(pattern: str) -> bool:
    return any(ch in pattern for ch in "*?[")


def _is_anchored(pattern: str) -> bool:
    """Whether git will only ever match this pattern relative to the
    repository root - true for a leading slash, and, per gitignore's own
    rules, for any pattern with a slash anywhere before the final
    character (it is then relative to the .gitignore's own directory,
    never matched at arbitrary depth).
    """
    if pattern.startswith("/"):
        return True
    return "/" in pattern.rstrip("/")


def test_every_gitignore_directory_pattern_is_anchored_or_deliberately_deep():
    """Every directory pattern in .gitignore must either be anchored to
    the repository root or be one of DELIBERATE_DEEP_MATCHES above.
    Anything else is a `models/`-shaped trap waiting for a package with
    the same name.
    """
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

    unanchored = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.startswith(("#", "!")):
            continue
        if not line.endswith("/"):
            continue  # not a directory pattern
        if _is_wildcard(line):
            # A name-shaped pattern like *.egg-info/, not a literal
            # directory - matching at any depth is its whole point.
            continue
        if line.rstrip("/") in DELIBERATE_DEEP_MATCHES:
            continue
        if not _is_anchored(line):
            unanchored.append(line)

    assert unanchored == [], (
        "these .gitignore directory patterns match at any depth, which is how "
        "packages/core/src/cip/core/models/ went invisible for a full story: "
        f"{unanchored}. Anchor with a leading slash, or add to "
        "DELIBERATE_DEEP_MATCHES above if matching at any depth is intended."
    )
