from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass

from lake.storage import LakeError, decode_quantity, encode_quantity, json_text


@dataclass(frozen=True)
class Replacement:
    position: int
    litres: int


@dataclass(frozen=True)
class PartSource:
    supplement_id: str
    part_id: str
    position: int


@dataclass(frozen=True)
class PartReceipt:
    supplement_id: str
    part_id: str
    replacements: tuple[Replacement, ...]
    missing: tuple[str, ...]


def validate_replacements(
    replacements: Iterable[Replacement], row_count: int | None = None, occupied: Iterable[int] = (),
) -> tuple[Replacement, ...]:
    seen = set(occupied)
    ordered = []
    for item in replacements:
        if (not isinstance(item, Replacement) or type(item.position) is not int or item.position < 0
                or (row_count is not None and item.position >= row_count)):
            raise LakeError('invalid_coordinate', 'Replacement position must be an existing zero-based row')
        if type(item.litres) is not int:
            raise LakeError('invalid_record', 'Replacement litres must be an integer')
        if item.position in seen:
            raise LakeError('overlap', f'Row {item.position} already has a replacement')
        seen.add(item.position)
        ordered.append(item)
    return tuple(sorted(ordered, key=lambda item: item.position))


def encode_replacements(replacements: tuple[Replacement, ...]) -> str:
    return json_text([(item.position, encode_quantity(item.litres)) for item in replacements])


def decode_replacements(payload: str) -> tuple[Replacement, ...]:
    return tuple(Replacement(position, decode_quantity(litres)) for position, litres in json.loads(payload))


class PartStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def initialize(self) -> None:
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS received_parts (
                supplement_id TEXT NOT NULL REFERENCES supplement_requests(supplement_id),
                part_id TEXT NOT NULL,
                replacements_json TEXT NOT NULL,
                missing_json TEXT NOT NULL,
                PRIMARY KEY (supplement_id, part_id)
            )
        ''')

    @staticmethod
    def _decode(row: sqlite3.Row) -> PartReceipt:
        return PartReceipt(row['supplement_id'], row['part_id'], decode_replacements(row['replacements_json']),
                           tuple(json.loads(row['missing_json'])))

    def find(self, supplement_id: str, part_id: str) -> PartReceipt | None:
        row = self.conn.execute('''
            SELECT supplement_id, part_id, replacements_json, missing_json FROM received_parts
            WHERE supplement_id = ? AND part_id = ?
        ''', (supplement_id, part_id)).fetchone()
        return None if row is None else self._decode(row)

    def insert(
        self, supplement_id: str, part_id: str, replacements: tuple[Replacement, ...], missing: tuple[str, ...],
    ) -> PartReceipt:
        self.conn.execute('''
            INSERT INTO received_parts (supplement_id, part_id, replacements_json, missing_json)
            VALUES (?, ?, ?, ?)
        ''', (supplement_id, part_id, encode_replacements(replacements), json_text(missing)))
        return PartReceipt(supplement_id, part_id, replacements, missing)

    def list_received(self, supplement_id: str) -> tuple[PartReceipt, ...]:
        rows = self.conn.execute('''
            SELECT supplement_id, part_id, replacements_json, missing_json FROM received_parts
            WHERE supplement_id = ? ORDER BY part_id
        ''', (supplement_id,))
        return tuple(self._decode(row) for row in rows)
