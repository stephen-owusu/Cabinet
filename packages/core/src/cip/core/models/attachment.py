"""Attachment: supporting evidence, stored but not parsed.

An attachment backs up what a respondent typed; it is not itself a
response. It is never clustered, never counted toward theme weight, and
never summarised as though a respondent said it - only Response feeds
analysis. Parsing attachment content is a deliberately separate concern,
designed later, so this model carries no extracted text or embedding
fields.
"""

from __future__ import annotations

from cip.core.models.provenance import Provenance
from pydantic import BaseModel, ConfigDict


class Attachment(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    submission_id: str
    filename: str
    media_type: str
    size_bytes: int
    content_sha256: str
    stored_uri: str
    provenance: Provenance
