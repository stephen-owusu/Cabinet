"""The tabular parser: identity handling, quarantine, idempotency at the
unit level, and the CSV/XLSX content-addressing cross-check.

Golden proves the pipeline end to end (see test_fixtures.py); this file
is narrower and adversarial - it builds small, deliberately awkward
exports (a malformed row, a NUL byte, a date Excel invented) to prove
each failure mode quarantines instead of crashing the run.
"""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

import openpyxl
import pytest
from cip.core.config import settings
from cip.core.models import Manifest, Response, Submission, ValidatedManifest
from cip.ingestion.inspect import validate_manifest_against_source
from cip.ingestion.parsers.tabular import (
    QuarantineReason,
    QuarantineRecord,
    _coarsen_postcode,
    _salted_hash,
    parse_export,
    quarantine_path_for,
    write_quarantine_log,
)

HEADER = [
    "Response ID",
    "Submitted",
    "Name",
    "Email",
    "Organisation",
    "Postcode",
    "Respondent Type",
    "Attachment",
    "Comments",
]

LONG_ANSWER = ("Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 400)[:20000]


def _rows() -> list[dict[str, str]]:
    return [
        {
            "Response ID": "R1",
            "Submitted": "2024-01-01 09:00:00",
            "Name": "Alice Example",
            "Email": "alice@example.com",
            "Organisation": "Acme Ltd",
            "Postcode": "SW1A 1AA",
            "Respondent Type": "An individual",
            "Attachment": "",
            "Comments": "We need better lighting, more parking, and safer crossings.",
        },
        {
            "Response ID": "R2",
            "Submitted": "2024-01-02 09:00:00",
            "Name": "Bob Example",
            "Email": "bob@example.com",
            "Organisation": "",
            "Postcode": "EC1A 1BB",
            "Respondent Type": "An individual",
            "Attachment": "supporting-evidence.pdf",
            "Comments": "Line one of my comment.\nLine two of my comment.",
        },
        {
            "Response ID": "R3",
            "Submitted": "2024-01-03 09:00:00",
            "Name": "Carol Example",
            "Email": "carol@example.com",
            "Organisation": "",
            "Postcode": "M1 1AE",
            "Respondent Type": "An individual",
            "Attachment": "",
            "Comments": 'She said "this is unacceptable" during the meeting.',
        },
        {
            "Response ID": "R4",
            "Submitted": "2024-01-04 09:00:00",
            "Name": "Dave Example",
            "Email": "dave@example.com",
            "Organisation": "",
            "Postcode": "B1 1AA",
            "Respondent Type": "An individual",
            "Attachment": "",
            "Comments": LONG_ANSWER,
        },
        {
            "Response ID": "R5",
            "Submitted": "2024-01-05 09:00:00",
            "Name": "José Müller",
            "Email": "jose@example.com",
            "Organisation": "",
            "Postcode": "LS1 1AA",
            "Respondent Type": "An individual",
            "Attachment": "",
            "Comments": "I think it’s “great” — really! \U0001f44d",
        },
    ]


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HEADER, quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        f.write("\n")  # a trailing blank row, as Excel appends


def _write_xlsx(path: Path, rows: list[dict[str, str]]) -> None:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(HEADER)
    for row in rows:
        sheet.append([row.get(h, "") for h in HEADER])
    workbook.save(path)


def _manifest_dict(*, source: str, sheet: str | None, source_sha256: str) -> dict[str, object]:
    return {
        "version": 1,
        "consultation": "parser-test",
        "title": "Parser test",
        "source": source,
        "encoding": "utf-8",
        "sheet": sheet,
        "columns": {
            "Response ID": {"role": "submission_id"},
            "Submitted": {"role": "submitted_at"},
            "Name": {"role": "identity", "handling": "drop"},
            "Email": {"role": "identity", "handling": "hash"},
            "Organisation": {"role": "identity", "handling": "keep"},
            "Postcode": {"role": "identity", "handling": "coarsen"},
            "Respondent Type": {"role": "respondent_type"},
            "Attachment": {"role": "attachment"},
            "Comments": {"role": "free_text", "question": "q1"},
        },
        "questions": [{"key": "q1", "text": "Comments", "position": 0}],
        "source_sha256": source_sha256,
    }


def _validated(manifest_dict: dict[str, object], source_path: Path) -> ValidatedManifest:
    manifest = Manifest.model_validate(manifest_dict)
    result = validate_manifest_against_source(manifest, source_path)
    assert isinstance(result, ValidatedManifest), result
    return result


@pytest.fixture
def csv_export(tmp_path) -> tuple[Path, ValidatedManifest]:
    source = tmp_path / "export.csv"
    _write_csv(source, _rows())
    import hashlib

    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = _validated(_manifest_dict(source="csv", sheet=None, source_sha256=sha), source)
    return source, manifest


def _by_type(items):
    submissions, responses, quarantines = [], [], []
    for item in items:
        if isinstance(item, Submission):
            submissions.append(item)
        elif isinstance(item, Response):
            responses.append(item)
        elif isinstance(item, QuarantineRecord):
            quarantines.append(item)
    return submissions, responses, quarantines


# --- CSV edge cases: encoding and quoting round-trip correctly ----------------


def test_comma_inside_quoted_cell_round_trips(csv_export):
    source, manifest = csv_export
    _, responses, _ = _by_type(parse_export(manifest, source))
    texts = [r.text for r in responses]
    assert any("lighting, more parking, and safer crossings" in t for t in texts)


def test_newline_inside_quoted_cell_round_trips(csv_export):
    source, manifest = csv_export
    _, responses, _ = _by_type(parse_export(manifest, source))
    assert any("\n" in r.text for r in responses)


def test_escaped_double_quote_round_trips(csv_export):
    source, manifest = csv_export
    _, responses, _ = _by_type(parse_export(manifest, source))
    assert any('"this is unacceptable"' in r.text for r in responses)


def test_twenty_thousand_character_answer_round_trips(csv_export):
    source, manifest = csv_export
    _, responses, _ = _by_type(parse_export(manifest, source))
    assert any(len(r.text) >= 20000 for r in responses)


def test_non_ascii_text_round_trips(csv_export):
    source, manifest = csv_export
    _, responses, _ = _by_type(parse_export(manifest, source))
    texts = [r.text for r in responses]
    assert any("’" in t for t in texts)  # curly apostrophe
    assert any("“" in t and "”" in t for t in texts)  # curly quotes
    assert any("—" in t for t in texts)  # em dash
    assert any("\U0001f44d" in t for t in texts)  # emoji


def test_trailing_blank_row_yields_nothing(csv_export):
    source, manifest = csv_export
    submissions, _, quarantines = _by_type(parse_export(manifest, source))
    assert len(submissions) == 5  # exactly the 5 real rows, not 6
    assert quarantines == []


# --- content addressing: CSV and XLSX agree ----------------------------------


def test_csv_and_xlsx_produce_identical_ids(tmp_path):
    rows = _rows()
    csv_path = tmp_path / "export.csv"
    xlsx_path = tmp_path / "export.xlsx"
    _write_csv(csv_path, rows)
    _write_xlsx(xlsx_path, rows)

    import hashlib

    csv_manifest = _validated(
        _manifest_dict(
            source="csv", sheet=None, source_sha256=hashlib.sha256(csv_path.read_bytes()).hexdigest()
        ),
        csv_path,
    )
    xlsx_manifest = _validated(
        _manifest_dict(
            source="xlsx",
            sheet="Sheet",
            source_sha256=hashlib.sha256(xlsx_path.read_bytes()).hexdigest(),
        ),
        xlsx_path,
    )

    # Different consultation ids would make different submission ids by
    # design (see cip.core.models.ids) - use the same one so this test
    # isolates the thing it's actually checking: format independence.
    csv_manifest = csv_manifest.model_copy(update={"consultation": "same-consultation"})
    xlsx_manifest = xlsx_manifest.model_copy(update={"consultation": "same-consultation"})

    csv_submissions, csv_responses, _ = _by_type(parse_export(csv_manifest, csv_path))
    xlsx_submissions, xlsx_responses, _ = _by_type(parse_export(xlsx_manifest, xlsx_path))

    csv_sub_ids = {s.id for s in csv_submissions}
    xlsx_sub_ids = {s.id for s in xlsx_submissions}
    assert csv_sub_ids == xlsx_sub_ids
    assert len(csv_sub_ids) == 5

    csv_resp_ids = {r.id for r in csv_responses}
    xlsx_resp_ids = {r.id for r in xlsx_responses}
    assert csv_resp_ids == xlsx_resp_ids


def test_xlsx_postcode_converted_to_a_date_does_not_crash(tmp_path):
    """A well-known Excel trap: a cell Excel decided looked like a date
    becomes a real datetime value in the file, regardless of what was
    typed. The original text is already gone by the time this file is
    opened - the parser's job is only to not crash on the type it gets.
    """
    rows = _rows()
    path = tmp_path / "export.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(HEADER)
    postcode_col = HEADER.index("Postcode") + 1
    for row in rows:
        sheet.append([row.get(h, "") for h in HEADER])
    # Corrupt the first data row's postcode cell the way Excel would.
    sheet.cell(row=2, column=postcode_col, value=date(2023, 1, 4))
    workbook.save(path)

    import hashlib

    manifest = _validated(
        _manifest_dict(
            source="xlsx", sheet="Sheet", source_sha256=hashlib.sha256(path.read_bytes()).hexdigest()
        ),
        path,
    )

    submissions, _, quarantines = _by_type(parse_export(manifest, path))

    assert quarantines == []
    assert len(submissions) == 5
    first = next(s for s in submissions if s.id)
    assert isinstance(first.respondent.postcode_area, str)
    assert first.respondent.postcode_area != ""


# --- identity handling: drop, keep, hash, coarsen -----------------------------


def test_coarsen_reduces_to_the_outward_code_only():
    assert _coarsen_postcode("SW1A 1AA") == "SW1A"
    assert _coarsen_postcode("M1 1AE") == "M1"
    assert _coarsen_postcode("EC1A1BB") == "EC1A"  # no space typed


def test_hash_is_salted_not_the_raw_value():
    hashed = _salted_hash("alice@example.com", "some-salt")
    assert hashed != "alice@example.com"
    assert len(hashed) == 64  # sha256 hex digest


def test_hash_changes_if_the_salt_changes():
    a = _salted_hash("alice@example.com", "salt-one")
    b = _salted_hash("alice@example.com", "salt-two")
    assert a != b


def test_salt_comes_from_config_not_a_literal_in_this_module():
    import cip.ingestion.parsers.tabular as tabular_module

    source = Path(tabular_module.__file__).read_text(encoding="utf-8")
    assert "settings.identity_salt" in source


def test_keep_passes_through_the_organisation_value(csv_export):
    source, manifest = csv_export
    submissions, _, _ = _by_type(parse_export(manifest, source))
    with_org = [s for s in submissions if s.respondent.organisation]
    assert any(s.respondent.organisation == "Acme Ltd" for s in with_org)


def test_drop_and_hash_never_leave_the_raw_value_on_the_respondent(csv_export):
    """Names never have a field to land in at all (see
    cip.core.models.submission); this specifically checks the hash path
    never regresses to storing the plaintext email either.
    """
    source, manifest = csv_export
    submissions, _, _ = _by_type(parse_export(manifest, source))
    raw_emails = {row["Email"] for row in _rows()}
    raw_names = {row["Name"] for row in _rows()}

    for s in submissions:
        assert s.respondent.contact_hash not in raw_emails
        assert s.respondent.contact_hash is None or s.respondent.contact_hash not in raw_names
        assert not hasattr(s.respondent, "name")
        assert not hasattr(s.respondent, "email")


# --- attachments: recognised, never opened -------------------------------------


def test_attachment_reference_is_never_opened_or_turned_into_a_response(csv_export):
    source, manifest = csv_export
    # R2's Attachment cell names a file that does not exist on disk -
    # if the parser ever tried to open it, this would raise.
    _, responses, _ = _by_type(parse_export(manifest, source))
    assert not any(r.text == "supporting-evidence.pdf" for r in responses)


# --- row-level quarantine -------------------------------------------------------


def test_row_length_mismatch_quarantines_only_that_row(tmp_path):
    source = tmp_path / "export.csv"
    rows = _rows()
    _write_csv(source, rows)
    # Splice in a malformed line (too few fields) between two good rows.
    lines = source.read_text(encoding="utf-8").splitlines()
    lines.insert(3, "R-BAD,2024-01-09 09:00:00")  # far fewer than len(HEADER) fields
    source.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="")

    import hashlib

    manifest = _validated(
        _manifest_dict(source="csv", sheet=None, source_sha256=hashlib.sha256(source.read_bytes()).hexdigest()),
        source,
    )

    submissions, _, quarantines = _by_type(parse_export(manifest, source))

    mismatches = [q for q in quarantines if q.reason is QuarantineReason.ROW_LENGTH_MISMATCH]
    assert len(mismatches) == 1
    assert len(submissions) == 5  # the five well-formed rows still processed


