from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, replace

from lake.receiving.commitments import PartCommitment
from lake.receiving.parts import Replacement, decode_replacements, encode_replacements
from lake.storage import json_text


@dataclass(frozen=True)
class SupplementRequest:
    supplement_id: str
    parent_id: str
    commitment: PartCommitment
    first_part_id: str
    first_replacements: tuple[Replacement, ...]
    status: str = 'staged'
    digest: str | None = None
    row_count: int | None = None

    @property
    def binding(self) -> str:
        terms = (self.supplement_id, self.parent_id, self.commitment.part_ids,
                 self.first_part_id, encode_replacements(self.first_replacements))
        return hashlib.sha256(json_text(terms).encode('ascii')).hexdigest()


class RequestStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def initialize(self) -> None:
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS supplement_requests (
                supplement_id TEXT PRIMARY KEY,
                parent_id TEXT NOT NULL,
                commitment_json TEXT NOT NULL,
                first_part_id TEXT NOT NULL,
                first_replacements_json TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('staged', 'rejected', 'admitted', 'settled')),
                digest TEXT,
                row_count INTEGER CHECK (row_count >= 0),
                CHECK (
                    (status IN ('staged', 'rejected') AND digest IS NULL AND row_count IS NULL)
                    OR (status IN ('admitted', 'settled') AND digest IS NOT NULL AND row_count IS NOT NULL)
                )
            )
        ''')

    def find(self, supplement_id: str) -> SupplementRequest | None:
        row = self.conn.execute('''
            SELECT supplement_id, parent_id, commitment_json, first_part_id,
                   first_replacements_json, status, digest, row_count
            FROM supplement_requests WHERE supplement_id = ?
        ''', (supplement_id,)).fetchone()
        if row is None:
            return None
        return SupplementRequest(
            row['supplement_id'], row['parent_id'], PartCommitment(tuple(json.loads(row['commitment_json']))),
            row['first_part_id'], decode_replacements(row['first_replacements_json']), row['status'],
            row['digest'], row['row_count'],
        )

    def prepare(
        self, supplement_id: str, parent_id: str, commitment: PartCommitment,
        first_part_id: str, first_replacements: tuple[Replacement, ...],
    ) -> SupplementRequest:
        self.conn.execute('''
            INSERT INTO supplement_requests (
                supplement_id, parent_id, commitment_json, first_part_id, first_replacements_json, status
            ) VALUES (?, ?, ?, ?, ?, 'staged')
        ''', (supplement_id, parent_id, json_text(commitment.part_ids), first_part_id,
              encode_replacements(first_replacements)))
        return SupplementRequest(supplement_id, parent_id, commitment, first_part_id, first_replacements)

    def record_admission(self, request: SupplementRequest, digest: str, row_count: int) -> SupplementRequest:
        self.conn.execute('''
            UPDATE supplement_requests SET status = 'admitted', digest = ?, row_count = ?
            WHERE supplement_id = ? AND status = 'staged'
        ''', (digest, row_count, request.supplement_id))
        return replace(request, status='admitted', digest=digest, row_count=row_count)

    def reject(self, supplement_id: str) -> None:
        self.conn.execute('''
            UPDATE supplement_requests SET status = 'rejected' WHERE supplement_id = ? AND status = 'staged'
        ''', (supplement_id,))

    def mark_settled(self, supplement_id: str) -> None:
        self.conn.execute('''
            UPDATE supplement_requests SET status = 'settled' WHERE supplement_id = ? AND status = 'admitted'
        ''', (supplement_id,))
