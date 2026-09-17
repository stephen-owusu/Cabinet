"""Submission: identity, holds no analysable text.

One submission per export row. It carries who, or what organisation,
answered and when, and the provenance of the row itself - never the
answers. Free text lives only on Response, so nothing that identifies a
person sits next to the text a model or a person will read.
"""

from __future__ import annotations

from datetime import datetime

from cip.core.models.enums import RespondentType
from cip.core.models.provenance import Provenance
from pydantic import BaseModel, ConfigDict, Field


class Respondent(BaseModel):
    """Who answered, described without identifying them.

    Deliberately absent: name, email address, full postcode. The
    manifest's handling rules (IdentityHandling) drop, hash or coarsen
    those during ingestion, before a Respondent is ever constructed, so
    there is no field here for a parser to accidentally fill with a raw
    contact detail. contact_hash is a one-way digest, never the original
    value; postcode_area is a coarse area, such as an outward code, never
    a full postcode.
    """

    model_config = ConfigDict(frozen=True)

    type: RespondentType
    organisation: str | None = None
    contact_hash: str | None = None
    postcode_area: str | None = None


class Submission(BaseModel):
    """One export row. Holds identity; holds no analysable text."""

    model_config = ConfigDict(frozen=True)

    id: str
    consultation_id: str
    respondent: Respondent
    submitted_at: datetime
    provenance: Provenance
    campaign_id: str | None = Field(
        default=None,
        description=(
            "Assigned by the corpus-wide campaign-detection stage, never at "
            "ingestion - a single submission's campaign membership isn't "
            "knowable until the whole corpus has been seen."
        ),
    )
