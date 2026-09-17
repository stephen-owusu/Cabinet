"""Parsers: turn a validated export into domain records.

Each module here handles one source format. All of them take a
ValidatedManifest, never a plain Manifest - the parser boundary is a
type error for anything that has not actually been checked against its
source file.
"""