def test_encoding_error_quarantines_only_that_row_not_the_rest(tmp_path):
    source = tmp_path / "export.csv"
    rows = _rows()
    _write_csv(source, rows)
    lines = source.read_text(encoding="utf-8").splitlines()
    # A NUL byte inside a field: csv raises for this one physical line only.
    lines.insert(3, "R-NUL,2024-01-09 09:00:00,,,,,,,\x00bad")
    source.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="")

    import hashlib

    manifest = _validated(
        _manifest_dict(source="csv", sheet=None, source_sha256=hashlib.sha256(source.read_bytes()).hexdigest()),
        source,
    )

    submissions, _, quarantines = _by_type(parse_export(manifest, source))

    encoding_errors = [q for q in quarantines if q.reason is QuarantineReason.ENCODING_ERROR]
    assert len(encoding_errors) == 1
    assert len(submissions) == 5  # every good row still processed despite the bad one


def test_unparseable_date_quarantines(tmp_path):
    source = tmp_path / "export.csv"
    rows = _rows()
    rows[0] = {**rows[0], "Submitted": "not-a-date"}
    _write_csv(source, rows)

    import hashlib

    manifest = _validated(
        _manifest_dict(source="csv", sheet=None, source_sha256=hashlib.sha256(source.read_bytes()).hexdigest()),
        source,
    )

    submissions, _, quarantines = _by_type(parse_export(manifest, source))

    assert any(q.reason is QuarantineReason.UNPARSEABLE_DATE and q.row == 1 for q in quarantines)
    assert len(submissions) == 4


