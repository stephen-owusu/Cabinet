"""Domain model: the shape of a consultation, from export to response.

Public re-exports only. Import from cip.core.models, not from the
submodules directly, so this list is the complete inventory of what the
rest of the system is allowed to depend on.
"""

from __future__ import annotations

from cip.core.models.attachment import Attachment
from cip.core.models.consultation import Consultation, Question
from cip.core.models.enums import (
    ColumnRole,
    IdentityHandling,
    QuestionMapping,
    RespondentType,
    ResponseStatus,
    SourceFormat,
    TextQuality,
)
from cip.core.models.ids import (
    attachment_id,
    content_hash,
    question_id,
    response_id,
    submission_id,
)
from cip.core.models.manifest import ColumnSpec, Manifest, QuestionSpec, ValidatedManifest
from cip.core.models.provenance import CellLocator, Locator, Provenance, SpanLocator
from cip.core.models.response import Response
from cip.core.models.submission import Respondent, Submission

__all__ = [
    "Attachment",
    "CellLocator",
    "ColumnRole",
    "ColumnSpec",
    "Consultation",
    "IdentityHandling",
    "Locator",
    "Manifest",
    "Provenance",
    "Question",
    "QuestionMapping",
    "QuestionSpec",
    "Respondent",
    "RespondentType",
    "Response",
    "ResponseStatus",
    "SourceFormat",
    "SpanLocator",
    "Submission",
    "TextQuality",
    "ValidatedManifest",
    "attachment_id",
    "content_hash",
    "question_id",
    "response_id",
    "submission_id",
]
