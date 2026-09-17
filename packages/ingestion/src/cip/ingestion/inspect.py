"""`cip inspect`: proposes a draft column manifest for a human to review.

This tool exists to be corrected, not trusted. If it is usually right,
people stop reading its output and start accepting it unchanged - and
the one time it misclassifies an email column as free text, nobody
notices, and addresses end up in a thematic summary someone else reads.
So it guesses only where the evidence is strong, marks everything else
`unknown` with a stated reason, and never guesses at a column that might
hold a person's name under any circumstances: names are the single
highest-cost misclassification here, and no header or value heuristic
for them is reliable enough to trust.

Reads headers and samples values only. It does not process responses,
and it does not decide anything on a human's behalf - every column it
proposes still has to be read and confirmed before this file means
anything.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from functools import partial
from pathlib import Path
from typing import TextIO

import yaml
from cip.core.models import ColumnRole, IdentityHandling, Manifest, SourceFormat
from cip.ingestion.sampling import Sample, read_sample, source_sha256

# --- attachment limits ------------------------------------------------------
#
# Every one of these is a refusal threshold, not a truncation point. When a
# cap is exceeded the rule is always: quarantine the attachment, keep the
# submission - never truncate and index what's left. Parsing the first 150
# pages of a 400-page report and indexing that silently is worse than
# refusing it outright, because a citation could then point at a section
# that exists while a contradicting section sits unindexed and invisible to
# every search that follows. A quarantined attachment is a visible gap a
# reviewer can go looking for; a silently truncated one is not.

MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024
"""Above this, an attachment is quarantined unread rather than parsed."""

MAX_ATTACHMENT_PAGES = 150
"""Above this many pages, quarantine rather than parse and index a partial document."""

MAX_EXTRACTED_CHARS = 500_000
"""Above this many extracted characters, quarantine rather than index a partial extraction."""

PARSE_TIMEOUT_SECONDS = 120
"""A parse that has not finished by this point is quarantined, not left to run further."""

MAX_CHUNKS_PER_DOCUMENT = 1_000
"""Above this many chunks, quarantine rather than index a partial chunk set."""

MAX_ZIP_DEPTH = 3
"""Nested archives beyond this depth are quarantined rather than recursed into further."""

MAX_ZIP_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
"""A zip that would decompress past this size is quarantined unread, to bound a zip bomb."""


# --- classification thresholds ----------------------------------------------

MIN_NON_EMPTY_SAMPLE = 20
"""Fewer non-empty sampled values than this and no guess is trustworthy."""

_STRONG_MATCH_RATIO = 0.95
_ATTACHMENT_MATCH_RATIO = 0.8
_RESPONDENT_TYPE_MAX_CARDINALITY = 8
_RESPONDENT_TYPE_MAX_AVG_LENGTH = 40.0
_RESPONDENT_TYPE_MIN_PRESENCE = 0.8
_FREE_TEXT_MIN_AVG_LENGTH = 30.0
_FREE_TEXT_MIN_UNIQUE_RATIO = 0.9
_FREE_TEXT_MIN_EMPTY_RATIO = 0.3

MAX_CONFIDENCE = 0.95
"""Confidence is capped below 1.0 deliberately: nothing this tool proposes
is written to be trusted unread, however strong the evidence looked."""

_SAMPLE_DISPLAY_WIDTH = 40
_MASKED_DISPLAY = "<hidden>"

_NAME_HEADER_RE = re.compile(r"\bname\b|\bsurname\b|\bforename\b|\bnickname\b", re.IGNORECASE)
_ID_HEADER_RE = re.compile(r"\bid\b|reference\s*number|\bref\s*no\b", re.IGNORECASE)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_UK_POSTCODE_RE = re.compile(r"^[A-Za-z]{1,2}\d[A-Za-z\d]?\s?\d[A-Za-z]{2}$")
_FILENAME_RE = re.compile(r"\.[A-Za-z0-9]{2,5}$")

_DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
    "%Y-%m-%dT%H:%M:%S",
)


def _parses_as_date(value: str) -> bool:
    for fmt in _DATE_FORMATS:
        try:
            datetime.strptime(value, fmt)  # noqa: DTZ007 - parseability only, value discarded
        except ValueError:
            continue
        else:
            return True
    return False


def _match_ratio(values: Sequence[str], pattern: re.Pattern[str]) -> float:
    if not values:
        return 0.0
    return sum(1 for v in values if pattern.match(v)) / len(values)


def _date_parse_ratio(values: Sequence[str]) -> float:
    if not values:
        return 0.0
    return sum(1 for v in values if _parses_as_date(v)) / len(values)


@dataclass(frozen=True, slots=True)
class _ColumnStats:
    total_sampled: int
    non_empty: list[str]
    non_empty_count: int
    distinct_count: int
    avg_length: float


def _compute_stats(values: Sequence[str]) -> _ColumnStats:
    non_empty = [v.strip() for v in values if v.strip() != ""]
    non_empty_count = len(non_empty)
    avg_length = (sum(len(v) for v in non_empty) / non_empty_count) if non_empty_count else 0.0
    return _ColumnStats(
        total_sampled=len(values),
        non_empty=non_empty,
        non_empty_count=non_empty_count,
        distinct_count=len(set(non_empty)),
        avg_length=avg_length,
    )


@dataclass(frozen=True, slots=True)
class ColumnClassification:
    """One column's proposed role, with the evidence a reviewer needs to
    check the reasoning rather than just the conclusion - every column
    gets a reason, including the confident ones.
    """

    header: str
    role: ColumnRole
    confidence: float
    reason: str
    handling: IdentityHandling | None = None
    sensitive: bool = False
    """True for identity columns and name-shaped headers: printing this
    column's sample value anywhere is exactly the mistake this tool
    exists to prevent."""
    sample_value: str | None = None


def _looks_sensitive(header: str, values: Sequence[str]) -> bool:
    """Whether this column's raw values must be masked wherever they are
    displayed, independent of whether there was enough evidence to
    confidently classify the column at all.

    This has to be evaluated separately from classify_column's decision
    tree, not folded into its branches: a column can fail the sample-size
    or evidence gates and still be full of email addresses. If
    sensitivity were only set on the confident identity branches, a
    column with too few samples to classify would fall through to a
    generic `unknown` result with sensitive=False, and its raw values
    would print unmasked - the exact accident this function exists to
    prevent.
    """
    if _NAME_HEADER_RE.search(header):
        return True
    if re.search(r"\bemail\b", header, re.IGNORECASE):
        return True
    if re.search(r"\bpost\s*code\b|\bzip\b", header, re.IGNORECASE):
        return True
    non_empty = [v.strip() for v in values if v.strip() != ""]
    if any(_EMAIL_RE.match(v) for v in non_empty):
        return True
    return any(_UK_POSTCODE_RE.match(v) for v in non_empty)


def classify_column(header: str, values: Sequence[str]) -> ColumnClassification:
    """Classifies one column from its header and its sampled values.

    Checked in order, first match wins: the name veto and the evidence
    gates (empty, too few samples) always run first and can never be
    overridden by a coincidental pattern match further down.
    """
    sensitive = _looks_sensitive(header, values)
    result = partial(ColumnClassification, header=header, sensitive=sensitive)

    if _NAME_HEADER_RE.search(header):
        return result(
            role=ColumnRole.UNKNOWN,
            confidence=0.0,
            reason=(
                "column header suggests this may hold a person's name; "
                "inspect never classifies a name column"
            ),
        )

    stats = _compute_stats(values)

    if stats.non_empty_count == 0:
        return result(
            role=ColumnRole.UNKNOWN, confidence=0.0, reason="column is empty in every sampled row"
        )

    if stats.non_empty_count < MIN_NON_EMPTY_SAMPLE:
        return result(
            role=ColumnRole.UNKNOWN,
            confidence=0.0,
            reason=(
                f"only {stats.non_empty_count} non-empty value(s) sampled, fewer than "
                f"the {MIN_NON_EMPTY_SAMPLE} needed for a confident guess"
            ),
        )

    if (
        _ID_HEADER_RE.search(header)
        and stats.non_empty_count == stats.total_sampled
        and stats.distinct_count == stats.non_empty_count
    ):
        return result(
            role=ColumnRole.SUBMISSION_ID,
            confidence=min(MAX_CONFIDENCE, 0.9),
            reason="header matches an id pattern and every sampled value is present and unique",
        )

    date_ratio = _date_parse_ratio(stats.non_empty)
    if date_ratio >= _STRONG_MATCH_RATIO:
        return result(
            role=ColumnRole.SUBMITTED_AT,
            confidence=min(MAX_CONFIDENCE, date_ratio),
            reason=f"{date_ratio:.0%} of sampled values parse as a date",
        )

    email_ratio = _match_ratio(stats.non_empty, _EMAIL_RE)
    if email_ratio >= _STRONG_MATCH_RATIO:
        return result(
            role=ColumnRole.IDENTITY,
            handling=IdentityHandling.HASH,
            confidence=min(MAX_CONFIDENCE, email_ratio),
            reason=f"{email_ratio:.0%} of sampled values match an email address shape",
        )

    postcode_ratio = _match_ratio(stats.non_empty, _UK_POSTCODE_RE)
    if postcode_ratio >= _STRONG_MATCH_RATIO:
        return result(
            role=ColumnRole.IDENTITY,
            handling=IdentityHandling.COARSEN,
            confidence=min(MAX_CONFIDENCE, postcode_ratio),
            reason=f"{postcode_ratio:.0%} of sampled values match a UK postcode shape",
        )

    filename_ratio = _match_ratio(stats.non_empty, _FILENAME_RE)
    if filename_ratio >= _ATTACHMENT_MATCH_RATIO:
        return result(
            role=ColumnRole.ATTACHMENT,
            confidence=min(MAX_CONFIDENCE, filename_ratio),
            reason=f"{filename_ratio:.0%} of sampled values look like a filename",
        )

    presence_ratio = stats.non_empty_count / stats.total_sampled
    if (
        stats.distinct_count <= _RESPONDENT_TYPE_MAX_CARDINALITY
        and stats.avg_length <= _RESPONDENT_TYPE_MAX_AVG_LENGTH
        and presence_ratio >= _RESPONDENT_TYPE_MIN_PRESENCE
    ):
        return result(
            role=ColumnRole.RESPONDENT_TYPE,
            confidence=min(MAX_CONFIDENCE, presence_ratio),
            reason=(
                f"{stats.distinct_count} distinct short value(s) present in "
                f"{presence_ratio:.0%} of sampled rows"
            ),
        )

    empty_ratio = 1 - presence_ratio
    unique_ratio = stats.distinct_count / stats.non_empty_count
    if (
        stats.avg_length >= _FREE_TEXT_MIN_AVG_LENGTH or unique_ratio >= _FREE_TEXT_MIN_UNIQUE_RATIO
    ) and empty_ratio >= _FREE_TEXT_MIN_EMPTY_RATIO:
        return result(
            role=ColumnRole.FREE_TEXT,
            confidence=min(MAX_CONFIDENCE, unique_ratio),
            reason=(
                f"long/varied values (avg {stats.avg_length:.0f} chars, {unique_ratio:.0%} "
                f"unique) and {empty_ratio:.0%} empty, consistent with respondents answering "
                "some but not all questions"
            ),
        )

    return result(
        role=ColumnRole.UNKNOWN,
        confidence=0.0,
        reason=(
            "signals conflict: cardinality and length sit between the free_text and "
            "respondent_type profiles"
        ),
    )


def classify_export(sample: Sample) -> list[ColumnClassification]:
    results = []
    for header in sample.header:
        values = [row.get(header, "") for row in sample.rows]
        classification = classify_column(header, values)
        sample_value = next((v for v in values if v.strip() != ""), None)
        results.append(replace(classification, sample_value=sample_value))
    return results


# --- draft manifest -----------------------------------------------------------


def build_draft_manifest(
    *,
    consultation: str,
    source_format: SourceFormat,
    sample: Sample,
    classifications: Sequence[ColumnClassification],
) -> tuple[dict[str, object], dict[str, str]]:
    """Builds the manifest as a plain dict (not a Manifest instance: a
    draft with unknown columns is not required to satisfy Manifest's own
    validators, only to become a Manifest once a human has resolved
    them) plus a header -> reason map for every column left unknown.
    """
    columns: dict[str, dict[str, object]] = {}
    questions: list[dict[str, object]] = []
    review_reasons: dict[str, str] = {}
    position = 0

    for c in classifications:
        column: dict[str, object] = {"role": c.role.value}
        if c.role is ColumnRole.IDENTITY:
            assert c.handling is not None
            column["handling"] = c.handling.value
        if c.role is ColumnRole.FREE_TEXT:
            key = f"q{position + 1}"
            column["question"] = key
            questions.append({"key": key, "text": c.header, "position": position})
            position += 1
        columns[c.header] = column
        if c.role is ColumnRole.UNKNOWN:
            review_reasons[c.header] = c.reason

    manifest_dict: dict[str, object] = {
        "version": 1,
        "consultation": consultation,
        "title": consultation,
        "source": source_format.value,
        "encoding": sample.encoding,
        "sheet": None,
        "columns": columns,
        "questions": questions,
        "source_sha256": sample.source_sha256,
    }
    return manifest_dict, review_reasons


def _render_yaml_block(value: object) -> str:
    return yaml.safe_dump(value, default_flow_style=False, sort_keys=False, allow_unicode=True)


def render_draft(
    *,
    manifest_dict: dict[str, object],
    review_reasons: dict[str, str],
    source_path: Path,
) -> str:
    """Renders the draft manifest as YAML text, with a header comment and
    an inline `# REVIEW:` comment on every unknown column.

    Built by hand rather than through a single yaml.safe_dump call
    because PyYAML's safe dumper has no way to attach a comment to a
    line - the top-level keys, each column block and the questions list
    are rendered separately so a comment can be spliced onto the one
    line that needs it.
    """
    columns = manifest_dict["columns"]
    assert isinstance(columns, dict)
    questions = manifest_dict["questions"]
    assert isinstance(questions, list)

    top_level = {k: v for k, v in manifest_dict.items() if k not in ("columns", "questions")}

    lines: list[str] = [
        f"# DRAFT column manifest for {source_path.name} - proposed by `cip inspect`.",
        "#",
        "# This is a draft, not a decision. Every column below marked",
        "# `role: unknown` MUST be reviewed and resolved by a human before",
        "# this file is usable - ingestion refuses to run while any column",
        "# is unknown. Once every column is correct, commit this file to git.",
        "#",
        "# `questions:` below is pre-filled with each free-text column's own",
        "# header as placeholder text. The real question wording usually",
        "# differs from the column header - replace it before committing.",
        "",
        _render_yaml_block(top_level).rstrip("\n"),
        "columns:",
    ]

    for header, column in columns.items():
        block = _render_yaml_block({header: column}).rstrip("\n")
        block_lines = ["  " + line for line in block.split("\n")]
        if header in review_reasons:
            for i, line in enumerate(block_lines):
                if line.strip() == "role: unknown":
                    block_lines[i] = f"{line}  # REVIEW: {review_reasons[header]}"
        lines.extend(block_lines)

    lines.append("questions:")
    if questions:
        block = _render_yaml_block(questions).rstrip("\n")
        lines.extend("  " + line if line else line for line in block.split("\n"))
    else:
        lines.append("  []")

    return "\n".join(lines) + "\n"


def draft_path_for(source_path: Path) -> Path:
    return source_path.with_name(source_path.name + ".manifest.draft.yaml")


# --- terminal summary -----------------------------------------------------------


def _display_sample(c: ColumnClassification) -> str:
    if c.sample_value is None:
        return ""
    if c.sensitive:
        return _MASKED_DISPLAY
    return c.sample_value[:_SAMPLE_DISPLAY_WIDTH]


def print_summary(
    classifications: Sequence[ColumnClassification], *, file: TextIO | None = None
) -> None:
    out = file if file is not None else sys.stdout
    header_row = f"{'Column':<42} {'Role':<16} {'Confidence':<11} Sample"
    print(header_row, file=out)
    print("-" * len(header_row), file=out)
    for c in classifications:
        name = c.header if len(c.header) <= 42 else c.header[:39] + "..."
        print(
            f"{name:<42} {c.role.value:<16} {c.confidence:<11.2f} {_display_sample(c)}",
            file=out,
        )

    unknown = [c for c in classifications if c.role is ColumnRole.UNKNOWN]
    print(file=out)
    print(f"{len(unknown)} column(s) marked unknown.", file=out)
    if unknown:
        print(
            "This draft is NOT usable until every unknown column has been reviewed and resolved.",
            file=out,
        )
    else:
        print(
            "No column was left unknown, but nothing here is confident enough to "
            "accept unread - check every role and reason before committing.",
            file=out,
        )


def run_inspect(source_path: Path, *, consultation: str) -> Path:
    """Reads the export, classifies every column, writes the draft
    manifest and prints the terminal summary. Returns the draft path.
    """
    sample = read_sample(source_path)
    classifications = classify_export(sample)
    manifest_dict, review_reasons = build_draft_manifest(
        consultation=consultation,
        source_format=SourceFormat.CSV,
        sample=sample,
        classifications=classifications,
    )

    draft_text = render_draft(
        manifest_dict=manifest_dict, review_reasons=review_reasons, source_path=source_path
    )
    out_path = draft_path_for(source_path)
    out_path.write_text(draft_text, encoding="utf-8")

    print(f"Detected encoding: {sample.encoding}")
    print(f"Sampled {len(sample.rows)} of {sample.total_rows} row(s).")
    print()
    print_summary(classifications)
    print()
    print(f"Draft manifest written to {out_path}")

    return out_path


# --- validation, used later by ingest -----------------------------------------


@dataclass(frozen=True, slots=True)
class Problem:
    kind: str
    message: str


def validate_manifest_against_source(manifest: Manifest, source_path: Path) -> list[Problem]:
    """Preconditions ingestion must check before it runs.

    Manifest's own validators check internal consistency - does every
    free-text column name a real question, and so on - without knowing
    the source file exists. This checks the manifest against that file,
    plus the one thing Manifest is deliberately permissive about: a
    column can be role=unknown and still be a structurally valid
    Manifest, because a draft in progress is not an error. It becomes
    one the moment something tries to ingest with it.

    An undeclared column is always an error here, never a default:
    silently including it risks putting identity data into analysis,
    and silently excluding it risks dropping a question nobody notices
    is missing.
    """
    problems: list[Problem] = []
    raw = source_path.read_bytes()

    header: tuple[str, ...] | None
    try:
        with source_path.open("r", newline="", encoding=manifest.encoding) as f:
            header = tuple(next(csv.reader(f), []))
    except (LookupError, UnicodeDecodeError) as exc:
        problems.append(
            Problem(
                kind="encoding",
                message=(
                    f"declared encoding {manifest.encoding!r} does not decode "
                    f"{source_path.name}: {exc}"
                ),
            )
        )
        header = None

    if header is not None:
        header_set = set(header)
        declared = set(manifest.columns)

        for column_name in sorted(header_set - declared):
            problems.append(
                Problem(
                    kind="undeclared_column",
                    message=(
                        f"column {column_name!r} is present in {source_path.name} but not "
                        "declared in the manifest"
                    ),
                )
            )

        for column_name in sorted(declared - header_set):
            problems.append(
                Problem(
                    kind="missing_column",
                    message=(
                        f"column {column_name!r} is declared in the manifest but not present "
                        f"in {source_path.name}"
                    ),
                )
            )

    for column_name, column_spec in manifest.columns.items():
        if column_spec.role is ColumnRole.UNKNOWN:
            problems.append(
                Problem(
                    kind="unresolved_unknown",
                    message=f"column {column_name!r} is still role=unknown and must be resolved",
                )
            )

    if manifest.source_sha256 is not None:
        actual = source_sha256(raw)
        if actual != manifest.source_sha256:
            problems.append(
                Problem(
                    kind="changed_source",
                    message=(
                        f"{source_path.name} has changed since this manifest was written "
                        f"(expected sha256 {manifest.source_sha256}, got {actual})"
                    ),
                )
            )

    return problems


def load_manifest(path: Path) -> Manifest:
    return Manifest.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] != "inspect":
        print("usage: cip inspect <source.csv> --consultation <id>", file=sys.stderr)
        return 2

    parser = argparse.ArgumentParser(prog="cip inspect")
    parser.add_argument("source", type=Path)
    parser.add_argument("--consultation", required=True)
    parsed = parser.parse_args(args[1:])

    run_inspect(parsed.source, consultation=parsed.consultation)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
