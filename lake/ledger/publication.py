from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass

from lake.ledger.detail import LedgerLine, decode_detail, encode_detail
from lake.ledger.receipts import FirstReceipt, ReceiptStore
from lake.ledger.totals import LedgerTotals, calculate_totals
from lake.storage import decode_quantity, encode_quantity, json_text


@dataclass(frozen=True)
class FixedLedger:
    supplement_id: str
    parent_id: str
    lines: tuple[LedgerLine, ...]
    totals: LedgerTotals


@dataclass(frozen=True)
class LedgerDelivery:
    ledger: FixedLedger
    receipt: FirstReceipt


class LedgerStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def initialize(self) -> None:
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS fixed_ledgers (
                supplement_id TEXT PRIMARY KEY REFERENCES supplement_requests(supplement_id),
                parent_id TEXT NOT NULL,
                detail_json TEXT NOT NULL,
                litres TEXT NOT NULL,
                missing_count INTEGER NOT NULL CHECK (missing_count >= 0),
                missing_json TEXT NOT NULL
            )
        ''')

    def find(self, supplement_id: str) -> FixedLedger | None:
        row = self.conn.execute('''
            SELECT parent_id, detail_json, litres, missing_count, missing_json
            FROM fixed_ledgers WHERE supplement_id = ?
        ''', (supplement_id,)).fetchone()
        if row is None:
            return None
        totals = LedgerTotals(decode_quantity(row['litres']), row['missing_count'], tuple(json.loads(row['missing_json'])))
        return FixedLedger(supplement_id, row['parent_id'], decode_detail(row['detail_json']), totals)

    def insert(self, ledger: FixedLedger) -> None:
        self.conn.execute('''
            INSERT INTO fixed_ledgers (supplement_id, parent_id, detail_json, litres, missing_count, missing_json)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (ledger.supplement_id, ledger.parent_id, encode_detail(ledger.lines), encode_quantity(ledger.totals.litres),
              ledger.totals.missing_count, json_text(ledger.totals.missing_positions)))


def publish_ledger(
    conn: sqlite3.Connection, supplement_id: str, parent_id: str, lines: tuple[LedgerLine, ...],
) -> LedgerDelivery:
    ledger = FixedLedger(supplement_id, parent_id, lines, calculate_totals(lines))
    LedgerStore(conn).insert(ledger)
    receipt = ReceiptStore(conn).insert(supplement_id)
    return LedgerDelivery(ledger, receipt)
