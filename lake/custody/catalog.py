import sqlite3
from enum import StrEnum

from lake.editions.manifest import ManifestStore
from lake.storage import LakeError


class CustodyState(StrEnum):
    OPEN = 'open'
    EXPIRED = 'expired'
    RECLAIMED = 'reclaimed'


class CustodyCatalog:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def initialize(self) -> None:
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS custody_retirements (
                edition_id TEXT PRIMARY KEY REFERENCES edition_manifests(edition_id),
                state TEXT NOT NULL CHECK (state IN ('expired', 'reclaimed'))
            )
        ''')

    def state_for(self, edition_id: str) -> CustodyState:
        row = self.conn.execute(
            'SELECT state FROM custody_retirements WHERE edition_id = ?', (edition_id,),
        ).fetchone()
        if row is not None:
            return CustodyState(row['state'])
        if ManifestStore(self.conn).find(edition_id) is None:
            raise LakeError('unknown_edition', f'Unknown edition {edition_id!r}')
        return CustodyState.OPEN

    def mark_expired(self, edition_id: str) -> None:
        self.conn.execute('''
            INSERT INTO custody_retirements (edition_id, state) VALUES (?, 'expired')
            ON CONFLICT(edition_id) DO NOTHING
        ''', (edition_id,))

    def mark_reclaimed(self, edition_id: str) -> None:
        self.conn.execute('''
            UPDATE custody_retirements SET state = 'reclaimed'
            WHERE edition_id = ? AND state = 'expired'
        ''', (edition_id,))
