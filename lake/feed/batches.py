from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from lake.feed.provenance import ReportSource
from lake.feed.records import NormalizedRecord, RawRecord
from lake.storage import decode_quantity, encode_quantity, json_text


@dataclass(frozen=True)
class StationBatch:
    batch_id: str
    raw_records: tuple[RawRecord, ...]
    rows: tuple[NormalizedRecord, ...]
    missing_count: int

    @property
    def valid_litres(self) -> tuple[int, ...]:
        return tuple(row.litres for row in self.rows if not row.missing)


class BatchStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def initialize(self) -> None:
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS station_batches (
                batch_id TEXT PRIMARY KEY,
                raw_json TEXT NOT NULL,
                normalized_json TEXT NOT NULL,
                missing_count INTEGER NOT NULL CHECK (missing_count >= 0)
            )
        ''')

    def find(self, batch_id: str) -> StationBatch | None:
        row = self.conn.execute(
            'SELECT raw_json, normalized_json, missing_count FROM station_batches WHERE batch_id = ?',
            (batch_id,),
        ).fetchone()
        if row is None:
            return None
        raw = tuple(
            RawRecord(record_id, name, decode_quantity(value), unit, missing)
            for record_id, name, value, unit, missing in json.loads(row['raw_json'])
        )
        normalized = tuple(
            NormalizedRecord(decode_quantity(litres), ReportSource(batch_id, record_id, name))
            for record_id, name, litres in json.loads(row['normalized_json'])
        )
        return StationBatch(batch_id, raw, normalized, row['missing_count'])

    def insert(self, batch: StationBatch) -> None:
        raw = [
            (row.record_id, row.source_name, encode_quantity(row.value), row.unit, row.missing)
            for row in batch.raw_records
        ]
        normalized = [
            (row.source.record_id, row.source.source_name, encode_quantity(row.litres))
            for row in batch.rows
        ]
        self.conn.execute(
            'INSERT INTO station_batches (batch_id, raw_json, normalized_json, missing_count) VALUES (?, ?, ?, ?)',
            (batch.batch_id, json_text(raw), json_text(normalized), batch.missing_count),
        )