def test_missing_and_duplicate_submission_id_quarantine(tmp_path):
    source = tmp_path / "export.csv"
    rows = _rows()
    rows[0] = {**rows[0], "Response ID": ""}
    rows[1] = {**rows[1], "Response ID": rows[2]["Response ID"]}  # duplicates R3's id
    _write_csv(source, rows)

    import hashlib

    manifest = _validated(
        _manifest_dict(source="csv", sheet=None, source_sha256=hashlib.sha256(source.read_bytes()).hexdigest()),
        source,
    )

    submissions, _, quarantines = _by_type(parse_export(manifest, source))

    reasons = {(q.row, q.reason) for q in quarantines}
    assert (1, QuarantineReason.MISSING_SUBMISSION_ID) in reasons
    assert (2, QuarantineReason.DUPLICATE_SUBMISSION_ID) in reasons
    assert len(submissions) == 3


# --- idempotency at the unit level ---------------------------------------------


def test_row_key_is_the_submission_id_column_not_the_row_index(tmp_path):
    """Reordering the rows must not change any id - if the row key were
    the row's position, this would fail.
    """
    rows = _rows()
    forward = tmp_path / "forward.csv"
    reversed_path = tmp_path / "reversed.csv"
    _write_csv(forward, rows)
    _write_csv(reversed_path, list(reversed(rows)))

    import hashlib

    forward_manifest = _validated(
        _manifest_dict(
            source="csv", sheet=None, source_sha256=hashlib.sha256(forward.read_bytes()).hexdigest()
        ),
        forward,
    )
    reversed_manifest = _validated(
        _manifest_dict(
            source="csv",
            sheet=None,
            source_sha256=hashlib.sha256(reversed_path.read_bytes()).hexdigest(),
        ),
        reversed_path,
    )
    forward_manifest = forward_manifest.model_copy(update={"consultation": "same"})
    reversed_manifest = reversed_manifest.model_copy(update={"consultation": "same"})

    forward_ids = {s.id for s in _by_type(parse_export(forward_manifest, forward))[0]}
    reversed_ids = {s.id for s in _by_type(parse_export(reversed_manifest, reversed_path))[0]}

    assert forward_ids == reversed_ids


# --- quarantine log -------------------------------------------------------------


def test_quarantine_path_for_appends_a_suffix_to_the_full_source_name():
    assert quarantine_path_for(Path("exports/housing.csv")) == Path(
        "exports/housing.csv.quarantine.jsonl"
    )


def test_write_quarantine_log_writes_one_json_line_per_record(tmp_path):
    from datetime import UTC, datetime

    records = [
        QuarantineRecord(
            row=7,
            reason=QuarantineReason.MISSING_SUBMISSION_ID,
            raw_row={"Response ID": ""},
            quarantined_at=datetime(2024, 1, 1, tzinfo=UTC),
        ),
        QuarantineRecord(
            row=9,
            reason=QuarantineReason.DUPLICATE_SUBMISSION_ID,
            raw_row={"Response ID": "R1"},
            quarantined_at=datetime(2024, 1, 1, tzinfo=UTC),
        ),
    ]
    path = tmp_path / "export.csv.quarantine.jsonl"
    write_quarantine_log(records, path)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["row"] == 7
    assert first["reason"] == "missing_submission_id"
    assert first["raw_row"] == {"Response ID": ""}
    assert "quarantined_at" in first
