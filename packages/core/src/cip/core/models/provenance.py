"""Where a fact came from, fixed at parse time.

Provenance is attached once, when a submission or response is first
parsed from its source, and carried forward untouched from then on.
Story 3 verifies every generated claim against these exact coordinates;
provenance reconstructed after the fact - guessed from content instead of
recorded at the moment of parsing - would verify nothing.
"""

from __future__ import annotations

from typing import Annotated, Literal

from cip.core.models.enums import SourceFormat
from pydantic import BaseModel, ConfigDict, Field


class CellLocator(BaseModel):
    """A single cell in a tabular export: sheet, row, column."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["cell"] = "cell"
    sheet: str
    row: int
    column: str


class SpanLocator(BaseModel):
    """A character span within a page.

    Not used by the export channel yet - added now because a
    discriminated union gains a new variant far more easily than it
    gains its first discriminator later, once Locator is already in wide
    use as a bare CellLocator.
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal["span"] = "span"
    page: int
    char_start: int
    char_end: int


Locator = Annotated[CellLocator | SpanLocator, Field(discriminator="kind")]


class Provenance(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_uri: str
    source_sha256: str
    source_format: SourceFormat
    locator: Locator
    manifest_version: int
