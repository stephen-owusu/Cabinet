"""Manifest: how to read one consultation's export, decided by a human.

A manifest is declared once per consultation, reviewed by a person, and
committed to git - it is never inferred from the data at run time. The
cost of guessing wrong is not cosmetic: misreading an identity column as
free text means publishing someone's email address in a thematic
summary. Every rule below exists to make that specific mistake
impossible to represent, not just unlikely.
"""

from __future__ import annotations

from collections import Counter

from cip.core.models.enums import ColumnRole, IdentityHandling, SourceFormat
from pydantic import BaseModel, ConfigDict, Field, model_validator


class QuestionSpec(BaseModel):
    """A question as declared in the manifest, before parsing.

    Lighter than consultation.Question on purpose: no id, because ids are
    always derived, never hand-authored in a manifest, and no
    source_column, because that would duplicate the column that already
    names this question's key in Manifest.columns.
    """

    model_config = ConfigDict(frozen=True)

    key: str
    text: str
    position: int


class ColumnSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: ColumnRole
    handling: IdentityHandling | None = None
    question: str | None = None


class Manifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: int
    consultation: str
    title: str
    source: SourceFormat
    encoding: str
    sheet: str | None = None
    columns: dict[str, ColumnSpec]
    questions: tuple[QuestionSpec, ...]
    source_sha256: str | None = Field(
        default=None,
        description=(
            "The source file's sha256 when this manifest was written or last "
            "confirmed against it. None for a manifest with no file behind it "
            "yet. Ingestion refuses to run if the file's current hash does "
            "not match - the manifest was written for a different file, "
            "deliberately or not, and that difference is exactly the kind of "
            "thing a human needs to see before analysis runs on it."
        ),
    )

    @model_validator(mode="after")
    def _identity_columns_declare_handling(self) -> Manifest:
        for name, column in self.columns.items():
            if column.role is ColumnRole.IDENTITY and column.handling is None:
                raise ValueError(f"column {name!r} is role=identity but declares no handling rule")
        return self

    @model_validator(mode="after")
    def _handling_only_on_identity_columns(self) -> Manifest:
        for name, column in self.columns.items():
            if column.role is not ColumnRole.IDENTITY and column.handling is not None:
                raise ValueError(
                    f"column {name!r} declares handling={column.handling!r} "
                    "but is not role=identity"
                )
        return self

    @model_validator(mode="after")
    def _free_text_columns_name_a_question(self) -> Manifest:
        for name, column in self.columns.items():
            if column.role is ColumnRole.FREE_TEXT and column.question is None:
                raise ValueError(f"column {name!r} is role=free_text but names no question")
        return self

    @model_validator(mode="after")
    def _referenced_questions_exist(self) -> Manifest:
        known = {question.key for question in self.questions}
        for name, column in self.columns.items():
            if column.question is not None and column.question not in known:
                raise ValueError(
                    f"column {name!r} names question {column.question!r}, "
                    "which is not declared in questions"
                )
        return self

    @model_validator(mode="after")
    def _every_question_referenced_exactly_once(self) -> Manifest:
        references = Counter(
            column.question for column in self.columns.values() if column.question is not None
        )
        for question in self.questions:
            count = references[question.key]
            if count != 1:
                raise ValueError(
                    f"question {question.key!r} is referenced by {count} columns, "
                    "expected exactly 1"
                )
        return self

    @property
    def free_text_questions(self) -> dict[str, str]:
        """Column name to question key, for the columns worth extracting
        as responses. Used by the parser, not this package, to decide
        which cells become Response records.
        """
        return {
            name: column.question
            for name, column in self.columns.items()
            if column.role is ColumnRole.FREE_TEXT and column.question is not None
        }


_VALIDATION_PROOF = object()
"""Module-private sentinel. Not exported - the only code that can supply
it is validate_manifest_against_source, by design."""


class ValidatedManifest(Manifest):
    """A manifest proven ready for ingestion.

    Manifest validates structurally even when a column is still
    ColumnRole.UNKNOWN, by design: a draft has to be loadable and
    inspectable before a human has finished reviewing it. That leaves a
    gap between "this parses as a Manifest" and "this is safe to ingest
    with" - and today that gap is closed only by every caller remembering
    to run validate_manifest_against_source first. One of them will
    forget, and the failure mode is silent: identity data flowing into
    analysis because nothing stopped it.

    ValidatedManifest closes the gap in the type system instead of in
    someone's memory. The only way to obtain one is
    validate_manifest_against_source(manifest, source_path), which
    returns either a ValidatedManifest or a list[Problem], never both.
    Constructing one any other way raises: a ValidatedManifest that
    nothing has actually checked is a lie, and a lie that type-checks as
    proof is worse than an unchecked Manifest, because it stops being
    questioned. The parser's signature - parse_export(manifest:
    ValidatedManifest, ...) - then makes passing a plain, unchecked
    Manifest a type error, not a runtime hope.

    Guarantees carried, all checked once by validate_manifest_against_source
    and never re-checked here - a ValidatedManifest is a completed proof,
    not a promise to verify itself again:
      - no column is ColumnRole.UNKNOWN
      - every column in the source file's header is declared in `columns`,
        and every column declared in `columns` is present in the header
      - `encoding` actually decodes the source file
      - `source_sha256` is set and matches the source file's current sha256
    """

    model_config = ConfigDict(frozen=True)

    @model_validator(mode="before")
    @classmethod
    def _require_validation_proof(cls, data: object) -> object:
        if not isinstance(data, dict) or data.get("_proof") is not _VALIDATION_PROOF:
            raise ValueError(
                "ValidatedManifest cannot be constructed directly. Obtain one from "
                "validate_manifest_against_source(manifest, source_path) - the only "
                "place that has actually checked the guarantees this type carries."
            )
        return {k: v for k, v in data.items() if k != "_proof"}

    @classmethod
    def _construct(cls, manifest: Manifest) -> ValidatedManifest:
        """The sanctioned construction path, used exclusively by
        validate_manifest_against_source after every guarantee above has
        been checked against `manifest` and its source file.
        """
        return cls.model_validate({**manifest.model_dump(), "_proof": _VALIDATION_PROOF})
