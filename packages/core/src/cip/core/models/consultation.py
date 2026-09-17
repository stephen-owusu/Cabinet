"""Consultation: the container for a set of questions.

A consultation is the unit a manifest is declared against, and the unit
every id in this package is namespaced under, directly or through a
submission or response.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class Question(BaseModel):
    """One free-text question.

    There are no closed questions to model: the export channel asks only
    free text, so nothing here represents a radio button, a count, or a
    closed-question schema.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    key: str
    text: str
    position: int
    source_column: str


class Consultation(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    title: str
    questions: tuple[Question, ...]
