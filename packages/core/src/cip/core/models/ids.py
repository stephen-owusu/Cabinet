"""Content-addressed identity.

Every id is a deterministic digest of the coordinates that produced it -
never a counter, never randomness. Re-running ingestion over the same
source must yield the same ids, which is what makes the pipeline safe to
interrupt and safe to re-run: a partial run and a full rerun converge on
the same identifiers instead of duplicating records.

Each function hashes a type-specific namespace ahead of its inputs and
tags the returned id with that namespace, so a submission id and a
response id cannot collide even if their inputs happened to coincide.
"""

from __future__ import annotations

import hashlib


def _digest(namespace: str, *parts: str) -> str:
    payload = "\x1f".join((namespace, *parts))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def submission_id(consultation: str, source_sha: str, row_key: str) -> str:
    """Identity for one export row.

    Keyed on the source file's hash and the row's position within it, so
    the same row re-parsed from the same file always resolves to the same
    submission, and a different export of the same consultation does not
    collide with it.
    """
    return f"submission_{_digest('submission', consultation, source_sha, row_key)}"


def response_id(submission: str, column: str) -> str:
    """Identity for one cell.

    Keyed on position - submission and column - not on the text in the
    cell. A corrected typo in a later re-parse of the same source must
    still resolve to the same response, so an edit is visible as history
    rather than as a new, unrelated record.
    """
    return f"response_{_digest('response', submission, column)}"


def question_id(consultation: str, key: str) -> str:
    """Identity for one question, stable across manifest revisions that
    do not change the question's key."""
    return f"question_{_digest('question', consultation, key)}"


def attachment_id(submission: str, filename: str, content_sha: str) -> str:
    """Identity for one attachment.

    Keyed on content as well as filename: two files with the same name
    but different bytes are different attachments, while the same bytes
    re-uploaded under the same name resolve to the same one.
    """
    return f"attachment_{_digest('attachment', submission, filename, content_sha)}"


def content_hash(text: str) -> str:
    """Digest of a response's text, insensitive to whitespace and case.

    Used to detect when re-parsing the same cell produced the same
    analysable content, independent of incidental formatting differences
    an export step might introduce.
    """
    normalised = " ".join(text.split()).casefold()
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()
