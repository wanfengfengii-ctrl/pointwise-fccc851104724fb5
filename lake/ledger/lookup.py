from __future__ import annotations

import sqlite3

from lake.ledger.publication import LedgerDelivery, LedgerStore
from lake.ledger.receipts import ReceiptStore
from lake.storage import LakeError


def read_ledger(conn: sqlite3.Connection, supplement_id: str) -> LedgerDelivery | None:
    ledger = LedgerStore(conn).find(supplement_id)
    receipt = ReceiptStore(conn).find(supplement_id)
    if ledger is None and receipt is None:
        return None
    if ledger is None or receipt is None:
        raise LakeError('invalid_ledger', f'Ledger and first receipt disagree for {supplement_id!r}')
    return LedgerDelivery(ledger, receipt)
