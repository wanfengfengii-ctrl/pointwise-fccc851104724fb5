from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from lake.custody.catalog import CustodyCatalog, CustodyState
from lake.editions.manifest import EditionManifest, ManifestStore, summarize_edition
from lake.editions.rows import EditionRowStore, FrozenRow
from lake.storage import LakeError


@dataclass(frozen=True)
class BasisEvidence:
    manifest: EditionManifest
    rows: tuple[FrozenRow, ...]


def read_exact_basis(conn: sqlite3.Connection, edition_id: str) -> BasisEvidence:
    state = CustodyCatalog(conn).state_for(edition_id)
    if state == CustodyState.RECLAIMED:
        raise LakeError('basis_unavailable', f'Original rows of edition {edition_id!r} were reclaimed')
    manifest = ManifestStore(conn).find(edition_id)
    if manifest is None:
        raise LakeError('basis_unavailable', f'Edition {edition_id!r} has no manifest')
    rows = EditionRowStore(conn).read_exact(edition_id)
    if (any(row.position != position for position, row in enumerate(rows))
            or summarize_edition(edition_id, manifest.day, rows) != manifest):
        raise LakeError('basis_unavailable', f'Original rows of edition {edition_id!r} do not match its manifest')
    return BasisEvidence(manifest, rows)


@dataclass(frozen=True)
class BasisObligation:
    supplement_id: str
    edition_id: str
    binding: str
    row_count: int
    digest: str
    released: bool = False


class BasisObligations:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def initialize(self) -> None:
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS basis_obligations (
                supplement_id TEXT PRIMARY KEY,
                edition_id TEXT NOT NULL REFERENCES edition_manifests(edition_id),
                binding TEXT NOT NULL,
                row_count INTEGER NOT NULL CHECK (row_count >= 0),
                digest TEXT NOT NULL,
                released INTEGER NOT NULL DEFAULT 0 CHECK (released IN (0, 1))
            )
        ''')
        self.conn.execute('''
            CREATE INDEX IF NOT EXISTS basis_obligations_by_edition
            ON basis_obligations (edition_id, released)
        ''')

    @staticmethod
    def _decode(row: sqlite3.Row) -> BasisObligation:
        return BasisObligation(row['supplement_id'], row['edition_id'], row['binding'],
                               row['row_count'], row['digest'], bool(row['released']))

    def find(self, supplement_id: str) -> BasisObligation | None:
        row = self.conn.execute('''
            SELECT supplement_id, edition_id, binding, row_count, digest, released
            FROM basis_obligations WHERE supplement_id = ?
        ''', (supplement_id,)).fetchone()
        return None if row is None else self._decode(row)

    def note_open_read(self, supplement_id: str, manifest: EditionManifest, binding: str) -> bool:
        cursor = self.conn.execute("""
            INSERT INTO basis_obligations (supplement_id, edition_id, binding, row_count, digest)
            VALUES (?, ?, ?, ?, ?) ON CONFLICT(supplement_id) DO NOTHING
        """, (supplement_id, manifest.edition_id, binding, manifest.row_count, manifest.digest))
        return cursor.rowcount == 1

    def outstanding(self, edition_id: str) -> tuple[BasisObligation, ...]:
        rows = self.conn.execute('''
            SELECT supplement_id, edition_id, binding, row_count, digest, released
            FROM basis_obligations WHERE edition_id = ? AND released = 0 ORDER BY supplement_id
        ''', (edition_id,))
        return tuple(self._decode(row) for row in rows)

    def release(self, supplement_id: str) -> bool:
        """Drop the original-material obligation once a supplement is settled."""
        cursor = self.conn.execute('''
            UPDATE basis_obligations SET released = 1
            WHERE supplement_id = ? AND released = 0
        ''', (supplement_id,))
        return cursor.rowcount == 1
