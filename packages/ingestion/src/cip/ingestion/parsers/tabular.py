"""Turns a validated CSV or XLSX export into Submission, Response and
quarantine records.

An iterator, never a list: a 5,000-row export across a dozen questions is
up to 60,000 objects, and holding all of them in memory before anything
downstream has started is exactly the failure streaming exists to avoid.
xlsx is read with openpyxl's read_only=True for the same reason - it
never materialises the whole workbook in memory.

Ids are content-addressed (see cip.core.models.ids): the same file parsed
twice, or the same content saved once as CSV and once as XLSX, produces
the same submission and response ids. That only holds because the row
key is the submission id column's own value, never the row's position -
a reordered file would otherwise mint an entirely new id for every row.

Identity handling - drop, keep, hash, coarsen - is applied here and
nowhere else. A Respondent can be constructed with a name, an email
address or a full postcode only if this code puts one there; the model
itself has no field that could hold it (see cip.core.models.submission),
so the guarantee lives in what this module refuses to pass through, not
in a check afterwards.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from enum import StrEnum
from pathlib import Path

import openpyxl
from cip.core.config import settings
from cip.core.models import (
    CellLocator,
    ColumnRole,
    IdentityHandling,
    Provenance,
    QuestionMapping,
    Respondent,
    RespondentType,
    Response,
    ResponseStatus,
    SourceFormat,
    Submission,
    TextQuality,
    ValidatedManifest,
    content_hash,
    question_id,
    response_id,
    submission_id,
)

# --- quarantine ---------------------------------------------------------------


class QuarantineReason(StrEnum):
    """Why a row did not become a submission.

    Recorded, not merely logged: "the department sent 4,912 rows and we
    ingested 4,847" is not an answer anyone can act on. "Rows 112, 340
    and 4,821-4,863 were quarantined as duplicate_submission_id" is.
    """

    MISSING_SUBMISSION_ID = "missing_submission_id"
    DUPLICATE_SUBMISSION_ID = "duplicate_submission_id"
    ENCODING_ERROR = "encoding_error"
    UNPARSEABLE_DATE = "unparseable_date"
    ROW_LENGTH_MISMATCH = "row_length_mismatch"


@dataclass(frozen=True, slots=True)
class QuarantineRecord:
    """A row that did not become a submission, kept rather than
    discarded so a human can go and look at exactly what was wrong.
    """

    row: int
    reason: QuarantineReason
    raw_row: dict[str, str]
    quarantined_at: datetime


def _now() -> datetime:
    return datetime.now(UTC)


def quarantine_path_for(source: Path) -> Path:
    return source.with_name(source.name + ".quarantine.jsonl")


def write_quarantine_log(records: Iterable[QuarantineRecord], path: Path) -> None:
    """Appends each record as one JSON line at the quarantine location,
    so "where are the other 65 rows" has an answer that does not require
    re-running ingestion with a debugger attached.
    """
    with path.open("a", encoding="utf-8") as f:
        for record in records:
            f.write(
                json.dumps(
                    {
                        "row": record.row,
                        "reason": record.reason.value,
                        "raw_row": record.raw_row,
                        "quarantined_at": record.quarantined_at.isoformat(),
                    }
                )
                + "\n"
            )


# --- identity handling ---------------------------------------------------------


def _salted_hash(value: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}\x1f{value}".encode()).hexdigest()


def _coarsen_postcode(value: str) -> str:
    """The outward code only - everything except the fixed 3-character
    inward code (a digit then two letters), which is precise enough to
    narrow a respondent to a street or a handful of buildings and so is
    never retained.
    """
    compact = value.strip().upper().replace(" ", "")
    return compact[:-3] if len(compact) > 3 else compact


_RESPONDENT_TYPE_KEYWORDS: tuple[tuple[str, RespondentType], ...] = (
    ("organisation", RespondentType.ORGANISATION),
    ("organization", RespondentType.ORGANISATION),
    ("public body", RespondentType.PUBLIC_BODY),
    ("individual", RespondentType.INDIVIDUAL),
    ("anonymous", RespondentType.ANONYMOUS),
)


def _parse_respondent_type(value: str) -> RespondentType:
    lowered = value.lower()
    for keyword, respondent_type in _RESPONDENT_TYPE_KEYWORDS:
        if keyword in lowered:
            return respondent_type
    return RespondentType.UNKNOWN


def _build_respondent(row: dict[str, str], manifest: ValidatedManifest, *, salt: str) -> Respondent:
    respondent_type = RespondentType.UNKNOWN
    organisation: str | None = None
    contact_hash: str | None = None
    postcode_area: str | None = None

    for column_name, spec in manifest.columns.items():
        value = row.get(column_name, "").strip()
        if spec.role is ColumnRole.RESPONDENT_TYPE:
            if value:
                respondent_type = _parse_respondent_type(value)
        elif spec.role is ColumnRole.IDENTITY and value:
            if spec.handling is IdentityHandling.DROP:
                continue
            elif spec.handling is IdentityHandling.KEEP:
                organisation = value
            elif spec.handling is IdentityHandling.HASH:
                contact_hash = _salted_hash(value, salt)
            elif spec.handling is IdentityHandling.COARSEN:
                postcode_area = _coarsen_postcode(value)

    return Respondent(
        type=respondent_type,
        organisation=organisation,
        contact_hash=contact_hash,
        postcode_area=postcode_area,
    )


# --- dates -----------------------------------------------------------------------

_DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
    "%Y-%m-%dT%H:%M:%S",
)


def _parse_submitted_at(value: str) -> datetime | None:
    if value == "":
        return None
    for fmt in _DATETIME_FORMATS:
        try:
            return datetime.strptime(value, fmt)  # noqa: DTZ007 - source has no tz, naive is correct
        except ValueError:
            continue
    return None


def _cell_to_str(value: object) -> str:
    """Openpyxl hands back typed cell values, not strings - a cell Excel
    auto-detected as a date becomes a real datetime object even when
    what was typed looks nothing like one, a well-known trap for
    postcodes and reference numbers that happen to parse as a date.
    Stringifying here means whatever the cell actually contains flows
    through as text, the same shape the CSV path already produces,
    instead of crashing on a type nothing downstream expects. It cannot
    recover text Excel has already discarded - that loss happened before
    this file was ever opened.
    """
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


# --- manifest lookups -----------------------------------------------------------


def _unique_column_for_role(manifest: ValidatedManifest, role: ColumnRole) -> str:
    matches = [name for name, spec in manifest.columns.items() if spec.role is role]
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one column with role={role.value!r}, found {len(matches)}: {matches}"
        )
    return matches[0]


# --- row iteration, per format ----------------------------------------------------


def _iter_csv_rows(
    source: Path, encoding: str
) -> Iterator[tuple[int, dict[str, str] | QuarantineRecord]]:
    """Yields (row_number, row-or-quarantine-record) for every non-blank
    data row. Row-length mismatches are caught here, against the raw
    field list, because csv.DictReader pads or silently drops mismatched
    rows rather than reporting them.
    """
    row_number = 0
    with source.open("r", newline="", encoding=encoding) as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if header is None:
            return

        while True:
            try:
                raw_row = next(reader)
            except StopIteration:
                return
            except csv.Error as exc:
                row_number += 1
                yield (
                    row_number,
                    QuarantineRecord(
                        row=row_number,
                        reason=QuarantineReason.ENCODING_ERROR,
                        raw_row={"_error": str(exc)},
                        quarantined_at=_now(),
                    ),
                )
                continue

            if not raw_row:
                continue  # a genuinely blank line, e.g. Excel's trailing row
            row_number += 1
            if len(raw_row) != len(header):
                yield (
                    row_number,
                    QuarantineRecord(
                        row=row_number,
                        reason=QuarantineReason.ROW_LENGTH_MISMATCH,
                        raw_row={f"column_{i}": v for i, v in enumerate(raw_row)},
                        quarantined_at=_now(),
                    ),
                )
                continue
            yield row_number, dict(zip(header, raw_row, strict=True))


def _iter_xlsx_rows(
    source: Path, manifest: ValidatedManifest
) -> Iterator[tuple[int, dict[str, str], str]]:
    """Yields (row_number, row, sheet_name) for every non-blank data row."""
    workbook = openpyxl.load_workbook(source, read_only=True, data_only=True)
    try:
        sheet = workbook[manifest.sheet] if manifest.sheet else workbook.worksheets[0]
        rows = sheet.iter_rows(values_only=True)
        header_row = next(rows, None)
        if header_row is None:
            return
        header = tuple("" if v is None else str(v) for v in header_row)

        row_number = 0
        for raw_row in rows:
            if raw_row is None or all(v is None for v in raw_row):
                continue
            row_number += 1
            values = tuple(_cell_to_str(v) for v in raw_row)
            if len(values) < len(header):
                values = values + ("",) * (len(header) - len(values))
            yield row_number, dict(zip(header, values[: len(header)], strict=True)), sheet.title
    finally:
        workbook.close()


# --- per-row processing, shared by both formats ------------------------------------


def _process_row(
    row_number: int,
    row: dict[str, str],
    *,
    manifest: ValidatedManifest,
    submission_id_column: str,
    submitted_at_column: str,
    consultation_id: str,
    source_sha256: str,
    seen_submission_ids: set[str],
    source_uri: str,
    sheet_label: str,
    salt: str,
) -> Iterator[Submission | Response | QuarantineRecord]:
    raw_id = row.get(submission_id_column, "").strip()
    if not raw_id:
        yield QuarantineRecord(
            row=row_number,
            reason=QuarantineReason.MISSING_SUBMISSION_ID,
            raw_row=row,
            quarantined_at=_now(),
        )
        return

    if raw_id in seen_submission_ids:
        yield QuarantineRecord(
            row=row_number,
            reason=QuarantineReason.DUPLICATE_SUBMISSION_ID,
            raw_row=row,
            quarantined_at=_now(),
        )
        return

    submitted_at = _parse_submitted_at(row.get(submitted_at_column, "").strip())
    if submitted_at is None:
        yield QuarantineRecord(
            row=row_number,
            reason=QuarantineReason.UNPARSEABLE_DATE,
            raw_row=row,
            quarantined_at=_now(),
        )
        return

    # Only a row that will actually become a submission claims its id -
    # a quarantined duplicate must not block a later, otherwise-valid row.
    seen_submission_ids.add(raw_id)

    sub_id = submission_id(consultation_id, raw_id)
    respondent = _build_respondent(row, manifest, salt=salt)

    yield Submission(
        id=sub_id,
        consultation_id=consultation_id,
        respondent=respondent,
        submitted_at=submitted_at,
        provenance=Provenance(
            source_uri=source_uri,
            source_sha256=source_sha256,
            source_format=manifest.source,
            locator=CellLocator(sheet=sheet_label, row=row_number, column=submission_id_column),
            manifest_version=manifest.version,
        ),
    )

    for column_name, question_key in manifest.free_text_questions.items():
        text = row.get(column_name, "").strip()
        if text == "":
            continue  # empty and whitespace-only cells yield nothing at all

        yield Response(
            id=response_id(sub_id, column_name),
            submission_id=sub_id,
            consultation_id=consultation_id,
            question_id=question_id(consultation_id, question_key),
            mapping=QuestionMapping.EXPLICIT,
            text=text,
            text_quality=TextQuality.NATIVE,
            content_hash=content_hash(text),
            provenance=Provenance(
                source_uri=source_uri,
                source_sha256=source_sha256,
                source_format=manifest.source,
                locator=CellLocator(sheet=sheet_label, row=row_number, column=column_name),
                manifest_version=manifest.version,
            ),
            status=ResponseStatus.INGESTED,
        )


# --- entry point ------------------------------------------------------------------


def parse_export(
    manifest: ValidatedManifest, source: Path
) -> Iterator[Submission | Response | QuarantineRecord]:
    """Turns one validated export into Submission, Response and
    QuarantineRecord objects, streamed one row at a time.

    Attachment-role columns are recognised and skipped: their reference
    is not opened, and nothing is built from them. Recording an
    Attachment record requires a content hash and a storage location -
    both mean opening the file, which this parser is explicitly not for.
    That is the attachment work the limits in inspect.py already exist
    for, not this one.
    """
    assert manifest.source_sha256 is not None  # guaranteed by ValidatedManifest

    submission_id_column = _unique_column_for_role(manifest, ColumnRole.SUBMISSION_ID)
    submitted_at_column = _unique_column_for_role(manifest, ColumnRole.SUBMITTED_AT)
    consultation_id = manifest.consultation
    source_sha256 = manifest.source_sha256
    salt = settings.identity_salt
    source_uri = source.resolve().as_uri()
    seen_submission_ids: set[str] = set()

    if manifest.source is SourceFormat.CSV:
        for row_number, row in _iter_csv_rows(source, manifest.encoding):
            if isinstance(row, QuarantineRecord):
                yield row
                continue
            yield from _process_row(
                row_number,
                row,
                manifest=manifest,
                submission_id_column=submission_id_column,
                submitted_at_column=submitted_at_column,
                consultation_id=consultation_id,
                source_sha256=source_sha256,
                seen_submission_ids=seen_submission_ids,
                source_uri=source_uri,
                sheet_label=source.name,
                salt=salt,
            )
    else:
        for row_number, row, sheet_label in _iter_xlsx_rows(source, manifest):
            yield from _process_row(
                row_number,
                row,
                manifest=manifest,
                submission_id_column=submission_id_column,
                submitted_at_column=submitted_at_column,
                consultation_id=consultation_id,
                source_sha256=source_sha256,
                seen_submission_ids=seen_submission_ids,
                source_uri=source_uri,
                sheet_label=sheet_label,
                salt=salt,
            )
