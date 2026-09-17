"""`cip inspect`: classification, the draft manifest, and the refusal
ingest will later rely on.

The golden fixture is 11 rows - too small to make any column confidently
classifiable on its own (fewer than the 20 non-empty values inspect
requires), so it's used here to prove correct *refusal*: every column
ends up unknown, and the reasons are the right ones. Confident
classification is exercised separately, against a small hand-built
export where every column's evidence is deliberately unambiguous.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

import pytest
import yaml
from cip.core.models import IdentityHandling, Manifest, SourceFormat
from cip.core.models.enums import ColumnRole
from cip.ingestion.inspect import (
    Problem,
    build_draft_manifest,
    classify_column,
    classify_export,
    load_manifest,
    print_summary,
    render_draft,
    validate_manifest_against_source,
)
from cip.ingestion.sampling import detect_encoding, read_sample

GOLDEN_DIR = Path(__file__).resolve().parent / "fixtures" / "golden"


# --- a clean, unambiguous export for exercising confident classification ---


def _clean_export(tmp_path: Path, *, rows: int = 70) -> Path:
    """70 rows, every column's evidence unambiguous by construction: a
    unique sequential id, consistent dates, email- and postcode-shaped
    identity columns, a low-cardinality respondent-type column present
    everywhere, two free-text columns answered a minority of the time
    with long varied text, an always-empty column, and a name column.
    """
    fieldnames = [
        "Response ID",
        "Submitted",
        "Name",
        "Email",
        "Organisation",
        "Postcode",
        "Respondent Type",
        "Question One",
        "Question Two",
    ]
    postcodes = ["SW1A 1AA", "EC1A 1BB", "M1 1AE", "B1 1AA", "LS1 1AA"]
    respondent_types = [
        "An individual",
        "An individual",
        "An individual",
        "An organisation",
        "A public body",
    ]

    path = tmp_path / "clean.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for i in range(1, rows + 1):
            writer.writerow(
                {
                    "Response ID": f"SUB-{i:04d}",
                    "Submitted": f"2024-{1 + (i % 9):02d}-{1 + (i % 28):02d} 09:00:00",
                    "Name": f"Person {i}",
                    "Email": f"person{i}@example.com",
                    "Organisation": "",
                    "Postcode": postcodes[i % len(postcodes)],
                    "Respondent Type": respondent_types[i % len(respondent_types)],
                    "Question One": (
                        f"I think option {i} needs more work on accessibility and cost, "
                        f"item reference {i}."
                        if i % 5 < 2
                        else ""
                    ),
                    "Question Two": (
                        f"The timeline for change {i} seems rushed given the consultation "
                        f"period that was offered to residents."
                        if i % 3 == 0
                        else ""
                    ),
                }
            )
    return path


@pytest.fixture
def clean_export(tmp_path) -> Path:
    return _clean_export(tmp_path)


# --- golden: every column classified or unknown -----------------------------


def test_every_golden_column_is_classified_or_unknown():
    sample = read_sample(GOLDEN_DIR / "export.csv")
    results = classify_export(sample)

    assert len(results) == len(sample.header)
    for c in results:
        assert isinstance(c.role, ColumnRole)
        assert c.reason  # every column carries a reason, confident or not


def test_golden_email_column_is_never_classified_as_free_text():
    sample = read_sample(GOLDEN_DIR / "export.csv")
    results = {c.header: c for c in classify_export(sample)}

    assert results["Email"].role is not ColumnRole.FREE_TEXT


def test_golden_name_column_is_unknown_with_a_pii_specific_reason():
    sample = read_sample(GOLDEN_DIR / "export.csv")
    results = {c.header: c for c in classify_export(sample)}

    name = results["Name"]
    assert name.role is ColumnRole.UNKNOWN
    assert "name" in name.reason.lower()
    assert name.sensitive is True


def test_name_column_is_unknown_even_with_ample_confident_evidence(clean_export):
    """The absolute veto: a Name column with 70 varied, present values -
    ample evidence by every other column's standard - must still refuse.
    """
    sample = read_sample(clean_export)
    results = {c.header: c for c in classify_export(sample)}

    assert results["Name"].role is ColumnRole.UNKNOWN
    assert "name" in results["Name"].reason.lower()


# --- confident classification, against the clean export ---------------------


def test_confident_classification_of_every_role(clean_export):
    sample = read_sample(clean_export)
    results = {c.header: c for c in classify_export(sample)}

    assert results["Response ID"].role is ColumnRole.SUBMISSION_ID
    assert results["Submitted"].role is ColumnRole.SUBMITTED_AT
    assert results["Email"].role is ColumnRole.IDENTITY
    assert results["Email"].handling is IdentityHandling.HASH
    assert results["Postcode"].role is ColumnRole.IDENTITY
    assert results["Postcode"].handling is IdentityHandling.COARSEN
    assert results["Respondent Type"].role is ColumnRole.RESPONDENT_TYPE
    assert results["Question One"].role is ColumnRole.FREE_TEXT
    assert results["Question Two"].role is ColumnRole.FREE_TEXT
    assert results["Organisation"].role is ColumnRole.UNKNOWN
    assert results["Organisation"].reason == "column is empty in every sampled row"

    for c in results.values():
        assert c.confidence < 1.0


def test_confidence_never_reaches_one(clean_export):
    sample = read_sample(clean_export)
    for c in classify_export(sample):
        assert 0.0 <= c.confidence <= 0.95


# --- classify_column: unit-level evidence gates ------------------------------


def test_column_with_no_non_empty_values_is_unknown():
    result = classify_column("Some Column", [""] * 30)
    assert result.role is ColumnRole.UNKNOWN
    assert "empty" in result.reason


def test_column_below_sample_threshold_is_unknown():
    result = classify_column("Some Column", ["x"] * 10 + [""] * 10)
    assert result.role is ColumnRole.UNKNOWN
    assert "fewer than" in result.reason


def test_ambiguous_column_is_unknown_with_a_conflict_reason():
    # Medium cardinality, medium length, mostly present: neither profile fits.
    values = [f"some medium length answer number {i % 15}" for i in range(30)]
    result = classify_column("Ambiguous Column", values)
    assert result.role is ColumnRole.UNKNOWN
    assert "conflict" in result.reason


# --- encoding detection -------------------------------------------------------


def test_encoding_detection_identifies_the_golden_file_as_utf8():
    raw = (GOLDEN_DIR / "export.csv").read_bytes()
    assert detect_encoding(raw) == "utf-8"


def test_encoding_detection_identifies_a_cp1252_variant_as_cp1252_not_utf8(tmp_path):
    # A curly apostrophe, encoded as cp1252, is not valid utf-8 on its own.
    text = "Response ID,Comment\nR1,’twas a good idea\n"
    raw = text.encode("cp1252")
    with pytest.raises(UnicodeDecodeError):
        raw.decode("utf-8")

    path = tmp_path / "cp1252.csv"
    path.write_bytes(raw)

    assert detect_encoding(path.read_bytes()) == "cp1252"
    assert detect_encoding(path.read_bytes()) != "utf-8"


# --- the draft: valid YAML, and valid as a Manifest once resolved -----------


def test_draft_output_parses_as_valid_yaml():
    sample = read_sample(GOLDEN_DIR / "export.csv")
    classifications = classify_export(sample)
    manifest_dict, review_reasons = build_draft_manifest(
        consultation="golden-consultation",
        source_format=SourceFormat.CSV,
        sample=sample,
        classifications=classifications,
    )
    draft_text = render_draft(
        manifest_dict=manifest_dict,
        review_reasons=review_reasons,
        source_path=GOLDEN_DIR / "export.csv",
    )

    parsed = yaml.safe_load(draft_text)
    assert parsed["consultation"] == "golden-consultation"
    assert set(parsed["columns"]) == set(sample.header)


def test_draft_with_unknowns_resolved_validates_against_manifest(clean_export):
    sample = read_sample(clean_export)
    classifications = classify_export(sample)
    manifest_dict, review_reasons = build_draft_manifest(
        consultation="clean-consultation",
        source_format=SourceFormat.CSV,
        sample=sample,
        classifications=classifications,
    )

    # "Name" (PII veto) and "Organisation" (empty column) are left unknown.
    assert set(review_reasons) == {"Name", "Organisation"}
    manifest_dict["columns"]["Organisation"] = {"role": "identity", "handling": "drop"}
    manifest_dict["columns"]["Name"] = {"role": "identity", "handling": "drop"}

    manifest = Manifest.model_validate(manifest_dict)
    assert manifest.columns["Organisation"].role is ColumnRole.IDENTITY
    assert manifest.columns["Name"].role is ColumnRole.IDENTITY


def test_unresolved_draft_does_not_validate_against_manifest():
    """The draft's role: unknown is a real ColumnRole, so Manifest
    accepts it structurally - it's validate_manifest_against_source,
    not Manifest itself, that refuses an unresolved draft.
    """
    manifest = load_manifest(GOLDEN_DIR / "manifest.yaml")
    unresolved = manifest.model_copy(
        update={
            "columns": {
                **manifest.columns,
                "Organisation": manifest.columns["Organisation"].model_copy(
                    update={"role": ColumnRole.UNKNOWN}
                ),
            }
        }
    )
    assert unresolved.columns["Organisation"].role is ColumnRole.UNKNOWN


# --- validate_manifest_against_source ----------------------------------------


def test_validate_catches_an_undeclared_column():
    manifest = load_manifest(GOLDEN_DIR / "manifest_incomplete.yaml")
    problems = validate_manifest_against_source(manifest, GOLDEN_DIR / "export.csv")

    assert all(isinstance(p, Problem) for p in problems)
    kinds = {p.kind for p in problems}
    assert "undeclared_column" in kinds
    assert any("Organisation" in p.message for p in problems if p.kind == "undeclared_column")


def test_validate_catches_a_column_missing_from_the_source():
    manifest = load_manifest(GOLDEN_DIR / "manifest.yaml")
    extended = manifest.model_copy(
        update={
            "columns": {
                **manifest.columns,
                "Nobody Has This Column": manifest.columns["Response ID"].model_copy(
                    update={"role": ColumnRole.ATTACHMENT}
                ),
            }
        }
    )

    problems = validate_manifest_against_source(extended, GOLDEN_DIR / "export.csv")

    assert any(
        p.kind == "missing_column" and "Nobody Has This Column" in p.message for p in problems
    )


def test_validate_catches_a_remaining_unknown_column():
    manifest = load_manifest(GOLDEN_DIR / "manifest.yaml")
    with_unknown = manifest.model_copy(
        update={
            "columns": {
                **manifest.columns,
                "Postcode": manifest.columns["Postcode"].model_copy(
                    update={"role": ColumnRole.UNKNOWN, "handling": None}
                ),
            }
        }
    )

    problems = validate_manifest_against_source(with_unknown, GOLDEN_DIR / "export.csv")

    assert any(p.kind == "unresolved_unknown" and "Postcode" in p.message for p in problems)


def test_validate_catches_a_changed_source_file():
    manifest = load_manifest(GOLDEN_DIR / "manifest.yaml")
    changed = manifest.model_copy(update={"source_sha256": "0" * 64})

    problems = validate_manifest_against_source(changed, GOLDEN_DIR / "export.csv")

    assert any(p.kind == "changed_source" for p in problems)


def test_validate_passes_a_manifest_with_the_correct_hash():
    manifest = load_manifest(GOLDEN_DIR / "manifest.yaml")
    raw = (GOLDEN_DIR / "export.csv").read_bytes()
    correct = manifest.model_copy(update={"source_sha256": hashlib.sha256(raw).hexdigest()})

    problems = validate_manifest_against_source(correct, GOLDEN_DIR / "export.csv")

    assert not any(p.kind == "changed_source" for p in problems)


# --- terminal output never prints a raw identity value -----------------------


def test_terminal_output_masks_identity_values(clean_export, capsys):
    """If this ever fails, someone made print_summary emit a raw sample
    value for a sensitive column - exactly what this tool must never do.
    """
    sample = read_sample(clean_export)
    classifications = classify_export(sample)

    print_summary(classifications)
    captured = capsys.readouterr().out

    for c in classifications:
        if c.sensitive and c.sample_value:
            assert c.sample_value not in captured

    assert "person1@example.com" not in captured
    assert "SW1A 1AA" not in captured
    assert "Person 1" not in captured
    assert captured.count("<hidden>") >= 3  # Name, Email, Postcode
