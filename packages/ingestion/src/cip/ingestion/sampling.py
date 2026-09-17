"""Reading headers and sampling values from a consultation export.

Classification lives in inspect.py; this module only gets bytes and rows
off disk. Encoding detection has to happen here, before a single row can
be decoded, so it cannot be deferred to whatever reads the sample next.
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_SAMPLE_SIZE = 200


def detect_encoding(raw: bytes) -> str:
    """Citizen Space exports are usually utf-8-sig. A department that
    opens one in Excel and re-saves it typically produces cp1252 instead
    - which does not fail to open, it silently turns curly quotes and em
    dashes into different, wrong characters. Encoding has to be detected
    from the bytes themselves; assuming utf-8 would let that corruption
    through unnoticed.
    """
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    try:
        raw.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return "cp1252"


def source_sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class Sample:
    """A header, a spread of sampled rows, and what it took to read them."""

    header: tuple[str, ...]
    rows: tuple[dict[str, str], ...]
    total_rows: int
    encoding: str
    source_sha256: str


def read_sample(path: Path, *, sample_size: int = DEFAULT_SAMPLE_SIZE) -> Sample:
    """Reads the header and up to `sample_size` data rows, spread evenly
    across the whole file rather than taken from the top.

    The first rows of a consultation are often test submissions entered
    by the department while checking the form works, and are not
    representative of what respondents actually send - sampling only
    the top of the file would classify columns against exactly the rows
    least likely to look like real answers.
    """
    raw = path.read_bytes()
    encoding = detect_encoding(raw)

    with path.open("r", newline="", encoding=encoding) as f:
        reader = csv.DictReader(f)
        header = tuple(reader.fieldnames or ())
        all_rows = list(reader)

    total_rows = len(all_rows)
    if total_rows <= sample_size:
        sampled = all_rows
    elif sample_size <= 1:
        sampled = all_rows[:1]
    else:
        indices = sorted(
            {round(i * (total_rows - 1) / (sample_size - 1)) for i in range(sample_size)}
        )
        sampled = [all_rows[i] for i in indices]

    return Sample(
        header=header,
        rows=tuple(sampled),
        total_rows=total_rows,
        encoding=encoding,
        source_sha256=source_sha256(raw),
    )
