"""Response: the unit of analysis.

One response per answered cell. Retrieval, clustering and summarisation
operate on responses, never on submissions or questions directly: a
submission may answer many questions, and a theme or a citation always
points at one response, not at the row it came from.
"""

from __future__ import annotations

from cip.core.models.enums import QuestionMapping, ResponseStatus, TextQuality
from cip.core.models.provenance import Provenance
from pydantic import BaseModel, ConfigDict, Field


class Response(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    submission_id: str
    consultation_id: str
    question_id: str
    mapping: QuestionMapping
    text: str
    text_quality: TextQuality
    content_hash: str
    provenance: Provenance
    status: ResponseStatus
    redacted: bool = False
    cluster_id: str | None = Field(
        default=None,
        description=(
            "Assigned by the corpus-wide clustering stage, never at ingestion "
            "- a single response has no cluster until the whole corpus is seen."
        ),
    )
    cluster_size: int | None = Field(
        default=None,
        description=(
            "Recomputed whenever the corpus changes. cluster_size is a "
            "property of the cluster, not of this response, so a stored "
            "value goes stale the moment another response joins or leaves "
            "the cluster."
        ),
    )
