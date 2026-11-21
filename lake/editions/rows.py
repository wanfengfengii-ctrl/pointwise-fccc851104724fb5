from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from lake.feed.provenance import ReportSource
from lake.feed.records import NormalizedRecord
from lake.storage import decode_quantity, encode_quantity


@dataclass(frozen=True)
class FrozenRow:
    position: int
    litres: int | None
    source: ReportSource

    @property
    def missing(self) -> bool:
        return self.litres is None


def freeze_rows(records: tuple[NormalizedRecord, ...]) -> tuple[FrozenRow, ...]:
    return tuple(FrozenRow(position, row.litres, row.source) for position, row in enumerate(records))


class EditionRowStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def initialize(self) -> None:
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS frozen_rows (
                edition_id TEXT NOT NULL REFERENCES edition_manifests(edition_id),
                position INTEGER NOT NULL CHECK (position >= 0),
                litres TEXT,
                batch_id TEXT NOT NULL,
                record_id TEXT NOT NULL,
                source_name TEXT NOT NULL,
                PRIMARY KEY (edition_id, position)
            )
        ''')

    def insert(self, edition_id: str, rows: tuple[FrozenRow, ...]) -> None:
        self.conn.executemany('''
            INSERT INTO frozen_rows (edition_id, position, litres, batch_id, record_id, source_name)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            (edition_id, row.position, encode_quantity(row.litres), row.source.batch_id,
             row.source.record_id, row.source.source_name)
            for row in rows
        ))

    def read_exact(self, edition_id: str) -> tuple[FrozenRow, ...]:
        records = self.conn.execute('''
            SELECT position, litres, batch_id, record_id, source_name
            FROM frozen_rows WHERE edition_id = ? ORDER BY position
        ''', (edition_id,))
        return tuple(
            FrozenRow(row['position'], decode_quantity(row['litres']),
                      ReportSource(row['batch_id'], row['record_id'], row['source_name']))
            for row in records
        )

    def delete_exact(self, edition_id: str) -> None:
        self.conn.execute('DELETE FROM frozen_rows WHERE edition_id = ?', (edition_id,))
