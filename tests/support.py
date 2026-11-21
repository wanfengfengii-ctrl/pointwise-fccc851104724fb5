import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from lake import Archive, Custodian, LakeError, PartCommitment, RawRecord, Receiving, Replacement, initialize
from lake.editions.rows import EditionRowStore
from lake.ledger.publication import LedgerStore
from lake.ledger.receipts import ReceiptStore
from lake.receiving.parts import PartStore
from lake.receiving.requests import RequestStore
from lake.storage import Database


DAY = '2026-10-12'
COMMITMENT = PartCommitment(('white', 'night'))
HEAD = (Replacement(0, 8),)
TAIL = (Replacement(1, 13),)


class Interrupted(RuntimeError):
    pass


class LakeTestCase(unittest.TestCase):
    def setUp(self):
        work = TemporaryDirectory(prefix='qingting-test-')
        self.addCleanup(work.cleanup)
        self.directory = Path(work.name)
        initialize(self.directory)
        self.archive = Archive(self.directory)
        self.keeper = Custodian(self.directory)
        self.receiving = Receiving(self.directory)
        self.custody_db = Database(self.directory / 'custody.sqlite3')
        self.receiving_db = Database(self.directory / 'receiving.sqlite3')

    def issue(self, tail=5, batch_id='morning', issue_id='first'):
        self.archive.ingest(batch_id, (
            RawRecord('up', '北堤', 7000, 'mL'),
            RawRecord('mid', '南堤', 11, 'L'),
            RawRecord('tail', '尾闸' if batch_id == 'morning' else '尾闸复报', tail, 'L'),
        ))
        return self.archive.freeze_edition(DAY, batch_id, issue_id).edition_id

    def submit(self, parent, part='white', replacements=HEAD, identifier='A', *, receiving=None, commitment=COMMITMENT):
        client = self.receiving if receiving is None else receiving
        return client.submit_part(identifier, parent, commitment, part, replacements)

    def assert_code(self, code, operation, *args, **kwargs):
        with self.assertRaises(LakeError) as raised:
            operation(*args, **kwargs)
        self.assertEqual(raised.exception.code, code)
        return raised.exception

    def assert_unpublished(self, identifier='A'):
        self.assertIsNone(Receiving(self.directory).read_ledger(identifier))
        with self.receiving_db.transaction() as conn:
            self.assertIsNone(LedgerStore(conn).find(identifier))
            self.assertIsNone(ReceiptStore(conn).find(identifier))

    def persisted_receipts(self):
        with self.receiving_db.transaction() as conn:
            return conn.execute('SELECT COUNT(*) FROM first_receipts').fetchone()[0]

    def receipt_state(self, identifier='A'):
        with self.receiving_db.transaction() as conn:
            request = RequestStore(conn).find(identifier)
            parts = PartStore(conn).list_received(identifier)
        return (None if request is None else request.status), tuple(part.part_id for part in parts)

    def physical_rows(self, parent):
        with self.custody_db.transaction() as conn:
            return EditionRowStore(conn).read_exact(parent)
