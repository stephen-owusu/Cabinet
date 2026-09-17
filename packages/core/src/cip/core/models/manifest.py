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
