from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class Issue:
    edition_id: str
    day: str
    batch_id: str


class EditionHistory:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def initialize(self) -> None:
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS edition_issues (
                issue_id TEXT PRIMARY KEY,
                edition_id TEXT NOT NULL UNIQUE,
                day TEXT NOT NULL,
                sequence INTEGER NOT NULL CHECK (sequence > 0),
                batch_id TEXT NOT NULL REFERENCES station_batches(batch_id),
                UNIQUE (day, sequence)
            )
        ''')

    def find_issue(self, issue_id: str) -> Issue | None:
        row = self.conn.execute('''
            SELECT edition_id, day, batch_id FROM edition_issues WHERE issue_id = ?
        ''', (issue_id,)).fetchone()
        return None if row is None else Issue(*row)

    def reserve_edition(self, day: str, batch_id: str, issue_id: str) -> str:
        sequence = self.conn.execute('''
            SELECT COALESCE(MAX(sequence), 0) + 1 FROM edition_issues WHERE day = ?
        ''', (day,)).fetchone()[0]
        edition_id = f'{day}#{sequence}'
        self.conn.execute('''
            INSERT INTO edition_issues (issue_id, edition_id, day, sequence, batch_id)
            VALUES (?, ?, ?, ?, ?)
        ''', (issue_id, edition_id, day, sequence, batch_id))
        return edition_id

    def latest_for_day(self, day: str) -> str | None:
        row = self.conn.execute('''
            SELECT edition_id FROM edition_issues WHERE day = ? ORDER BY sequence DESC LIMIT 1
        ''', (day,)).fetchone()
        return None if row is None else row['edition_id']
