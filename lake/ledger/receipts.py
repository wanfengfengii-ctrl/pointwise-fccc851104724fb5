from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class FirstReceipt:
    supplement_id: str
    number: int


class ReceiptStore:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def initialize(self) -> None:
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS first_receipts (
                number INTEGER PRIMARY KEY,
                supplement_id TEXT NOT NULL UNIQUE REFERENCES fixed_ledgers(supplement_id)
            )
        ''')

    def insert(self, supplement_id: str) -> FirstReceipt:
        cursor = self.conn.execute('INSERT INTO first_receipts (supplement_id) VALUES (?)', (supplement_id,))
        return FirstReceipt(supplement_id, cursor.lastrowid)

    def find(self, supplement_id: str) -> FirstReceipt | None:
        row = self.conn.execute('SELECT number FROM first_receipts WHERE supplement_id = ?', (supplement_id,)).fetchone()
        return None if row is None else FirstReceipt(supplement_id, row['number'])
