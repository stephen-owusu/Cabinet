"""The fixtures themselves: the golden file, and the seeded generator.

A fixture with wrong ground truth produces confidently wrong pipeline
tests later, so everything here checks the fixtures against an
independent recomputation, not against generate.py's own bookkeeping.
"""

from __future__ import annotations

import csv
import hashlib
import json
import tracemalloc
from pathlib import Path

import pytest
import yaml
from cip.core.models import Manifest, Response, Submission, ValidatedManifest
from cip.ingestion.inspect import validate_manifest_against_source
from cip.ingestion.parsers.tabular import QuarantineRecord, parse_export
from fixtures.generate import generate_export

GOLDEN_DIR = Path(__file__).resolve().parent / "fixtures" / "golden"


def _load_manifest(path: Path) -> Manifest:
    return Manifest.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def _derive_ground_truth(csv_path: Path, manifest: Manifest) -> dict:
    """Recomputes submissions/responses/empty_cells/quarantine straight
    from the CSV and manifest, applying the same rules a future parser
    must: blank or whitespace-only free-text cells yield no response, a
    blank Response ID quarantines a row, and a Response ID already seen
    quarantines every row after the first that uses it.
    """
    free_text_columns = manifest.free_text_questions
    with csv_path.open("r", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    seen_ids: set[str] = set()
    submissions = 0
    responses = 0
    empty = 0
    quarantine: list[dict[str, object]] = []

    for i, row in enumerate(rows, start=1):
        response_id_value = (row.get("Response ID") or "").strip()
        if response_id_value == "":
            quarantine.append({"row": i, "reason": "missing_submission_id"})
            continue
        if response_id_value in seen_ids:
            quarantine.append({"row": i, "reason": "duplicate_submission_id"})
            continue
        seen_ids.add(response_id_value)

        submissions += 1
        for column in free_text_columns:
            if (row.get(column) or "").strip() == "":
                empty += 1
            else:
                responses += 1

    return {
        "submissions_expected": submissions,
        "responses_expected": responses,
        "empty_cells": empty,
        "quarantine_expected": quarantine,
    }


@pytest.fixture(scope="module")
def golden_manifest() -> Manifest:
    return _load_manifest(GOLDEN_DIR / "manifest.yaml")


@pytest.fixture(scope="module")
def golden_header() -> list[str]:
    with (GOLDEN_DIR / "export.csv").open("r", newline="", encoding="utf-8") as f:
        return next(csv.reader(f))


@pytest.fixture(scope="module")
def golden_rows() -> list[dict[str, str]]:
    with (GOLDEN_DIR / "export.csv").open("r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@pytest.fixture(scope="module")
def golden_expected() -> dict:
    return json.loads((GOLDEN_DIR / "expected.json").read_text(encoding="utf-8"))


# --- generator: determinism ------------------------------------------------


def test_generator_is_deterministic_for_the_same_seed(tmp_path):
    gt_a = generate_export(rows=40, seed=99, out_dir=tmp_path / "a")
    gt_b = generate_export(rows=40, seed=99, out_dir=tmp_path / "b")

    assert (tmp_path / "a" / "export.csv").read_bytes() == (
        tmp_path / "b" / "export.csv"
    ).read_bytes()
    assert gt_a == gt_b


def test_different_seeds_produce_different_output(tmp_path):
    generate_export(rows=40, seed=1, out_dir=tmp_path / "a")
    generate_export(rows=40, seed=2, out_dir=tmp_path / "b")

    csv_a = (tmp_path / "a" / "export.csv").read_bytes()
    csv_b = (tmp_path / "b" / "export.csv").read_bytes()
    assert csv_a != csv_b


def test_generated_expected_json_is_internally_consistent(tmp_path):
    """Same check as the golden fixture below, but for a generated one -
    the generator's own bookkeeping is not exempt from being wrong.
    """
    out_dir = tmp_path / "generated"
    ground_truth = generate_export(rows=250, seed=2024, out_dir=out_dir)

    manifest = _load_manifest(out_dir / "manifest.yaml")
    derived = _derive_ground_truth(out_dir / "export.csv", manifest)

    assert derived["submissions_expected"] == ground_truth.submissions_expected
    assert derived["responses_expected"] == ground_truth.responses_expected
    assert derived["empty_cells"] == ground_truth.empty_cells
    assert derived["quarantine_expected"] == [
        q.model_dump() for q in ground_truth.quarantine_expected
    ]

    on_disk = json.loads((out_dir / "expected.json").read_text(encoding="utf-8"))
    assert on_disk == ground_truth.model_dump(mode="json")


# --- golden: internal consistency -------------------------------------------


def test_golden_expected_json_is_internally_consistent(golden_manifest, golden_expected):
    derived = _derive_ground_truth(GOLDEN_DIR / "export.csv", golden_manifest)

    assert derived["submissions_expected"] == golden_expected["submissions_expected"]
    assert derived["responses_expected"] == golden_expected["responses_expected"]
    assert derived["empty_cells"] == golden_expected["empty_cells"]
    assert derived["quarantine_expected"] == golden_expected["quarantine_expected"]


# --- golden: manifest validation --------------------------------------------


def test_golden_manifest_validates_against_the_manifest_model(golden_manifest):
    assert golden_manifest.consultation == "golden-consultation"
    assert golden_manifest.free_text_questions == {
        "What do you think of the proposal overall?": "q1",
        "Do you have any comments on the proposed timeline?": "q2",
        "Is there anything else you would like to add?": "q3",
    }


def test_complete_manifest_declares_every_csv_column(golden_manifest, golden_header):
    assert set(golden_manifest.columns) == set(golden_header)


def test_incomplete_manifest_is_missing_exactly_one_declared_column(golden_header):
    """The agreed rule: an undeclared column is an ingestion error, never
    a silent include or exclude. This manifest is still a structurally
    valid Manifest on its own - the missing column only matters once
    it's checked against export.csv, which is the future parser's job.
    """
    manifest = _load_manifest(GOLDEN_DIR / "manifest_incomplete.yaml")
    missing = set(golden_header) - set(manifest.columns)
    assert missing == {"Organisation"}


# --- golden: every edge case is present, by inspection ----------------------


def test_edge_case_comma_inside_quoted_cell(golden_rows):
    assert any("," in row["What do you think of the proposal overall?"] for row in golden_rows)


def test_edge_case_newline_inside_quoted_cell(golden_rows):
    assert any(
        "\n" in row["Do you have any comments on the proposed timeline?"] for row in golden_rows
    )


def test_edge_case_escaped_double_quote_inside_quoted_cell(golden_rows):
    assert any('"' in row["Is there anything else you would like to add?"] for row in golden_rows)


def test_edge_case_empty_cell_yields_no_response(golden_rows):
    row = next(r for r in golden_rows if r["Response ID"] == "RESP-0005")
    assert row["Do you have any comments on the proposed timeline?"] == ""
    assert row["Is there anything else you would like to add?"] == ""


def test_edge_case_whitespace_only_cell_is_treated_as_empty(golden_rows):
    row = next(r for r in golden_rows if r["Response ID"] == "RESP-0006")
    cell = row["What do you think of the proposal overall?"]
    assert cell != ""
    assert cell.strip() == ""


def test_edge_case_missing_response_id_row_is_present(golden_rows):
    candidates = [r for r in golden_rows if r["Response ID"].strip() == ""]
    assert len(candidates) == 1
    assert candidates[0]["Name"] != ""  # a deliberate row, not a stray blank line


def test_edge_case_duplicate_response_id_row_is_present(golden_rows):
    ids = [r["Response ID"] for r in golden_rows if r["Response ID"].strip() != ""]
    duplicated = {i for i in set(ids) if ids.count(i) > 1}
    assert duplicated == {"RESP-0008"}
    assert ids.count("RESP-0008") == 2


def test_edge_case_non_ascii_text_is_present(golden_rows):
    row = next(r for r in golden_rows if r["Response ID"] == "RESP-0010")
    assert "é" in row["Name"] or "ü" in row["Name"]  # accented name
    answer = row["What do you think of the proposal overall?"]
    assert "’" in answer  # curly apostrophe
    assert "“" in answer and "”" in answer  # curly quotes
    assert "—" in answer  # em dash
    assert "\U0001f44d" in answer  # emoji


def test_edge_case_very_long_answer_is_present(golden_rows):
    lengths = [len(value) for row in golden_rows for value in row.values()]
    assert max(lengths) >= 20000


def test_edge_case_trailing_blank_row_is_present():
    """Excel appends a genuinely empty final line, not a row of empty
    fields - csv.reader must see it as [], and DictReader (used by every
    other test here) must skip it rather than yield a phantom row.
    """
    with (GOLDEN_DIR / "export.csv").open("r", newline="", encoding="utf-8") as f:
        raw_rows = list(csv.reader(f))
    assert raw_rows[-1] == []


def test_edge_case_normal_unremarkable_row_is_present(golden_rows):
    row = next(r for r in golden_rows if r["Response ID"] == "RESP-0001")
    free_text = (
        row["What do you think of the proposal overall?"],
        row["Do you have any comments on the proposed timeline?"],
        row["Is there anything else you would like to add?"],
    )
    assert all(cell.strip() != "" for cell in free_text)


# --- pipeline: the parser, exercised end to end -----------------------------


def _validated_golden_manifest() -> ValidatedManifest:
    manifest = _load_manifest(GOLDEN_DIR / "manifest.yaml")
    raw = (GOLDEN_DIR / "export.csv").read_bytes()
    manifest = manifest.model_copy(update={"source_sha256": hashlib.sha256(raw).hexdigest()})
    result = validate_manifest_against_source(manifest, GOLDEN_DIR / "export.csv")
    assert isinstance(result, ValidatedManifest), result
    return result


def test_correctness_golden_file_produces_exact_submission_and_response_counts():
    validated = _validated_golden_manifest()
    expected = json.loads((GOLDEN_DIR / "expected.json").read_text(encoding="utf-8"))

    submissions = 0
    responses = 0
    for item in parse_export(validated, GOLDEN_DIR / "export.csv"):
        if isinstance(item, Submission):
            submissions += 1
        elif isinstance(item, Response):
            responses += 1

    assert submissions == expected["submissions_expected"]
    assert responses == expected["responses_expected"]


def test_idempotency_ingesting_twice_produces_identical_ids_and_no_duplication():
    """Ids are content-addressed, derived from the submission id column's
    own value rather than the row's position - this is where that
    actually has to hold, not just where it's declared.
    """
    validated = _validated_golden_manifest()

    def collect_ids() -> list[str]:
        return [
            item.id
            for item in parse_export(validated, GOLDEN_DIR / "export.csv")
            if isinstance(item, Submission | Response)
        ]

    first = collect_ids()
    second = collect_ids()

    assert first == second
    assert len(first) == len(set(first))  # no duplication within a single run either


def test_streaming_fifty_thousand_rows_keeps_peak_memory_flat(tmp_path):
    """A ceiling, not a ratio: comparing peak memory at 500 rows against
    peak memory at 50,000 rows would still pass if both were already
    buffering everything, just at two different, equally-wrong sizes.
    A fixed ceiling only passes if the implementation is actually
    streaming, on any machine this happens to run on.
    """
    out_dir = tmp_path / "streaming"
    generate_export(rows=50_000, seed=13, out_dir=out_dir)

    manifest = _load_manifest(out_dir / "manifest.yaml")
    validated = validate_manifest_against_source(manifest, out_dir / "export.csv")
    assert isinstance(validated, ValidatedManifest), validated

    tracemalloc.start()
    try:
        count = 0
        for _ in parse_export(validated, out_dir / "export.csv"):
            count += 1
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert count > 0

    ceiling = 30 * 1024 * 1024  # 30 MiB - an export this size fully materialised is far larger
    assert peak < ceiling, (
        f"peak traced memory was {peak / (1024 * 1024):.1f} MiB for {count} yielded "
        f"records, ceiling is {ceiling / (1024 * 1024):.0f} MiB - parse_export may "
        "have stopped streaming"
    )


def test_quarantine_every_bad_row_quarantined_every_good_row_processed():
    validated = _validated_golden_manifest()
    expected = json.loads((GOLDEN_DIR / "expected.json").read_text(encoding="utf-8"))

    quarantines = []
    submissions = 0
    for item in parse_export(validated, GOLDEN_DIR / "export.csv"):
        if isinstance(item, QuarantineRecord):
            quarantines.append({"row": item.row, "reason": item.reason.value})
        elif isinstance(item, Submission):
            submissions += 1

    assert quarantines == expected["quarantine_expected"]
    assert submissions == expected["submissions_expected"]
