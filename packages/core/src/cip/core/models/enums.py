"""Enumerations serialised into stored records and manifests.

Every member here ends up as a string in a JSON manifest, a stored
Response, or a stored Submission. Renaming or removing a member changes
what a file written a year ago means, so treat these as the vocabulary of
the storage format itself, not as an internal implementation detail free
to rename on a whim.
"""

from __future__ import annotations

from enum import StrEnum


class SourceFormat(StrEnum):
    """The consultation webform export's file format.

    There is one intake channel - the webform export - so these are the
    only formats it can arrive in. Do not add a format belonging to a
    channel, such as email, that does not exist yet.
    """

    CSV = "csv"
    XLSX = "xlsx"


class ColumnRole(StrEnum):
    """What a single export column means, as declared in a manifest.

    UNKNOWN marks a column nobody has classified yet - a draft manifest
    tool's honest answer when the evidence isn't strong enough to guess.
    A manifest may hold it temporarily; it is a structurally valid
    column role, not an error. What treats it as an error is ingestion
    time: nothing may read a column for analysis while its role is still
    unknown, because guessing wrong here is exactly how identity data
    ends up where it shouldn't.
    """

    SUBMISSION_ID = "submission_id"
    SUBMITTED_AT = "submitted_at"
    RESPONDENT_TYPE = "respondent_type"
    IDENTITY = "identity"
    FREE_TEXT = "free_text"
    ATTACHMENT = "attachment"
    UNKNOWN = "unknown"


class IdentityHandling(StrEnum):
    """How an identity column is treated during ingestion, before a
    Respondent is ever constructed.

    DROP discards the column entirely. KEEP retains it as-is, for a
    column that is identifying but not personal, such as an organisation
    name given for publication. HASH produces Respondent.contact_hash: a
    one-way digest, never the original value. COARSEN produces
    Respondent.postcode_area: an area, never a full postcode. Every
    identity column must declare exactly one of these; there is no
    default, because a default would be a guess about a person's data.
    """

    DROP = "drop"
    KEEP = "keep"
    HASH = "hash"
    COARSEN = "coarsen"


class RespondentType(StrEnum):
    INDIVIDUAL = "individual"
    ORGANISATION = "organisation"
    PUBLIC_BODY = "public_body"
    ANONYMOUS = "anonymous"
    UNKNOWN = "unknown"


class QuestionMapping(StrEnum):
    """How a response came to be associated with a question.

    The export channel always produces EXPLICIT: the manifest names the
    question for every free-text column, so the mapping is a declared
    fact, never a guess. INFERRED and UNMAPPED are unused by this channel
    and will stay that way until a prose-submission channel exists, where
    a question is not tied to a column and has to be matched, or left
    unmatched. Keep them - they are not dead code, they are the seam the
    next channel plugs into.
    """

    EXPLICIT = "explicit"
    INFERRED = "inferred"
    UNMAPPED = "unmapped"


class TextQuality(StrEnum):
    """How a response's text was obtained.

    NATIVE text came from the export as typed. OCR text was recovered
    from an image or a scanned document and carries a higher chance of
    transcription error - a future confidence weighting or review queue
    can key off this without re-deriving it from provenance.
    """

    NATIVE = "native"
    OCR = "ocr"


class ResponseStatus(StrEnum):
    """Whether a response is fit for analysis.

    QUARANTINED responses are retained, not discarded: ingestion found a
    problem worth a human's attention, and silently dropping the row
    would hide exactly the rows most worth checking.
    """

    INGESTED = "ingested"
    QUARANTINED = "quarantined"
