from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass

from lake.editions.rows import FrozenRow
from lake.storage import encode_quantity, json_text


@dataclass(frozen=True)
class EditionManifest:
    edition_id: str
    day: str
    row_count: int
    missing_count: int
    digest: str


def summarize_edition(edition_id: str, day: str, rows: tuple[FrozenRow, ...]) -> EditionManifest:
    payload = [
        (row.position, encode_quantity(row.litres), row.source.batch_id,
         row.source.record_id, row.source.source_name)
        for row in rows
    ]
    digest = hashlib.sha256(json_text(payload).encode('ascii')).hexdigest()
    return EditionManifest(edition_id, day, len(rows), sum(row.missing for row in rows), digest)


class ManifestStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def initialize(self) -> None:
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS edition_manifests (
                edition_id TEXT PRIMARY KEY REFERENCES edition_issues(edition_id),
                day TEXT NOT NULL,
                row_count INTEGER NOT NULL CHECK (row_count >= 0),
                missing_count INTEGER NOT NULL CHECK (missing_count BETWEEN 0 AND row_count),
                digest TEXT NOT NULL
            )
        ''')

    def insert(self, manifest: EditionManifest) -> None:
        self.conn.execute('''
            INSERT INTO edition_manifests (edition_id, day, row_count, missing_count, digest)
            VALUES (?, ?, ?, ?, ?)
        ''', (manifest.edition_id, manifest.day, manifest.row_count, manifest.missing_count, manifest.digest))

    def find(self, edition_id: str) -> EditionManifest | None:
        row = self.conn.execute('''
            SELECT edition_id, day, row_count, missing_count, digest
            FROM edition_manifests WHERE edition_id = ?
        ''', (edition_id,)).fetchone()
        return None if row is None else EditionManifest(*row)
