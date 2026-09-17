"""The domain model: stable ids, manifest validation, and two
architectural guards that must fail loudly if someone adds a field.
"""

from __future__ import annotations

import pytest
from cip.core.models import (
    Attachment,
    ColumnRole,
    ColumnSpec,
    IdentityHandling,
    Manifest,
    QuestionSpec,
    Respondent,
    RespondentType,
    SourceFormat,
    attachment_id,
    content_hash,
    question_id,
    response_id,
    submission_id,
)
from pydantic import ValidationError

# --- ids ---------------------------------------------------------------


def test_submission_id_is_stable_for_identical_input():
    a = submission_id("consult-1", "sha-abc", "row-1")
    b = submission_id("consult-1", "sha-abc", "row-1")
    assert a == b


def test_submission_id_differs_when_any_input_differs():
    base = submission_id("consult-1", "sha-abc", "row-1")
    assert submission_id("consult-2", "sha-abc", "row-1") != base
    assert submission_id("consult-1", "sha-xyz", "row-1") != base
    assert submission_id("consult-1", "sha-abc", "row-2") != base


def test_response_id_is_stable_and_differs():
    a = response_id("submission-1", "Q3")
    assert a == response_id("submission-1", "Q3")
    assert response_id("submission-1", "Q4") != a
    assert response_id("submission-2", "Q3") != a


def test_question_id_is_stable_and_differs():
    a = question_id("consult-1", "q3")
    assert a == question_id("consult-1", "q3")
    assert question_id("consult-1", "q4") != a
    assert question_id("consult-2", "q3") != a


def test_attachment_id_is_stable_and_differs():
    a = attachment_id("submission-1", "evidence.pdf", "sha-content")
    assert a == attachment_id("submission-1", "evidence.pdf", "sha-content")
    assert attachment_id("submission-1", "other.pdf", "sha-content") != a
    assert attachment_id("submission-1", "evidence.pdf", "sha-different") != a


def test_ids_are_namespaced_and_cannot_collide_across_types():
    sub = submission_id("x", "y", "z")
    resp = response_id("x", "y")
    assert sub != resp
    assert sub.startswith("submission_")
    assert resp.startswith("response_")


# --- content_hash --------------------------------------------------------


def test_content_hash_treats_whitespace_and_case_as_identical():
    a = content_hash("Hello   World")
    b = content_hash("hello world")
    c = content_hash("  hello\nworld  ")
    assert a == b == c


def test_content_hash_differs_for_different_content():
    assert content_hash("hello world") != content_hash("goodbye world")


# --- frozen models --------------------------------------------------------


def test_frozen_model_raises_on_mutation():
    respondent = Respondent(type=RespondentType.INDIVIDUAL)
    with pytest.raises(ValidationError):
        respondent.type = RespondentType.ORGANISATION


# --- architectural guards --------------------------------------------------


def test_respondent_has_no_field_capable_of_holding_a_name_email_or_full_postcode():
    """Not a behaviour test: an assertion over the field set itself, so it
    fails loudly the moment someone adds a name/email/postcode field back.
    """
    fields = set(Respondent.model_fields)
    assert fields == {"type", "organisation", "contact_hash", "postcode_area"}
    forbidden = {"name", "email", "email_address", "postcode", "full_postcode", "address"}
    assert fields.isdisjoint(forbidden)


def test_attachment_has_no_field_capable_of_holding_extracted_text():
    fields = set(Attachment.model_fields)
    assert fields == {
        "id",
        "submission_id",
        "filename",
        "media_type",
        "size_bytes",
        "content_sha256",
        "stored_uri",
        "provenance",
    }
    forbidden = {"text", "extracted_text", "content", "embedding", "chunks", "chunk_text"}
    assert fields.isdisjoint(forbidden)


# --- manifest validation ---------------------------------------------------


def _manifest(columns: dict[str, ColumnSpec], questions: tuple[QuestionSpec, ...]) -> Manifest:
    return Manifest(
        version=1,
        consultation="consult-1",
        title="Test consultation",
        source=SourceFormat.CSV,
        encoding="utf-8",
        sheet=None,
        columns=columns,
        questions=questions,
    )


def test_identity_column_without_handling_is_rejected():
    with pytest.raises(ValidationError, match="handling"):
        _manifest(columns={"email": ColumnSpec(role=ColumnRole.IDENTITY)}, questions=())


def test_identity_column_with_handling_is_accepted():
    manifest = _manifest(
        columns={"email": ColumnSpec(role=ColumnRole.IDENTITY, handling=IdentityHandling.HASH)},
        questions=(),
    )
    assert manifest.columns["email"].handling is IdentityHandling.HASH


def test_free_text_column_without_question_is_rejected():
    with pytest.raises(ValidationError, match="names no question"):
        _manifest(
            columns={"q1": ColumnSpec(role=ColumnRole.FREE_TEXT)},
            questions=(QuestionSpec(key="q1", text="What do you think?", position=0),),
        )


def test_free_text_column_with_question_is_accepted():
    manifest = _manifest(
        columns={"q1": ColumnSpec(role=ColumnRole.FREE_TEXT, question="q1")},
        questions=(QuestionSpec(key="q1", text="What do you think?", position=0),),
    )
    assert manifest.free_text_questions == {"q1": "q1"}


def test_handling_on_a_non_identity_column_is_rejected():
    with pytest.raises(ValidationError, match="is not role=identity"):
        _manifest(
            columns={
                "q1": ColumnSpec(
                    role=ColumnRole.FREE_TEXT, question="q1", handling=IdentityHandling.DROP
                )
            },
            questions=(QuestionSpec(key="q1", text="?", position=0),),
        )


def test_handling_on_an_identity_column_is_accepted():
    manifest = _manifest(
        columns={"email": ColumnSpec(role=ColumnRole.IDENTITY, handling=IdentityHandling.DROP)},
        questions=(),
    )
    assert manifest.columns["email"].handling is IdentityHandling.DROP


def test_column_referencing_an_unknown_question_is_rejected():
    with pytest.raises(ValidationError, match="not declared"):
        _manifest(
            columns={"q1": ColumnSpec(role=ColumnRole.FREE_TEXT, question="ghost")},
            questions=(),
        )


def test_column_referencing_a_declared_question_is_accepted():
    manifest = _manifest(
        columns={"q1": ColumnSpec(role=ColumnRole.FREE_TEXT, question="q1")},
        questions=(QuestionSpec(key="q1", text="?", position=0),),
    )
    assert manifest.questions[0].key == "q1"


def test_question_referenced_by_zero_columns_is_rejected():
    with pytest.raises(ValidationError, match="referenced by 0 columns"):
        _manifest(columns={}, questions=(QuestionSpec(key="q1", text="?", position=0),))


def test_question_referenced_by_exactly_one_column_is_accepted():
    manifest = _manifest(
        columns={"q1": ColumnSpec(role=ColumnRole.FREE_TEXT, question="q1")},
        questions=(QuestionSpec(key="q1", text="?", position=0),),
    )
    assert len(manifest.questions) == 1


def test_question_referenced_by_more_than_one_column_is_rejected():
    with pytest.raises(ValidationError, match="referenced by 2 columns"):
        _manifest(
            columns={
                "q1a": ColumnSpec(role=ColumnRole.FREE_TEXT, question="q1"),
                "q1b": ColumnSpec(role=ColumnRole.FREE_TEXT, question="q1"),
            },
            questions=(QuestionSpec(key="q1", text="?", position=0),),
        )
